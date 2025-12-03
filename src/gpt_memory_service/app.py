"""FastAPI application for the GPT Memory Service.

The FastAPI instance is exported as ``app`` and configured to expose
health/version routes in addition to the memory management endpoints.
"""

import asyncio
import copy
import json
import logging
import os
from datetime import datetime
from difflib import unified_diff
import shutil
from tempfile import NamedTemporaryFile
import threading
from typing import Any, Dict, List, Optional, Tuple
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
MAX_CONTEXT_FEEDS = 500  # guardrail to prevent unbounded growth from transcript ingestion


# ---------- Helpers: save / load with backup + restore ----------
def save_memory(data: Dict[str, Any]):
    """Atomic write with automatic backup rotation."""
    tmp: Optional[NamedTemporaryFile] = None
    tmp_path: Optional[str] = None
    try:
        if os.path.exists(MEMORY_FILE):
            shutil.copy2(MEMORY_FILE, BACKUP_FILE)
            logging.info("Backup created: %s → %s", MEMORY_FILE, BACKUP_FILE)

        tmp = NamedTemporaryFile("w", delete=False, dir=".")
        tmp_path = tmp.name
        try:
            json.dump(data, tmp, indent=2, ensure_ascii=False)
            tmp.flush()
            os.fsync(tmp.fileno())
        finally:
            try:
                tmp.close()
            except Exception as close_err:
                logging.warning("Failed to close temp file %s: %s", tmp_path, close_err)

        if not tmp_path:
            raise RuntimeError("Temporary file was not created for save operation")

        os.replace(tmp_path, MEMORY_FILE)
        logging.info("Memory saved successfully to %s", MEMORY_FILE)
    except Exception as e:
        logging.error("Failed to save memory: %s", e)
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError as cleanup_err:
                logging.warning("Failed to clean up temp file %s: %s", tmp_path, cleanup_err)
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


class ContextFeedEntry(BaseModel):
    """Structured snapshot from the Meeting Synth Co-Pilot."""

    id: Optional[str] = Field(
        default=None,
        description="Stable identifier for deduplication (meeting id, transcript hash, etc.)",
    )
    title: Optional[str] = Field(default=None, description="Human-friendly meeting title")
    captured_at: Optional[str] = Field(
        default=None,
        description="ISO8601 timestamp when this summary was produced",
    )
    summary: Optional[str] = None
    decisions: Optional[List[str]] = Field(default_factory=list)
    follow_ups: Optional[List[str]] = Field(default_factory=list)
    open_loops: Optional[List[str]] = Field(default_factory=list)
    metadata: Optional[Dict[str, Any]] = Field(
        default_factory=dict,
        description="Arbitrary machine-readable hints (e.g., participants, tags)",
    )


class MemoryCreate(BaseModel):
    profile: Optional[Profile] = None
    working_memory: Optional[WorkingMemory] = None
    long_term_knowledge: Optional[LongTermKnowledge] = None
    session_snapshots: Optional[List[Any]] = Field(default_factory=list)
    context_feeds: Optional[List[ContextFeedEntry]] = Field(default_factory=list)


class MemoryPatch(BaseModel):
    profile: Optional[Dict[str, Any]] = None
    working_memory: Optional[Dict[str, Any]] = None
    long_term_knowledge: Optional[Dict[str, Any]] = None
    session_snapshots: Optional[Any] = None
    context_feeds: Optional[List[ContextFeedEntry]] = None
    context_feeds_overwrite: Optional[bool] = Field(
        default=False,
        description=(
            "When true, replaces the entire context_feeds array instead of appending. "
            "Default False for backward-safe merging."
        ),
    )


class Memory(BaseModel):
    user_id: str
    profile: Optional[Profile] = None
    working_memory: Optional[WorkingMemory] = None
    long_term_knowledge: Optional[LongTermKnowledge] = None
    session_snapshots: Optional[List[Any]] = Field(default_factory=list)
    context_feeds: Optional[List[ContextFeedEntry]] = Field(default_factory=list)


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
        existing_value = merged.get(key)
        if isinstance(value, dict) and isinstance(existing_value, dict):
            merged[key] = deep_merge(existing_value, value)
        elif isinstance(value, list) and isinstance(existing_value, list):
            existing_list = list(existing_value)
            for item in value:
                if item not in existing_list:
                    existing_list.append(copy.deepcopy(item))
            merged[key] = existing_list
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def normalize_context_feeds(raw_feeds: Optional[List[Any]]) -> List[Dict[str, Any]]:
    """Ensure context_feeds entries are dicts with timestamps and without ``None`` values."""

    normalized: List[Dict[str, Any]] = []
    now_iso = datetime.utcnow().isoformat()

    for feed in raw_feeds or []:
        if isinstance(feed, ContextFeedEntry):
            feed_dict = feed.model_dump(exclude_none=True)
        elif isinstance(feed, dict):
            feed_dict = {k: v for k, v in feed.items() if v is not None}
        else:
            raise HTTPException(status_code=400, detail="context_feeds entries must be objects")

        # auto-fill timestamp to preserve ordering and auditability
        if not feed_dict.get("captured_at"):
            feed_dict["captured_at"] = now_iso

        normalized.append(feed_dict)

    # Keep the most recent entries when trimming so new context feeds are not dropped
    return normalized[-MAX_CONTEXT_FEEDS:]


def _context_feed_key(feed: Dict[str, Any]) -> Tuple[str, str, str, str]:
    """Create a stable deduplication key; tolerant to missing identifiers."""

    return (
        str(feed.get("id") or ""),
        str(feed.get("captured_at") or ""),
        str(feed.get("title") or ""),
        str(feed.get("summary") or ""),
    )


def merge_context_feeds(
    existing: Optional[List[Any]], updates: Optional[List[Any]], overwrite: bool = False
) -> List[Dict[str, Any]]:
    """
    Merge context_feeds safely:

    * Default behavior (overwrite=False): append new items, keep unique by (id, captured_at, title, summary).
    * overwrite=True: replace the entire array explicitly (useful for cleanup/compaction).
    * Enforces MAX_CONTEXT_FEEDS to avoid unbounded growth from large transcripts.
    """

    existing_normalized = normalize_context_feeds(existing)
    updates_normalized = normalize_context_feeds(updates)

    if overwrite:
        merged = updates_normalized
    else:
        seen = {_context_feed_key(feed) for feed in existing_normalized}
        merged = list(existing_normalized)
        for feed in updates_normalized:
            key = _context_feed_key(feed)
            if key not in seen:
                merged.append(feed)
                seen.add(key)

    # keep newest entries last and trimmed
    if len(merged) > MAX_CONTEXT_FEEDS:
        merged = merged[-MAX_CONTEXT_FEEDS:]

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


# ---------- Continuous auto-save ----------
async def autosave_loop(app: FastAPI, interval_sec: int = 300):
    global _last_saved_state
    logging.info("Starting autosave task (%ss interval)", interval_sec)
    try:
        while not app.state.autosave_stop_event.is_set():
            await asyncio.sleep(interval_sec)
            with _state_lock:
                current_state = json.dumps({uid: m.model_dump() for uid, m in MEMORY_STORE.items()}, sort_keys=True)
                if current_state != _last_saved_state:
                    save_memory(json.loads(current_state))
                    _last_saved_state = current_state
                    logging.info("Autosave triggered (state changed).")
    except asyncio.CancelledError:
        logging.info("Autosave task cancelled.")
        raise
    finally:
        logging.info("Autosave task stopping.")


@app.on_event("startup")
async def start_autosave():
    if getattr(app.state, "autosave_task", None):
        return
    app.state.autosave_stop_event = asyncio.Event()
    app.state.autosave_task = asyncio.create_task(autosave_loop(app))


@app.on_event("shutdown")
async def stop_autosave():
    stop_event: asyncio.Event = getattr(app.state, "autosave_stop_event", asyncio.Event())
    stop_event.set()
    autosave_task: Optional[asyncio.Task] = getattr(app.state, "autosave_task", None)
    if autosave_task:
        autosave_task.cancel()
        try:
            await autosave_task
        except asyncio.CancelledError:
            pass


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
    payload_data = payload.model_dump()
    payload_context = payload_data.pop("context_feeds", None)
    if payload_context is not None:
        payload_data["context_feeds"] = merge_context_feeds([], payload_context, overwrite=True)

    mem = Memory(user_id=user_id, **payload_data)
    with _state_lock:
        MEMORY_STORE[user_id] = mem
        safe_save_memory(action="create", user_id=user_id)
    return mem


@app.patch("/memory/{user_id}", summary="Patch Memory", response_model=Memory)
def patch_memory(user_id: str, payload: MemoryPatch) -> Memory:
    existing = MEMORY_STORE.get(user_id)
    base_data: Dict[str, Any] = existing.model_dump() if existing else {}
    updates = payload.model_dump(exclude_unset=True)
    context_feeds_updates = updates.pop("context_feeds", None)
    context_feeds_overwrite = updates.pop("context_feeds_overwrite", False)

    merged = deep_merge(base_data, updates)
    existing_feeds = base_data.get("context_feeds") or []
    if context_feeds_updates is not None or existing_feeds:
        merged["context_feeds"] = merge_context_feeds(
            existing_feeds,
            context_feeds_updates or [],
            overwrite=context_feeds_overwrite if context_feeds_updates is not None else False,
        )
    merged.pop("user_id", None)
    mem = Memory(user_id=user_id, **merged)
    with _state_lock:
        MEMORY_STORE[user_id] = mem
        safe_save_memory(action="patch", user_id=user_id)
    return mem
