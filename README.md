# gpt-memory-service

A backend service that provides persistent memory storage for the **APM Focus Co-Pilot** (CustomGPT). The service exposes a simple FastAPI-based REST API that supports reading, writing, and updating structured memory objects.

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

### **2. Application Layer — FastAPI (`main.py`)**

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
│
├── main.py                 # FastAPI backend
├── requirements.txt        # Python dependencies
├── .gitignore              # Ensures runtime data is excluded
│
├── memory.json             # (ignored) application memory
├── memory_backup*.json     # (ignored) backups
├── memory_audit.log        # (ignored) audit log
├── venv/                   # (ignored) virtual environment
└── __pycache__/            # (ignored) Python bytecode
```

---

## Running the Service Locally

### 1. Create a virtual environment

```
python3 -m venv venv
source venv/bin/activate
```

### 2. Install dependencies

```
pip install -r requirements.txt
```

### 3. Start the server

```
uvicorn main:app --host 0.0.0.0 --port 80
```

Local API:

```
http://localhost:80
```

Interactive docs:

```
http://localhost:80/docs
```

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

To make this service reachable from the OpenAI platform, expose it using any tunneling solution you prefer.

A common option is using a reverse tunnel such as ngrok. Any tooling choice is valid as long as it provides a stable HTTPS URL.

> Installation steps and tunnel configuration are intentionally **not** included in this README, as they depend on personal tooling preferences and are not part of the core application.

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
curl http://localhost:80/
```

Expected:

```
{"status": "ok"}
```

---

## Extensions

For deeper documentation, you may add a `/docs` directory containing:

* CustomGPT instructions
* Memory protocol specifications
* Architecture deep‑dives
* Exported OpenAPI schema

---

## Maintainer

**Blake (bw67-git)** — personal project for persistent, structured memory to support APM workflows.
