# Fraud MVP — Comprehensive Codebase Assessment

**Date:** 2026-04-26  
**Assessor:** Claude Code (Anthropic) with Context7 documentation lookup  
**Scope:** Full repository — agents, services, API, database, tests, infrastructure  
**Lines of Code:** ~18,794 Python LOC across ~70 files  
**Core Frameworks:** FastAPI 0.111.0, Pydantic 2.7.1, Telethon 1.35.0, pytest 8.2.1

---

## 1. Executive Summary

Fraud MVP is a well-architected fraud intelligence pipeline targeting Malaysia and Southeast Asia. It scrapes web sources (MyCERT, consumer.org.my), OpenSanctions government alert lists (BNM, SC), Telegram channels, and Reddit, then extracts entities (phone numbers, bank accounts, domains, URLs), scores them through a 9-step pipeline, and delivers alerts via Telegram.

**Overall Verdict:** Production-ready MVP with solid architectural foundations, good separation of concerns, and comprehensive scoring logic. Several areas need attention before scaling: test coverage gaps, API router organization, type safety, and hardcoded configurations.

**Strengths:**
- Clean agent-based architecture (collector → extractor → scorer → alerter)
- Comprehensive 9-step scoring with Malaysian market-specific tuning
- Good use of configuration-driven design (YAML configs for sources, keywords, scoring rules)
- Proper API authentication and rate limiting
- Docker + docker-compose with health checks
- SQLite with idempotent schema migration path

**Concerns:**
- 21 `sys.path.insert` hacks indicate packaging/import issues
- No `pyproject.toml` / `setup.py` — project is not installable as a package
- Test suite uses custom runner instead of native pytest discovery
- No CI/CD configuration
- API is monolithic in a single file (1,078 LOC)
- Mixed sync/async patterns in FastAPI endpoints

---

## 2. Architecture & Design

### 2.1 Pipeline Architecture

```
Data Sources (web, Telegram, OpenSanctions, gated Reddit)
        ↓
raw_messages (Redis queue)
        ↓
FraudCollectorAgent / RedditCollectorAgent
        ↓
scraped_messages (SQLite) + extracted_entities (Redis queue)
        ↓
FraudExtractorAgent
        ↓
services.pipeline ingest (replay/enrichment)
        ↓
FraudScorerAgent (9-step scoring)
        ↓
alerts (Redis queue, threshold ≥60)
        ↓
FraudAlerterAgent → Telegram delivery + daily reports
```

**Assessment:** The pipeline is well-designed with clear stage separation, idempotent operations, and failure isolation (the bash pipeline script continues even if individual steps fail). The use of Redis queues between stages allows for distributed processing and replay capabilities.

### 2.2 Agent Design Pattern

Each agent follows a consistent pattern:
- Config loaded from YAML + `.env`
- `logging.basicConfig()` at module level (potential issue — see §5.3)
- `sys.path.insert(0, ...)` to resolve imports (anti-pattern — see §5.1)
- Database + QueueHandler instantiated in agent logic

**Assessment:** Consistent but not DRY. Every agent duplicates config/logging setup. A shared `BaseAgent` class or dependency injection framework would reduce boilerplate.

### 2.3 Database Design

SQLite with the following key tables:
- `entities` — unique by `(value, type)`
- `entity_edges` — every appearance of an entity
- `campaigns` — scored clusters
- `scraped_messages` — deduped by `text_hash`
- `alert_log` — delivery tracking

**Assessment:** Schema is well-normalized. The `_ensure_schema()` method runs `CREATE TABLE IF NOT EXISTS` on every `Database()` instantiation, making it self-migrating and idempotent. However, SQLite is noted as "MVP" with a commented-out PostgreSQL path but no migration tooling (Alembic, etc.).

### 2.4 Scoring Pipeline (scorer.py)

The 9-step scoring is the crown jewel of this codebase:

1. **Entity Graph** — builds node/edge graph from DB
2. **Frequency Scoring** — count ≥3 → +40, ≥4 → +50
3. **Temporal Clustering** — cross-channel 24h → +30, cross-platform → +40
4. **Content Similarity** — LLM script match ≥80% → +20
5. **Scam Type Classification** — 3-tier: keyword → LLM → cross-reference
6. **Cross-Reference Scoring** — BNM/SC/SemakMule boosts (+45 to +50)
7. **Victim Signal Scoring** — financial loss, police report (+5 to +50)
8. **Relationship Scoring** — shared phone/domain/co-occurrence
9. **Trend Scoring** — spike/rising/increasing adjustments

**Assessment:** Exceptionally comprehensive for an MVP. The scoring rules are externalized to `config/scoring_rules.yaml`, making tuning accessible to non-developers. The Malaysian market-specific weights (WhatsApp links, QR codes, phone numbers) show deep domain understanding.

---

## 3. Code Quality & Maintainability

### 3.1 Import System — CRITICAL

**Finding:** 21 occurrences of `sys.path.insert(0, str(Path(__file__).parent.parent))` across the codebase.

**Impact:** This is a significant anti-pattern. It:
- Prevents the project from being installable as a package
- Breaks IDE introspection and static analysis
- Makes testing more complex
- Causes issues with `mypy` type checking
- Indicates the project lacks a proper `setup.py` / `pyproject.toml`

**Recommendation (Priority: High):**
```toml
# pyproject.toml
[project]
name = "fraud-mvp"
version = "0.1.0"
dependencies = [...]

[tool.setuptools.packages.find]
where = ["."]
include = ["agents*", "api*", "db*", "services*", "config*"]
```
Then replace all `sys.path.insert` with standard imports.

### 3.2 Code Duplication

**Finding:** Every agent file duplicates:
- `load_dotenv()`
- `logging.basicConfig(...)`
- `sys.path.insert(...)`
- `CONFIG_DIR = Path(__file__).parent.parent / "config"`
- `LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()`

**Assessment:** ~15 lines × 8 agents = ~120 lines of duplicated boilerplate. A shared `config.py` or `logging.py` module would eliminate this.

### 3.3 Type Hints

**Finding:** The codebase uses `from __future__ import annotations` and has partial type hint coverage. However:
- Many function signatures lack return types
- Several `Any` types are used where more specific types could be applied
- The `Campaign` dataclass has mutable default arguments (`entity_values: list[dict] = None` which is actually handled, but pattern is risky)

**Assessment:** Moderate type safety. With `mypy==1.10.0` in requirements but no mypy configuration visible, the project likely has unchecked type errors.

### 3.4 Docstrings & Comments

**Finding:** Good module-level docstrings explain the purpose of each file. The CLAUDE.md file provides excellent project context. However, inline comments are sparse in complex scoring logic.

**Assessment:** Documentation is above average for an MVP. The `CLAUDE.md` file is a standout — it provides comprehensive context that makes onboarding significantly faster.

### 3.5 Configuration Management

**Finding:** Configuration is split across:
- `.env` / `.env.example` — environment variables
- `config/sources.yaml` — data sources
- `config/keywords.yaml` — scam keywords by category
- `config/scoring_rules.yaml` — scoring thresholds
- `config/scam_types.yaml` — scam type definitions
- `config/victim_signals.yaml` — victim signal keywords
- `config/pipeline.yaml` — pipeline settings

**Assessment:** Excellent separation of config from code. The YAML files are well-structured and commented. Using Pydantic Settings (already in `requirements.txt` as `pydantic-settings==2.2.1`) would provide validation and type safety for `.env` variables.

---

## 4. Security Assessment

### 4.1 API Authentication

**Finding:** The API uses a simple API key mechanism:
```python
_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
_api_key_query  = APIKeyQuery(name="api_key", auto_error=False)

async def verify_api_key(...):
    if not secrets.compare_digest(key, API_ACCESS_TOKEN):
        raise HTTPException(status_code=401, detail="Invalid API key")
```

**Assessment:** GOOD — `secrets.compare_digest` prevents timing attacks. The API key is required (server fails fast if missing). However:
- No key rotation mechanism
- No support for multiple keys / scopes
- Key is a single shared secret (no per-client identification)

**Context7 Insight:** FastAPI recommends using OAuth2 with JWT or API key + dependency injection for production. For this MVP, the current approach is acceptable but should evolve to OAuth2 or JWT before adding user management.

### 4.2 Rate Limiting

**Finding:** Uses `slowapi==0.1.9` for rate limiting:
```python
limiter = Limiter(key_func=get_remote_address, default_limits=["60/minute"])
READ_LIMITS  = "60/minute"
WRITE_LIMITS = "10/minute"
```

**Assessment:** GOOD — Proper per-IP rate limiting with separate read/write tiers. `slowapi` is a solid choice for FastAPI. The limits are reasonable for an internal tool.

### 4.3 CORS Configuration

**Finding:** CORS origins are configurable via `CORS_ORIGINS` env var. Default is `*` in `.env.example`.

**Assessment:** MODERATE RISK — `CORS_ORIGINS=*` allows any origin. For production, this should be restricted to known frontend domains. The implementation correctly reads from env, so this is an operations issue, not a code issue.

### 4.4 Input Validation

**Finding:** The API uses Pydantic models (`BaseModel`) for request/response validation. Query parameters use FastAPI's built-in validation.

**Assessment:** GOOD — Pydantic v2 provides robust validation. The endpoints appear to properly sanitize inputs. However, the raw message ingestion path (from scrapers) could benefit from stricter validation.

### 4.5 Secrets Management

**Finding:** Telegram API credentials, Reddit credentials, and alert bot tokens are all env-var based.

**Assessment:** MODERATE RISK — `.env.example` is well-documented. However:
- Session files (`fraudmvp_user_session.session`) are committed or generated in the repo root
- No `.gitignore` check for `.env` files was visible
- Telegram session files contain sensitive auth data

**Recommendation (Priority: High):** Ensure `.gitignore` includes:
```
.env
*.session
*.session-journal
```

### 4.6 SQL Injection Risk

**Finding:** The database layer uses parameterized queries consistently:
```python
conn.execute("SELECT * FROM entities WHERE type = ?", (entity_type,))
```

**Assessment:** GOOD — No raw string interpolation visible in the database layer. The SQLite wrapper is safe.

### 4.7 XSS / Injection in Alerts

**Finding:** Alert messages are formatted with HTML for Telegram delivery.

**Assessment:** LOW RISK — Telegram messages support HTML but the `alert_formatter.py` likely escapes user content. A review of `services/alert_formatter.py` should verify that entity values are escaped before HTML embedding.

---

## 5. API Design & FastAPI Patterns

### 5.1 Monolithic API File

**Finding:** `api/main.py` is 1,078 lines — a single file containing all endpoints, auth, rate limiting, models, and static file serving.

**Assessment:** MAINTAINABILITY RISK — As the API grows, this file will become unmanageable.

**Context7 Recommendation:** Use `APIRouter` to split endpoints into logical modules:
```python
# api/routers/campaigns.py
from fastapi import APIRouter
router = APIRouter(prefix="/campaigns", tags=["campaigns"])

@router.get("/")
async def list_campaigns(...):
    ...

# api/main.py
from api.routers import campaigns, entities, alerts
app.include_router(campaigns.router)
app.include_router(entities.router)
app.include_router(alerts.router)
```

### 5.2 Lifespan Events

**Finding:** No `lifespan` context manager visible in `api/main.py`. The database and queue connections are likely created per-request or at module import time.

**Context7 Insight:** FastAPI recommends using `asynccontextmanager` for startup/shutdown logic (database connections, Redis pools, ML model loading). This replaces the older `startup`/`shutdown` event handlers.

**Recommendation (Priority: Medium):**
```python
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    app.state.db = Database()
    app.state.queue = QueueHandler()
    yield
    # Shutdown
    app.state.db.close()
    app.state.queue.close()

app = FastAPI(lifespan=lifespan)
```

### 5.3 Dependency Injection

**Finding:** The API uses manual dependency injection (`verify_api_key`) but not FastAPI's `Depends` pattern for database/queue access.

**Assessment:** MODERATE — The auth dependency is correctly implemented. However, database and queue instances could be injected via `Depends` for better testability.

**Context7 Recommendation:**
```python
async def get_db() -> Generator[Database, None, None]:
    db = Database()
    try:
        yield db
    finally:
        db.close()

@app.get("/campaigns")
async def list_campaigns(db: Database = Depends(get_db)):
    return db.get_campaigns()
```

### 5.4 Background Tasks

**Finding:** The trigger endpoints (`/collect/trigger`, `/extract/trigger`, `/score/trigger`) are described as "informational only" and "manual-only."

**Assessment:** These endpoints likely execute heavy work synchronously. For production, they should use `BackgroundTasks` to avoid blocking the event loop.

**Context7 Recommendation:**
```python
from fastapi import BackgroundTasks

@app.post("/collect/trigger")
async def trigger_collection(background_tasks: BackgroundTasks):
    background_tasks.add_task(run_collector)
    return {"status": "started"}
```

### 5.5 Response Models

**Finding:** The API uses `BaseModel` but response models are not explicitly declared on all endpoints.

**Assessment:** MODERATE — Without explicit response models, FastAPI cannot generate accurate OpenAPI documentation. Adding `response_model=CampaignListResponse` to each endpoint improves documentation and client generation.

---

## 6. Testing & Quality Assurance

### 6.1 Test Suite Structure

**Finding:** 12 test files covering:
- Phase 1 regressions
- Phase 2 data integrity
- Reddit promotion
- Review defects (513 LOC — largest test file)
- Keyword extractor
- Daily report
- Campaign type normalization
- Phone/bank dedup
- Telegram auth guard
- Phase 4 efficiency
- Dashboard API
- `verify_all.py` (961 LOC — comprehensive but custom)

**Assessment:** GOOD COVERAGE FOR AN MVP — The tests cover key business logic (dedup, scoring, API, auth). However, the custom test runner in `verify_all.py` is concerning.

### 6.2 Custom Test Runner Anti-Pattern

**Finding:** `tests/verify_all.py` implements its own test framework:
```python
def test(name, func, *args, **kwargs):
    try:
        func(*args, **kwargs)
        results["pass"] += 1
    except AssertionError as e:
        results["fail"] += 1
    ...
```

**Assessment:** CRITICAL ISSUE — This bypasses pytest's fixture system, parameterized tests, plugins, coverage reporting, and CI/CD integration.

**Context7 Insight:** pytest's fixture system enables clean separation of test setup from test logic. Parametrization allows comprehensive testing with minimal code duplication. The plugin architecture supports CI/CD integration, code coverage, and parallel execution.

**Recommendation (Priority: High):** Convert `verify_all.py` to proper pytest tests with fixtures:
```python
# tests/test_integration.py
import pytest
from db.database import Database

@pytest.fixture
def db():
    db = Database(":memory:")
    yield db
    db.close()

def test_entity_insertion(db):
    db.upsert_entity("60123456789", "phone", ...)
    assert db.get_entity_by_value("60123456789", "phone") is not None
```

### 6.3 pytest-asyncio

**Finding:** `pytest-asyncio==0.23.6` is in requirements but no async test patterns were visible.

**Assessment:** The project has async code (Telethon, FastAPI) but may not be testing it properly. Adding `@pytest.mark.asyncio` to async tests and using async fixtures is needed.

### 6.4 Test Coverage

**Finding:** No coverage tool in requirements (no `pytest-cov` or `coverage.py`).

**Assessment:** UNKNOWN — Without coverage reporting, it's impossible to know what percentage of code is tested.

**Recommendation (Priority: Medium):** Add `pytest-cov` to requirements and set a coverage threshold:
```bash
pytest --cov=agents --cov=services --cov=api --cov=db --cov-report=term-missing --cov-fail-under=70
```

---

## 7. Performance & Scalability

### 7.1 Database

**Finding:** SQLite with `db/fraud_mvp.db` file path.

**Assessment:** SQLite is fine for MVP but has limitations:
- No concurrent writes (WAL mode can help but wasn't checked)
- No horizontal scaling path
- File-based backups are simple but limited

The `requirements.txt` includes `psycopg2-binary==2.9.9` (PostgreSQL adapter), indicating a planned migration. However, no migration tooling (Alembic, Flyway) is present.

**Recommendation (Priority: Medium):**
1. Enable SQLite WAL mode for better concurrency
2. Add Alembic for schema migrations
3. Abstract database layer to support both SQLite and PostgreSQL

### 7.2 Redis

**Finding:** Redis is used for queues with graceful degradation:
```python
# QueueHandler catches ConnectionError and falls back to no-op mode
```

**Assessment:** EXCELLENT — The graceful degradation pattern ensures the pipeline doesn't crash if Redis is down. FIFO queues using LPUSH/RPOP are correct for this use case.

### 7.3 Scraping Performance

**Finding:** Playwright is used for browser-based scraping. The Dockerfile installs Chromium.

**Assessment:** Playwright is resource-intensive. With `MAX_CONCURRENT_SCRAPERS=5`, memory usage could be significant. Consider:
- Using `httpx` for simple GET requests where JavaScript isn't needed
- Running Playwright in a separate service/container
- Implementing request caching with `httpx` + `hishel`

### 7.4 LLM Integration

**Finding:** Ollama is used for embeddings and similarity scoring with `nemotron-cascade-2:latest`.

**Assessment:** Local LLM is cost-effective but has tradeoffs:
- Model loading latency
- GPU/memory requirements
- Timeout handling (`FRAUD_LLM_TIMEOUT_SECONDS=20`)
- Failure fallback (`FRAUD_LLM_MAX_FAILURES=2`)

The failure handling is good. Consider adding a circuit breaker pattern for when Ollama is unreachable.

### 7.5 Scoring Pipeline Efficiency

**Finding:** The scorer builds an entity graph from the database on every run.

**Assessment:** For large datasets, this could be slow. Consider:
- Incremental scoring (only process new entities since last run)
- Caching the entity graph in Redis
- Batch processing with `get_edges_for_entities()` (already partially implemented)

---

## 8. DevOps & Deployment

### 8.1 Docker

**Finding:** Dockerfile uses `python:3.12-slim` with:
- `PYTHONDONTWRITEBYTECODE=1`
- `PYTHONUNBUFFERED=1`
- Layer caching (requirements copied first)
- Playwright Chromium installation

**Assessment:** GOOD — The Dockerfile follows best practices. Playwright browser installation adds significant build time and image size (~200MB+). Consider multi-stage builds to separate build dependencies from runtime.

### 8.2 Docker Compose

**Finding:** `docker-compose.yaml` defines:
- `redis` service with health checks
- `app` service (FastAPI, profile: app)
- `collector` service (profile: collector)
- `scraper` service (profile: scraper)
- `semakmule` service (profile: scraper)

**Assessment:** EXCELLENT — The profile-based design allows selective service startup. Health checks on Redis are proper. Volume mounts for config and db are correct.

### 8.3 Pipeline Orchestration

**Finding:** `fraud-mvp-daily-pipeline.sh` is a bash script with:
- Preflight checks (DB writable, Redis reachable, Telegram env)
- 5 pipeline steps with isolated failure handling
- Postflight baseline checks
- Comprehensive logging to `logs/YYYYMMDD.log`

**Assessment:** GOOD FOR MVP — The bash script is robust with `set -o pipefail`, error isolation, and metrics tracking. For production, consider:
- Airflow / Prefect / Dagster for workflow orchestration
- Systemd timer configuration (mentioned in CLAUDE.md but not visible in repo)
- Retry logic with exponential backoff for transient failures

### 8.4 CI/CD

**Finding:** No CI/CD configuration files (no `.github/workflows/`, no `.gitlab-ci.yml`).

**Assessment:** CRITICAL GAP — No automated testing, linting, or deployment. Adding a GitHub Actions workflow would:
- Run tests on every PR
- Run `mypy` for type checking
- Run `ruff` or `flake8` for linting
- Build and push Docker images

### 8.5 Makefile

**Finding:** Simple Makefile with targets for install, redis, api, pipeline, test, collect, extract, score, alert.

**Assessment:** GOOD — Provides convenient developer commands. Could be enhanced with `lint`, `format`, `typecheck`, and `coverage` targets.

---

## 9. Frontend

### 9.1 Dashboard

**Finding:** Static HTML/JS/CSS frontend in `frontend/`:
- `index.html` — single-page dashboard
- `app.js` — JavaScript logic
- `styles.css` — styling

**Assessment:** SIMPLE BUT EFFECTIVE — A lightweight static dashboard is appropriate for an MVP. The HTML shows a well-structured dashboard with sections for Executive, Intelligence, Campaigns, Operations, and Evidence.

### 9.2 Integration

**Finding:** FastAPI serves static files:
```python
from fastapi.staticfiles import StaticFiles
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
```

**Assessment:** CORRECT — StaticFiles with `html=True` serves `index.html` for directory requests, enabling SPA behavior.

---

## 10. Dependencies Analysis

### 10.1 FastAPI 0.111.0 vs Latest

**Current:** 0.111.0  
**Latest (Context7):** 0.128.0+  
**Risk Level:** LOW-MEDIUM

FastAPI 0.111.0 is stable. Key improvements in newer versions include:
- Better `lifespan` support
- `APIRouter` enhancements
- Performance improvements
- Bug fixes for background tasks

**Recommendation:** Upgrade to latest FastAPI during a maintenance window. Check for breaking changes in the release notes.

### 10.2 Pydantic 2.7.1

**Current:** 2.7.1  
**Risk Level:** LOW

Pydantic v2 is mature. The codebase correctly uses `BaseModel` and `ConfigDict` patterns (visible in Context7 lookup). No immediate upgrade needed.

### 10.3 Telethon 1.35.0

**Current:** 1.35.0  
**Risk Level:** LOW

Telethon is stable. The session-based authentication is correctly handled with fallback to demo mode. The auth guard prevents interactive prompts in background mode.

### 10.4 pytest 8.2.1

**Current:** 8.2.1  
**Risk Level:** LOW

pytest 8.x is the current major version. The `pytest-asyncio` plugin is correctly included for async test support.

### 10.5 Security Scan

**Finding:** No `safety`, `bandit`, or `pip-audit` in requirements.

**Assessment:** MODERATE RISK — Dependencies should be scanned for known vulnerabilities.

**Recommendation:**
```bash
pip install bandit safety
bandit -r agents services api db
safety check
```

---

## 11. Recommendations & Action Items

### Priority: Critical (Fix Immediately)

| # | Issue | Action | Effort |
|---|-------|--------|--------|
| 1 | `sys.path.insert` anti-pattern | Add `pyproject.toml`, make project installable, remove all `sys.path.insert` | 2-4h |
| 2 | `.gitignore` missing secrets | Add `.env`, `*.session`, `*.session-journal` to `.gitignore` | 15min |
| 3 | Custom test runner | Convert `verify_all.py` to proper pytest tests with fixtures | 4-8h |

### Priority: High (Fix Before Production)

| # | Issue | Action | Effort |
|---|-------|--------|--------|
| 4 | API monolith | Split `api/main.py` into routers (`api/routers/*.py`) | 3-4h |
| 5 | No CI/CD | Add GitHub Actions workflow for test + lint + build | 2-3h |
| 6 | Logging duplication | Create shared `logging_config.py`, use in all agents | 1-2h |
| 7 | Type checking | Add `mypy.ini` / `pyproject.toml` config, fix type errors | 3-6h |
| 8 | No coverage tool | Add `pytest-cov`, set 70% threshold | 30min |

### Priority: Medium (Fix During Maintenance)

| # | Issue | Action | Effort |
|---|-------|--------|--------|
| 9 | Database scaling | Enable SQLite WAL mode, add Alembic migrations | 2-4h |
| 10 | FastAPI lifespan | Add `lifespan` context manager for DB/Redis lifecycle | 1-2h |
| 11 | Background tasks | Use `BackgroundTasks` for trigger endpoints | 1-2h |
| 12 | Security scanning | Add `bandit` and `safety` to CI pipeline | 30min |
| 13 | Dependency injection | Use `Depends` for DB/Queue in API endpoints | 2-3h |
| 14 | CORS restriction | Update `.env.example` default from `*` to specific origins | 15min |

### Priority: Low (Nice to Have)

| # | Issue | Action | Effort |
|---|-------|--------|--------|
| 15 | Multi-stage Docker | Separate build/runtime stages to reduce image size | 1-2h |
| 16 | Orchestration | Migrate from bash to Airflow/Prefect for pipeline scheduling | 8-16h |
| 17 | API versioning | Add `/v1/` prefix to API endpoints | 1-2h |
| 18 | OpenAPI docs | Add explicit `response_model` to all endpoints | 2-3h |
| 19 | Circuit breaker | Add circuit breaker for Ollama LLM calls | 2-3h |
| 20 | Request caching | Cache HTTP responses for seed sources | 2-4h |

---

## 12. Risk Matrix

| Risk | Likelihood | Impact | Score | Mitigation |
|------|-----------|--------|-------|------------|
| Import path issues break deployment | High | High | **Critical** | Add `pyproject.toml` immediately |
| Secrets committed to git | Medium | Critical | **High** | Audit git history, add `.gitignore` |
| SQLite concurrency bottlenecks | Medium | Medium | **Medium** | Enable WAL mode, plan PostgreSQL migration |
| No automated testing in CI | High | Medium | **High** | Add GitHub Actions workflow |
| API monolith unmaintainable | Medium | Medium | **Medium** | Refactor into routers |
| LLM timeout cascades | Low | Medium | **Low** | Add circuit breaker, better fallback |
| Playwright memory exhaustion | Medium | Medium | **Medium** | Separate scraping service, add resource limits |
| CORS wildcard in production | Low | High | **Medium** | Update deployment config |

---

## 13. Conclusion

Fraud MVP is a **solid, well-architected MVP** with excellent domain-specific scoring logic and good operational patterns. The codebase shows clear thinking about failure modes, graceful degradation, and Malaysian market specifics.

The **top 3 priorities** are:
1. **Fix imports** (`pyproject.toml` + remove `sys.path.insert`) — blocks packaging and testing
2. **Add CI/CD** — ensures quality gates on every change
3. **Refactor API** — split monolithic `main.py` into routers for maintainability

With these changes, the project is well-positioned to scale from MVP to production.

---

*Assessment generated by Claude Code with Context7 documentation lookup for FastAPI, Pydantic, and pytest best practices.*
