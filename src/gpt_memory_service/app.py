"""FastAPI application for the GPT Memory Service.

The FastAPI instance is exported as ``app`` and configured to expose
health/version routes in addition to the memory management endpoints.
"""

import copy
import json
import logging
import os
from datetime import datetime
from difflib import unified_diff
import shutil
from tempfile import NamedTemporaryFile
import threading
from typing import Any, Dict, List, Optional
import time

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .version import __version__

# ---------- Logging ----------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

# ---------- File paths ----------
MEMORY_FILE = "memory.json"
BACKUP_FILE = "memory_backup.json"
AUDIT_LOG_FILE = "memory_audit.log"


# ---------- Helpers: save / load with backup + restore ----------
def save_memory(data: Dict[str, Any]):
    """Atomic write with automatic backup rotation."""
    tmp: Optional[NamedTemporaryFile] = None
    try:
        if os.path.exists(MEMORY_FILE):
            shutil.copy2(MEMORY_FILE, BACKUP_FILE)
            logging.info("Backup created: %s → %s", MEMORY_FILE, BACKUP_FILE)

        tmp = NamedTemporaryFile("w", delete=False, dir=".")
        json.dump(data, tmp, indent=2, ensure_ascii=False)
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp.close()
        os.replace(tmp.name, MEMORY_FILE)
        logging.info("Memory saved successfully to %s", MEMORY_FILE)
    except Exception as e:
        logging.error("Failed to save memory: %s", e)
        if tmp and os.path.exists(tmp.name):
            os.remove(tmp.name)
        raise


def load_memory() -> Dict[str, Any]:
    """Load memory, auto-restore from backup if corrupted."""
    if not os.path.exists(MEMORY_FILE):
        logging.info("No memory file found, starting fresh.")
        return {}
    try:
        with open(MEMORY_FILE, "r") as f:
            data = json.load(f)
            logging.info("Loaded memory from %s", MEMORY_FILE)
            return data
    except json.JSONDecodeError as e:
        logging.warning("Corrupted memory file detected: %s", e)
        if os.path.exists(BACKUP_FILE):
            logging.warning("Restoring from backup: %s", BACKUP_FILE)
            shutil.copy2(BACKUP_FILE, MEMORY_FILE)
            with open(MEMORY_FILE, "r") as f:
                return json.load(f)
        logging.error("No backup found. Starting empty.")
        return {}
    except Exception as e:
        logging.error("Unexpected load error: %s", e)
        return {}


# ---------- Pydantic models ----------
class Profile(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    preferences: Optional[Dict[str, Any]] = None


class WorkingMemory(BaseModel):
    current_focus_thread: Optional[str] = ""
    active_priorities: Optional[List[str]] = Field(default_factory=list)
    open_loops: Optional[List[str]] = Field(default_factory=list)
    decisions_made: Optional[List[Dict[str, Any]]] = Field(default_factory=list)
    pending_follow_ups: Optional[List[Dict[str, Any]]] = Field(default_factory=list)


class LongTermKnowledge(BaseModel):
    projects: Optional[List[Any]] = Field(default_factory=list)
    stakeholders: Optional[List[Any]] = Field(default_factory=list)
    systems: Optional[List[Any]] = Field(default_factory=list)


class MemoryCreate(BaseModel):
    profile: Optional[Profile] = None
    working_memory: Optional[WorkingMemory] = None
    long_term_knowledge: Optional[LongTermKnowledge] = None
    session_snapshots: Optional[List[Any]] = Field(default_factory=list)


class MemoryPatch(BaseModel):
    profile: Optional[Dict[str, Any]] = None
    working_memory: Optional[Dict[str, Any]] = None
    long_term_knowledge: Optional[Dict[str, Any]] = None
    session_snapshots: Optional[Any] = None


class Memory(BaseModel):
    user_id: str
    profile: Optional[Profile] = None
    working_memory: Optional[WorkingMemory] = None
    long_term_knowledge: Optional[LongTermKnowledge] = None
    session_snapshots: Optional[List[Any]] = Field(default_factory=list)


# ---------- FastAPI setup ----------
app = FastAPI(
    title="Blake Memory Service",
    description=(
        "Persistent memory API for the APM Focus Co-Pilot GPT "
        "(with backups, validation, autosave, and audit logging)"
    ),
    version=__version__,
    openapi_version="3.1.0",
    servers=[{"url": "https://unhemmed-pseudoacademically-tatum.ngrok-free.dev"}],
)


# ---------- Root + utility routes ----------
@app.get("/")
async def root():
    return {"status": "OK", "message": "Blake Memory Service running inside venv."}


@app.get("/health", summary="Health check")
async def health():
    return {"status": "ok"}


@app.get("/version", summary="Service version")
async def version():
    return {"version": __version__}


@app.get("/openapi.json", include_in_schema=False)
async def custom_openapi():
    """Serve static openapi.json for GPT integration."""
    if os.path.exists("openapi.json"):
        with open("openapi.json", "r") as f:
            data = json.load(f)
        return JSONResponse(content=data)
    return JSONResponse(content={"error": "openapi.json not found"}, status_code=404)


# ---------- Global state ----------
_raw_state = load_memory()
MEMORY_STORE: Dict[str, Memory] = {uid: Memory(**data) for uid, data in _raw_state.items()}
_state_lock = threading.Lock()
_last_saved_state = json.dumps(_raw_state, sort_keys=True)


# ---------- Deep merge utility ----------
def deep_merge(existing: Dict[str, Any], updates: Dict[str, Any]) -> Dict[str, Any]:
    merged = copy.deepcopy(existing)
    for key, value in updates.items():
        if value is None:
            continue
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        elif isinstance(value, list) and isinstance(merged.get(key), list):
            existing_list = list(merged.get(key, []))
            for item in value:
                if item not in existing_list:
                    existing_list.append(item)
            merged[key] = existing_list
        else:
            merged[key] = value
    return merged


# ---------- Validation + Safe Save ----------
def validate_memory_structure(data: Dict[str, Any]) -> bool:
    try:
        for uid, record in data.items():
            Memory(**record)
        return True
    except Exception as e:
        logging.error("Memory validation failed: %s", e)
        return False


# ---------- Audit Logging ----------
def audit_log(action: str, user_id: str, before: Dict[str, Any], after: Dict[str, Any]):
    """Write a structured audit event with timestamp + diff."""
    timestamp = datetime.now().isoformat()
    before_json = json.dumps(before, indent=2, sort_keys=True)
    after_json = json.dumps(after, indent=2, sort_keys=True)
    diff = "\n".join(
        unified_diff(
            before_json.splitlines(),
            after_json.splitlines(),
            fromfile="before",
            tofile="after",
            lineterm="",
        )
    )
    event = {"timestamp": timestamp, "action": action, "user_id": user_id, "diff": diff}
    with open(AUDIT_LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(event) + "\n")
    logging.info("Audit logged: %s for %s", action, user_id)


# ---------- Safe save wrapper ----------
def safe_save_memory(action: str = "unspecified", user_id: str = "unknown"):
    global _last_saved_state
    snapshot_before = json.loads(_last_saved_state)
    snapshot_after = {uid: m.model_dump() for uid, m in MEMORY_STORE.items()}

    if not validate_memory_structure(snapshot_after):
        logging.error("Aborting save: validation failed.")
        return False

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    try:
        if os.path.exists(MEMORY_FILE):
            shutil.copy2(MEMORY_FILE, f"memory_backup_{ts}.json")
            logging.info("Incremental backup created: memory_backup_%s.json", ts)
    except FileNotFoundError:
        pass

    save_memory(snapshot_after)
    _last_saved_state = json.dumps(snapshot_after, sort_keys=True)
    audit_log(action, user_id, snapshot_before.get(user_id, {}), snapshot_after.get(user_id, {}))
    return True


# ---------- Autosave ----------
def autosave_loop(interval_sec: int = 300):
    global _last_saved_state
    logging.info("Starting autosave thread (%ss interval)", interval_sec)
    while not _autosave_stop_event.wait(interval_sec):
        with _state_lock:
            current_state = json.dumps({uid: m.model_dump() for uid, m in MEMORY_STORE.items()}, sort_keys=True)
            if current_state != _last_saved_state:
                save_memory(json.loads(current_state))
                _last_saved_state = current_state
                logging.info("Autosave triggered (state changed).")
    logging.info("Autosave thread stopping.")


_autosave_stop_event = threading.Event()
_autosave_thread: Optional[threading.Thread] = None


@app.on_event("startup")
def start_autosave():
    global _autosave_thread
    if _autosave_thread and _autosave_thread.is_alive():
        return
    _autosave_stop_event.clear()
    _autosave_thread = threading.Thread(target=autosave_loop, daemon=True)
    _autosave_thread.start()


@app.on_event("shutdown")
def stop_autosave():
    _autosave_stop_event.set()
    if _autosave_thread:
        _autosave_thread.join(timeout=5)


# ---------- Routes ----------
@app.get("/memory/{user_id}", summary="Get Memory", response_model=Memory)
def get_memory(user_id: str) -> Memory:
    mem = MEMORY_STORE.get(user_id)
    if mem is None:
        raise HTTPException(status_code=404, detail="Memory not found")
    return mem


@app.post("/memory/{user_id}", summary="Create Memory", response_model=Memory)
def create_memory(user_id: str, payload: MemoryCreate, overwrite: bool = False) -> Memory:
    """Create memory; prevent overwrite unless explicitly allowed."""
    if user_id in MEMORY_STORE and not overwrite:
        raise HTTPException(
            status_code=409,
            detail=f"Memory for '{user_id}' already exists. Use PATCH or set ?overwrite=true."
        )
    mem = Memory(user_id=user_id, **payload.model_dump())
    with _state_lock:
        MEMORY_STORE[user_id] = mem
        safe_save_memory(action="create", user_id=user_id)
    return mem


@app.patch("/memory/{user_id}", summary="Patch Memory", response_model=Memory)
def patch_memory(user_id: str, payload: MemoryPatch) -> Memory:
    existing = MEMORY_STORE.get(user_id)
    base_data: Dict[str, Any] = existing.model_dump() if existing else {}
    updates = payload.model_dump(exclude_unset=True)
    merged = deep_merge(base_data, updates)
    merged.pop("user_id", None)
    mem = Memory(user_id=user_id, **merged)
    with _state_lock:
        MEMORY_STORE[user_id] = mem
        safe_save_memory(action="patch", user_id=user_id)
    return mem
