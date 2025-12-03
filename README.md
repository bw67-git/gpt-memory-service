# gpt-memory-service

A backend service that provides persistent memory storage for the **APM Focus Co-Pilot** (CustomGPT). The service exposes a FastAPI-based REST API that supports reading, writing, and updating structured memory objects.

This repository contains the **application code only**. All runtime memory data remains local and is excluded from version control.

---

## Overview

The APM Focus Co-Pilot requires a persistent memory backend to store:

* Working memory
* Long‑term memory
* Session snapshots
* Profile information

This service provides that backend. It is intentionally minimal, reliable, and easy to run locally.

---

## System Architecture

This project uses the classic **three‑tier architecture**:

### **1. Presentation Layer — APM Focus Co-Pilot (CustomGPT)**

* Runs on OpenAI’s platform
* Sends API requests to this backend
* Loads memory at session start and updates it throughout usage

### **2. Application Layer — FastAPI (`src/gpt_memory_service/app.py`)**

Handles all logic:

* Request validation (Pydantic)
* Reading/writing memory
* Patch merging
* Backup generation
* Audit logging
* Automatic recovery

### **3. Data Layer — JSON Files (local)**

Not committed to GitHub:

* `memory.json` — main datastore
* `memory_backup_<timestamp>.json` — rolling backups
* `memory_audit.log` — append‑only diff log

---

## Repository Structure

```
gpt-memory-service/
├── main.py                  # Production entrypoint (uvicorn without reload)
├── src/
│   └── gpt_memory_service/
│       ├── __init__.py      # Exports __version__
│       ├── app.py           # FastAPI app definition and routes
│       └── version.py       # Single source of truth for the service version
├── requirements.txt         # Python dependencies
├── CHANGELOG.md             # Release history and version bump guidance
└── .gitignore               # Ensures runtime data is excluded
```

Runtime artifacts remain ignored:

* `memory.json`
* `memory_backup*.json`
* `memory_audit.log`
* `venv/`, `.venv/`, `__pycache__/`

---

## Running the Service Locally

> The project follows a ``src`` layout. If you are not installing the package, set ``PYTHONPATH=src`` when running commands from the repository root.

### 1. Create a virtual environment

```
python3 -m venv venv
source venv/bin/activate
```

### 2. Install dependencies

```
pip install -r requirements.txt
```

### 3a. Development server (auto-reload)

```
PYTHONPATH=src uvicorn gpt_memory_service.app:app --reload --host 0.0.0.0 --port 8000
```

### 3b. Production-style entrypoint (no reload)

```
python main.py
```

Local API:

```
http://localhost:8000
```

Interactive docs:

```
http://localhost:8000/docs
```

---

## Versioning

* The service uses semantic versioning. The version string lives in `src/gpt_memory_service/version.py` and is re-exported via the package `__init__`.
* The FastAPI application exposes `/version`, and the root entrypoint prints the version on startup.
* Bump versions using `MAJOR.MINOR.PATCH` only in `version.py`, and record changes in `CHANGELOG.md`.

---

## Connecting With APM Focus Co-Pilot

The Co-Pilot uses this backend to:

* Load memory at session start
* Patch working memory
* Store long‑term memory
* Save session snapshots
* Maintain user profile state

The CustomGPT Action must point to a **publicly accessible URL** for this service.

---

## External Access

To make this service reachable from the OpenAI platform, expose it using any tunneling solution you prefer (e.g., ngrok). Any tooling choice is valid as long as it provides a stable HTTPS URL.

---

## Data Handling & Safety

This backend ensures:

* Strict validation on all memory updates
* Automatic backups for every write
* Human‑readable diff logs
* Recovery from bad writes or corruption
* Memory files are never tracked by Git

---

## Health Check

```
curl http://localhost:8000/health
```

Expected:

```
{"status": "ok"}
```

---

## Maintainer

**Blake (bw67-git)** — personal project for persistent, structured memory to support APM workflows.
