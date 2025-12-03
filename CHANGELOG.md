# Changelog

All notable changes to this project will be documented in this file. The version number follows [Semantic Versioning](https://semver.org/) and should be updated in `src/gpt_memory_service/version.py` only.

## [0.1.0] - 2024-12-10
- Restructure project into a src-based FastAPI service layout.
- Add explicit dev (`uvicorn ... --reload`) and prod (`python main.py`) entrypoints.
- Introduce a single-source-of-truth version string exported via `/version`.

## How to release
1. Update `__version__` in `src/gpt_memory_service/version.py` using `MAJOR.MINOR.PATCH`.
2. Add a matching section above documenting the changes.
3. Commit and tag the release if desired.
