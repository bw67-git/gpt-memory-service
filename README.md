# gpt-memory-service v2.0.0

A backend service that provides persistent memory storage for the **APM Focus Co-Pilot** (CustomGPT). The service exposes a FastAPI-based REST API that supports reading, writing, and updating a structured `UserMemory` object.

This repository contains the **application code only**. All runtime memory data remains local and is excluded from version control.


---

## Overview

The APM Focus Co-Pilot requires a persistent memory backend to store:

- Profile information and preferences
- Working memory (focus thread, priorities, tasks, decisions, timeblocks)
- Long-term knowledge (projects, stakeholders, systems)
- A unified event timeline (meetings, snapshots, notes)

This service provides that backend. It is intentionally minimal, reliable, and easy to run locally.

---

## System Architecture

This project uses a simple three‑tier architecture:

### 1. Presentation Layer — APM Focus Co-Pilot (CustomGPT)

- Runs on OpenAI’s platform
- Calls this backend via HTTPS
- Loads `UserMemory` at session start and updates it over time

### 2. Application Layer — FastAPI (`src/gpt_memory_service/app.py`)

Responsible for:

- Request validation (Pydantic v2)
- Reading / writing memory
- Patch merging and event deduplication
- Backup generation
- Audit logging (JSON diff log)
- Automatic recovery from corrupted `memory.json`

### 3. Data Layer — JSON Files (local)

Not committed to GitHub:

- `memory.json` — main datastore (map of `user_id` → `UserMemory`)
- `memory_backup.json` — last-known-good backup
- `memory_audit.log` — append‑only diff log of changes

> The service will create `memory.json` automatically on first write if it doesn't already exist, alongside its backup and audit companions.

---

## Repository Structure

```bash
gpt-memory-service/
├── main.py                  # Production entrypoint (uvicorn without reload)
├── src/
│   └── gpt_memory_service/
│       ├── __init__.py      # Exports __version__
│       ├── app.py           # FastAPI app definition and routes
│       ├── models.py        # Pydantic models (UserMemory, Task, Event, etc.)
│       └── version.py       # Single source of truth for the service version
├── requirements.txt         # Python dependencies
├── CHANGELOG.md             # Release history and version bump guidance
└── .gitignore               # Ensures runtime data is excluded
```

Runtime artifacts remain ignored:

- `memory.json`
- `memory_backup*.json`
- `memory_audit.log`
- `venv/`, `.venv/`, `__pycache__/`

---

## Running the Service Locally

> The project follows a `src` layout. If you are not installing the package, set `PYTHONPATH=src` when running commands from the repository root.

### 1. Create a virtual environment

```bash
python3 -m venv venv
source venv/bin/activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3a. Development server (auto-reload)

```bash
PYTHONPATH=src uvicorn gpt_memory_service.app:app --reload --host 0.0.0.0 --port 8000
```

### 3b. Production-style entrypoint (no reload)

```bash
python main.py
```

Local API:

```text
http://localhost:8000
```

Interactive docs:

```text
http://localhost:8000/docs
```

---

## Versioning

- The service uses semantic versioning. The version string lives in `src/gpt_memory_service/version.py` and is re-exported via the package `__init__`.
- The FastAPI application exposes `/version`, and the root entrypoint prints the version on startup.
- Bump versions using `MAJOR.MINOR.PATCH` only in `version.py`, and record changes in `CHANGELOG.md`.
- This README describes the 2.x schema, which is **not** backward-compatible with 1.x `memory.json` files.

---

## Memory Model (2.x)

### UserMemory

`UserMemory` is the canonical root object for a single user:

- `user_id`: string — unique user identifier (key in `memory.json`).
- `profile`: `Profile` — name, role, preferences, weekly planning settings.
- `working_memory`: `WorkingMemory` — live focus, priorities, tasks, decisions, timeblocks.
- `long_term_knowledge`: `LongTermKnowledge` — relatively stable projects, stakeholders, systems.
- `events`: list[`Event`] — unified timeline of meetings, snapshots, and notes.

### Profile & WeeklyPlanningSettings

- `Profile`

  - `name`: optional string
  - `role`: optional string
  - `preferences`: free-form object for behavior knobs and prompt settings
  - `weekly_planning`: `WeeklyPlanningSettings`

- `WeeklyPlanningSettings`

  - `planning_day`: optional enum (`monday`…`sunday`)
  - `planning_time_local`: optional `HH:MM` (24h) local time
  - `calendar_link`: optional string
  - `timezone`: optional IANA timezone string

### WorkingMemory

- `current_focus_thread`: string — current focus identifier or narrative
- `active_priorities`: list[string]
- `tasks`: list[`Task`]
- `decisions`: list[`Decision`]
- `timeblocks`: list[`Timeblock`]

#### Task

- `id`: optional string
- `title`: string — short summary
- `status`: enum `TaskStatus` = `todo | in_progress | done | delegated`
- `due_at`: optional `datetime` (`format: date-time`)
- `notes`: list[string]

#### Decision

- `id`: optional string
- `summary`: string
- `rationale`: optional string
- `decision_type`: enum `DecisionType` = `strategic | tactical | process`
- `decided_at`: optional `datetime`

#### Timeblock

- `id`: optional string
- `label`: string
- `block_type`: enum `TimeblockType` = `focus | meeting | break | admin`
- `start_at`: `datetime`
- `end_at`: `datetime` (validated as strictly after `start_at`)

### LongTermKnowledge

- `projects`: list[`Project`]
- `stakeholders`: list[`Stakeholder`]
- `systems`: list[`System`]

#### Project

- `id`: optional string
- `name`: string
- `objectives`: list[string]
- `status`: optional enum `ProjectStatus` = `planning | in_progress | blocked | done`

#### Stakeholder

- `id`: optional string
- `name`: string
- `role`: optional string
- `contact`: optional string

#### System

- `id`: optional string
- `name`: string
- `notes`: list[string]

### Event (unified timeline)

`Event` is used for meetings, snapshots, and freeform notes:

- `id`: optional string — recommended:
  - `meeting-YYYYMMDD-slug` for meetings
  - `snapshot-YYYYMMDD-HHMMSS` for snapshots (24h time without separators)
- `type`: enum `EventType` = `meeting | snapshot | note`
- `title`: optional string
- `summary`: optional string
- `occurred_at`: optional `datetime`
- `captured_at`: optional `datetime`
- `decisions`: list[`Decision`]
- `tasks`: list[`Task`]
- `notes`: list[string]
- `metadata`: object (participants, tags, etc.)

When you POST or PATCH events without `captured_at`, the server will default it to the current UTC time.

---

## API Endpoints

All endpoints are rooted at your chosen base URL (e.g., `http://localhost:8000` or your ngrok HTTPS URL).

### `GET /memory/{user_id}` — Fetch memory

Returns the full `UserMemory` for the given `user_id`.

- **200** — `UserMemory` JSON
- **404** — if memory for that `user_id` does not exist

### `POST /memory/{user_id}` — Create memory

Create a new `UserMemory` record. By default, this will **not** overwrite an existing record.

- Request body: `MemoryCreate`
  - `profile`: optional `Profile`
  - `working_memory`: optional `WorkingMemory`
  - `long_term_knowledge`: optional `LongTermKnowledge`
  - `events`: list[`Event`]
- Query parameters:
  - `overwrite` (bool, default `false`) — if `true`, allow replacing existing memory for this user.

Responses:

- **200** — `UserMemory` after creation
- **409** — if memory already exists and `overwrite=false`

### `PATCH /memory/{user_id}` — Patch memory

Apply a partial update using `MemoryPatch`:

- `profile`: optional `ProfilePatch`
- `working_memory`: optional `WorkingMemoryPatch`
- `long_term_knowledge`: optional `LongTermKnowledgePatch`
- `events`: optional list[`Event`] — combined with `events_overwrite` flag
- `events_overwrite`: bool (default `false`)
  - `false` → merge events, deduplicating by `id` or timestamp/title/summary
  - `true` → replace the entire `events` array with the provided list

Responses:

- **200** — updated `UserMemory`
- **404** — if memory for that `user_id` does not exist

---

## Example Workflows

### 1. Creating a new user memory

```bash
curl -X POST "http://localhost:8000/memory/blake" \
  -H "Content-Type: application/json" \
  -d '{
    "profile": {
      "name": "Blake",
      "role": "Associate Product Manager",
      "preferences": {},
      "weekly_planning": {
        "planning_day": "monday",
        "planning_time_local": "09:00",
        "timezone": "America/Chicago"
      }
    },
    "working_memory": {
      "current_focus_thread": "Critical Mass MVP",
      "active_priorities": ["Ship PRD", "Align stakeholders"],
      "tasks": [],
      "decisions": [],
      "timeblocks": []
    },
    "long_term_knowledge": {
      "projects": [],
      "stakeholders": [],
      "systems": []
    },
    "events": []
  }'
```

### 2. Appending a meeting event

```bash
curl -X PATCH "http://localhost:8000/memory/blake" \
  -H "Content-Type: application/json" \
  -d '{
    "events": [
      {
        "id": "meeting-20251203-hex-platform-kickoff",
        "type": "meeting",
        "title": "HEX Platform Kickoff",
        "summary": "Framed HEX as unified geo standard and agreed on Q4–Q1 MVP.",
        "occurred_at": "2025-12-03T18:30:00Z",
        "decisions": [
          {"summary": "Adopt H3-based hex mapping as standard geo abstraction."}
        ],
        "tasks": [
          {"title": "Draft HEX MVP scope doc"}
        ],
        "notes": ["Target ~5% variance before go-live"]
      }
    ],
    "events_overwrite": false
  }'
```

---

## External Access

To make this service reachable from the OpenAI platform, expose it using any tunneling solution you prefer (e.g., ngrok). Any tooling choice is valid as long as it provides a stable HTTPS URL.

Configure your CustomGPT Action to point at the public HTTPS base URL and to use the OpenAPI contract served at `/openapi.json`.

---

## Data Handling & Safety

This backend ensures:

- Strict validation on all memory updates (Pydantic v2)
- Automatic backups for every write
- Human‑readable diff logs
- Recovery from bad writes or corruption
- Memory files are never tracked by Git

---

## Health Check

```bash
curl http://localhost:8000/health
```

Expected:

```json
{"status": "ok"}
```

---

## Maintainer

**Blake (bw67-git)** — personal project for persistent, structured memory to support APM workflows.

