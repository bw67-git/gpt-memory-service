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

from .models import Event, MemoryCreate, MemoryPatch, UserMemory
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
MAX_EVENTS = 500  # guardrail to prevent unbounded growth from transcript ingestion


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


def normalize_events(raw_events: Optional[List[Any]]) -> List[Dict[str, Any]]:
    """Ensure event entries align with the Event model."""

    normalized: List[Dict[str, Any]] = []
    now_iso = datetime.utcnow().isoformat()

    for event in raw_events or []:
        if isinstance(event, Event):
            event_dict = event.model_dump(exclude_none=True)
        elif isinstance(event, dict):
            event_dict = {k: v for k, v in event.items() if v is not None}
        else:
            raise HTTPException(status_code=400, detail="events entries must be objects")

        event_dict.setdefault("captured_at", now_iso)

        normalized.append(event_dict)

    return normalized[:MAX_EVENTS]


def _event_key(event: Dict[str, Any]) -> Tuple[str, str, str, str, str]:
    """Create a stable deduplication key; tolerant to missing identifiers."""

    event_id = str(event.get("id") or "")
    if event_id:
        return (event_id, "", "", "", "")

    return (
        "",
        str(event.get("captured_at") or ""),
        str(event.get("occurred_at") or ""),
        str(event.get("title") or ""),
        str(event.get("summary") or ""),
    )


def merge_events(
    existing: Optional[List[Any]],
    updates: Optional[List[Any]],
    overwrite: bool = False,
) -> List[Dict[str, Any]]:
    """Merge events safely while deduplicating by id or timestamp/title/summary."""

    existing_normalized = normalize_events(existing)
    updates_normalized = normalize_events(updates)

    if overwrite:
        merged = updates_normalized
    else:
        seen = {_event_key(event) for event in existing_normalized}
        merged = list(existing_normalized)
        for event in updates_normalized:
            key = _event_key(event)
            if key not in seen:
                merged.append(event)
                seen.add(key)

    # keep newest entries last and trimmed
    if len(merged) > MAX_EVENTS:
        merged = merged[-MAX_EVENTS:]

    return merged


MEMORY_STORE: Dict[str, UserMemory] = {
    uid: UserMemory(**data) for uid, data in _raw_state.items()
}
_state_lock = threading.Lock()
_last_saved_state = json.dumps(
    {uid: mem.model_dump(mode="json") for uid, mem in MEMORY_STORE.items()}, sort_keys=True
)


# ---------- Deep merge utility ----------
def deep_merge(existing: Dict[str, Any], updates: Dict[str, Any]) -> Dict[str, Any]:
    merged = copy.deepcopy(existing)
    for key, value in updates.items():
        if value is None:
            continue
        existing_value = merged.get(key)
        if isinstance(value, dict) and isinstance(existing_value, dict):
            merged[key] = deep_merge(existing_value, value)
        elif isinstance(value, list):
            merged[key] = copy.deepcopy(value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


# ---------- Validation + Safe Save ----------
def validate_memory_structure(data: Dict[str, Any]) -> bool:
    try:
        for uid, record in data.items():
            UserMemory(**record)
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
    snapshot_after = {uid: m.model_dump(mode="json") for uid, m in MEMORY_STORE.items()}

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
                current_state = json.dumps(
                    {uid: m.model_dump(mode="json") for uid, m in MEMORY_STORE.items()},
                    sort_keys=True,
                )
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
@app.get("/memory/{user_id}", summary="Get Memory", response_model=UserMemory)
def get_memory(user_id: str) -> UserMemory:
    mem = MEMORY_STORE.get(user_id)
    if mem is None:
        raise HTTPException(status_code=404, detail="Memory not found")
    return mem


@app.post("/memory/{user_id}", summary="Create Memory", response_model=UserMemory)
def create_memory(user_id: str, payload: MemoryCreate, overwrite: bool = False) -> UserMemory:
    """Create memory; prevent overwrite unless explicitly allowed."""
    if user_id in MEMORY_STORE and not overwrite:
        raise HTTPException(
            status_code=409,
            detail=f"Memory for '{user_id}' already exists. Use PATCH or set ?overwrite=true."
        )
    payload_data = payload.model_dump(exclude_none=True)
    payload_events = payload_data.pop("events", [])
    events = merge_events([], payload_events, overwrite=True)
    payload_data["events"] = events

    with _state_lock:
        MEMORY_STORE[user_id] = UserMemory(user_id=user_id, **payload_data)
        safe_save_memory(action="create", user_id=user_id)
    return MEMORY_STORE[user_id]


@app.patch("/memory/{user_id}", summary="Patch Memory", response_model=UserMemory)
def patch_memory(user_id: str, payload: MemoryPatch) -> UserMemory:
    existing = MEMORY_STORE.get(user_id)
    base_data: Dict[str, Any] = existing.model_dump() if existing else {}
    updates = payload.model_dump(exclude_unset=True)
    events_updates = updates.pop("events", None)
    events_overwrite = updates.pop("events_overwrite", False)

    merged = deep_merge(base_data, updates)
    existing_events = base_data.get("events") or []

    if events_updates is not None or existing_events:
        events_base = [] if events_overwrite else existing_events
        events_merged = merge_events(events_base, events_updates or [], overwrite=events_overwrite)
        merged["events"] = events_merged
    merged.pop("user_id", None)
    mem = UserMemory(user_id=user_id, **merged)
    with _state_lock:
        MEMORY_STORE[user_id] = mem
        safe_save_memory(action="patch", user_id=user_id)
    return mem
