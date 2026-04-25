# Repository Guidelines

## Project Structure & Module Organization
Core application code is split by responsibility. `agents/` contains the pipeline stages (`collector`, `extractor`, `scorer`, `alerter`) plus RSS and Reddit collectors. `services/` holds reusable logic such as scraping, queue handling, classification, similarity, and alert formatting. `api/main.py` exposes the FastAPI surface. `db/` contains `schema.sql`, the SQLite wrapper, and local database artifacts. Configuration lives in `config/*.yaml`. Tests are in `tests/`. Operational notes and phase plans live in `docs/` and `_docs/`.

## Build, Test, and Development Commands
Use the existing `Makefile` where possible:

- `make install` creates `.venv` and installs `requirements.txt`.
- `make redis` starts the Redis dependency with Docker Compose.
- `make api` runs `uvicorn api.main:app --reload`.
- `make collect`, `make extract`, `make score`, `make alert` run individual pipeline stages.
- `make pipeline` runs `./fraud-mvp-daily-pipeline.sh` for the end-to-end daily flow.
- `make test` runs the pytest suite under `tests/`.

Direct equivalents such as `python3 -m pytest tests` and `python3 -m agents.collector` are also used in this repo.

## Coding Style & Naming Conventions
Follow existing Python style: 4-space indentation, `snake_case` for functions and modules, `PascalCase` for classes, and type hints where practical. Keep module-level docstrings and concise section comments when a file has multiple responsibilities. Prefer small service classes over large scripts when adding reusable logic. YAML config keys should remain descriptive and lowercase with underscores.

## Testing Guidelines
Tests use `pytest`, with some broader verification in `tests/verify_all.py`. Name new tests `test_*.py` and keep test functions behavior-focused, for example `test_upsert_source_updates_existing_row`. Run `make test` before opening a PR. If you change DB logic, scrapers, or scoring rules, add or update regression coverage in `tests/`.

## Commit & Pull Request Guidelines
Recent commits use milestone-style subjects such as `Week 4: alerter agent, FastAPI, full pipeline complete`. Keep commit titles short, descriptive, and scoped to one change set. PRs should include: purpose, affected modules, test evidence, config or migration notes, and screenshots or sample payloads when API or alert output changes.

## Security & Configuration Tips
Do not commit populated `.env`, session files, or generated databases. Use `.env.example` as the template. Treat live Telegram scraping and API tokens as production-sensitive; default to demo mode unless credentials are intentionally configured.
