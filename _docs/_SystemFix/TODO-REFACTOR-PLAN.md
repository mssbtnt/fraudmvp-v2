# TODO Refactor Plan

## Objective

Refine the project structure so the codebase is easier to maintain, safer to extend, and clearer to operate without disrupting the current runtime model.

This plan is intentionally compatibility-first:
- preserve current pipeline behavior
- avoid schema-breaking changes unless explicitly isolated and tested
- avoid broad rewrites of working logic
- focus on structure, ownership, configuration clarity, and safer operational boundaries

## Current Assessment

The codebase is functional, but the structure has started to drift as features were added:

- the repo root contains product code, helper scripts, stateful artifacts, and one-off utilities
- runtime artifacts are mixed with source code
- `services/` is acting as a catch-all for unrelated concerns
- `agents/` mixes pipeline stages with source-specific collection logic
- config access and path assumptions are spread across the codebase
- operational scripts and support tooling are not clearly separated from application modules

This does not require a rewrite. It requires a staged structural cleanup.

## Refactor Goals

1. Keep runtime behavior stable while improving code organization.
2. Make module ownership and boundaries obvious.
3. Separate code from runtime state and generated artifacts.
4. Reduce path fragility and implicit assumptions.
5. Make future feature work safer by clarifying extension points.
6. Improve testability without introducing unnecessary abstractions.

## Non-Goals

- replacing SQLite with another database
- replacing Redis or changing queue semantics
- redesigning the pipeline algorithm
- rewriting FastAPI endpoints for new orchestration behavior
- converting the project into a complex framework-heavy architecture

## Recommended Target Structure

The exact naming can vary, but the codebase should converge toward a structure like this:

```text
fraud-mvp/
  api/
  config/
  db/
    schema.sql
    database.py
  pipeline/
    collector.py
    extractor.py
    scorer.py
    alerter.py
    collectors/
  services/
    infrastructure/
    intelligence/
    notifications/
    scrapers/
  scripts/
  runtime/
    db/
    sessions/
    logs/
    backups/
    exports/
  tests/
  _docs/
```

If a `pipeline/` rename is too disruptive, keep `agents/` and apply the same internal separation.

## Major Problems To Address

### 1. Root Directory Is Too Noisy

Current root-level files include:
- helper scripts
- Telegram session/login utilities
- session artifacts
- DB files and backups
- temporary analysis scripts

Impact:
- weak signal-to-noise ratio
- higher risk of accidental misuse
- harder onboarding and navigation

### 2. Runtime State Is Mixed With Code

Examples:
- SQLite DB files and backups in `db/`
- `.session` files in repo root
- generated JSON files near code

Impact:
- encourages accidental coupling between code and mutable state
- makes deployment and cleanup harder
- increases risk of committing sensitive or environment-specific artifacts

### 3. `services/` Has Become A Catch-All

Current `services/` mixes:
- queue infrastructure
- LLM/keyword logic
- alert formatting
- Telegram monitoring
- scrapers

Impact:
- unclear ownership
- weaker discoverability
- more cross-cutting dependencies over time

### 4. `agents/` Mixes Stage Workers And Source-Specific Logic

Current `agents/` includes both:
- core pipeline stages such as collect/extract/score/alert
- source-specific collection modules such as Reddit and RSS collectors

Impact:
- pipeline model is less clear
- stage logic and source adapters are not cleanly separated

### 5. Configuration And Paths Need Centralization

Several components assume file locations or load config directly from scattered paths.

Impact:
- fragile when moving files
- harder to support different environments
- harder to test with isolated fixtures

### 6. Operational Tooling Is Present But Not Organized

Scripts and operational helpers exist, but there is no single structured home for:
- auth/bootstrap helpers
- admin utilities
- one-off maintenance scripts
- migration/cleanup scripts

## Refactor Principles

1. Move files only when the resulting boundary is clearer.
2. Keep imports backward-compatible where possible during transition.
3. Centralize path/config logic before moving runtime files.
4. Refactor structure in phases; do not mix structural work with logic changes unless necessary.
5. Add tests before changing ownership of fragile modules.
6. Prefer shallow, obvious packages over deep abstraction trees.

## Phased Refactor Plan

## Phase A: Establish Safe Foundations

### Purpose

Create the structural and operational guardrails needed for later moves without changing behavior.

### Changes

1. Add a centralized settings/path module.
   Suggested responsibilities:
   - project root discovery
   - config paths
   - runtime directory paths
   - database path
   - logs path
   - sessions path
   - environment variable parsing

2. Standardize runtime directories.
   Create:
   - `runtime/db/`
   - `runtime/sessions/`
   - `runtime/logs/`
   - `runtime/backups/`
   - `runtime/exports/`

3. Add compatibility defaults.
   The settings layer should preserve current paths if new directories are not yet populated.

4. Update `.gitignore` if needed so runtime state is clearly excluded.

### Benefits

- reduces path fragility
- makes later file moves lower-risk
- improves environment portability

### Risks

- low
- mostly path-related regressions if path resolution is incomplete

### Required Validation

- API import smoke test
- pipeline script dry run
- stage execution tests
- DB path resolution test

## Phase B: Clean Up Root-Level Scripts And Artifacts

### Purpose

Move one-off scripts and helper utilities out of the project root.

### Changes

1. Create `scripts/` with subfolders if useful:
   - `scripts/auth/`
   - `scripts/analysis/`
   - `scripts/maintenance/`
   - `scripts/dev/`

2. Move helper utilities such as:
   - Telegram login/session helpers
   - one-off fetch/analyze scripts
   - group listing utilities

3. Leave thin compatibility wrappers in the old locations only if existing docs or operators still rely on them.

4. Move any durable procedure into `_docs/` or the runbook if it is operational rather than executable.

### Benefits

- cleaner repo root
- better discoverability
- clearer separation between application code and tooling

### Risks

- low to medium
- risk comes from stale docs or shell scripts referencing old paths

### Required Validation

- run moved scripts from their new locations
- confirm referenced session paths still resolve
- update docs and Makefile targets

## Phase C: Separate Runtime State From Code

### Purpose

Move mutable artifacts out of code directories.

### Changes

1. Move live SQLite DB and backups into `runtime/db/`.
2. Move Telegram session files into `runtime/sessions/`.
3. Move logs into `runtime/logs/`.
4. Move exports and generated JSON artifacts into `runtime/exports/`.

### Implementation Notes

- do not hardcode new paths across the codebase
- route all access through the centralized settings/path module
- provide migration logic or documented manual move steps

### Benefits

- cleaner code directories
- safer ops practices
- clearer distinction between immutable source and mutable state

### Risks

- medium
- runtime breakage can happen if auth/session/DB paths are moved without a compatibility layer

### Required Validation

- full pipeline execution against migrated runtime paths
- Telegram auth/session reuse verification
- DB startup and API query validation

## Phase D: Refine Application Package Boundaries

### Purpose

Make the code layout reflect the system architecture more clearly.

### Recommended Split

#### Option 1: Keep `agents/`

Retain `agents/` but separate by role:
- `agents/stages/`
- `agents/collectors/`

#### Option 2: Rename `agents/` To `pipeline/`

Use:
- `pipeline/stages/`
- `pipeline/collectors/`

This is clearer, but more disruptive.

### Recommended `services/` Split

Split `services/` into narrower packages such as:

- `services/infrastructure/`
  - queue handling
  - shared adapters
  - env/path helpers if not placed elsewhere

- `services/intelligence/`
  - keyword extraction
  - LLM enhancement
  - campaign type normalization
  - scoring support

- `services/notifications/`
  - alert formatting
  - delivery integrations

- `services/scrapers/`
  - Reddit
  - Telegram
  - web
  - OpenSanctions
  - SemakMule

### Benefits

- clearer ownership
- lower cognitive load
- better extensibility for future features

### Risks

- medium
- import path churn can cause avoidable breakage if moved too aggressively

### Required Validation

- test suite
- import smoke checks
- pipeline execution per stage
- API startup

## Phase E: Centralize Domain Contracts

### Purpose

Reduce logic drift by defining explicit internal contracts for the main entities.

### Changes

1. Define shared contracts or dataclasses for:
   - extracted entity payloads
   - queue messages
   - campaign scoring results
   - alert payloads

2. Consolidate campaign type normalization and category mapping into one authoritative location.
3. Ensure collectors, extractors, scorers, and alerting all use the same field names and category values.

### Benefits

- fewer silent mismatches
- safer future enhancements
- easier test design

### Risks

- low to medium
- mostly contract drift if partial adoption occurs

### Required Validation

- contract-focused tests
- regression tests across queue payload boundaries

## Phase F: Improve Testing Layout And Coverage Strategy

### Purpose

Move from phase-based regression tests toward feature-based test ownership.

### Changes

1. Reorganize tests into functional groups such as:
   - `tests/db/`
   - `tests/pipeline/`
   - `tests/services/`
   - `tests/api/`
   - `tests/integration/`

2. Keep existing phase regressions temporarily, then retire them after equivalent coverage exists elsewhere.
3. Add fixture support for:
   - temporary SQLite DBs
   - isolated Redis mocks/fakes
   - sample source messages
   - sample queue payloads

### Benefits

- easier long-term maintenance
- clearer test intent
- better confidence during refactors

### Risks

- low

### Required Validation

- full test suite
- coverage review for critical paths

## Phase G: Tighten Operational Surfaces

### Purpose

Make the developer and operator experience more predictable.

### Changes

1. Ensure `Makefile` and runbook reflect the real file layout.
2. Add explicit maintenance commands for:
   - DB backup
   - DB cleanup
   - pipeline stage runs
   - session/bootstrap tasks

3. Add health/admin scripts under `scripts/maintenance/`.
4. If desired, add a `bin/` entrypoint layer for stable operational commands.

### Benefits

- fewer ad hoc commands
- easier maintenance
- clearer supported workflows

### Risks

- low

## Priority Ranking

Recommended order:

1. Phase A: settings/path centralization
2. Phase B: root script cleanup
3. Phase C: runtime state separation
4. Phase D: package boundary refinement
5. Phase E: contract centralization
6. Phase F: testing structure cleanup
7. Phase G: operational polish

## Suggested Concrete Moves

These are good candidates for the first structural pass:

- move root utility scripts into `scripts/`
- move session files into `runtime/sessions/`
- move SQLite DB and backups into `runtime/db/`
- move generated JSON outputs into `runtime/exports/`
- add a shared settings/path module and update all filesystem references to use it

These are good candidates for the second structural pass:

- split `services/`
- separate stage workers from source collectors
- reorganize tests by responsibility

These should be deferred until the structure is already stable:

- renaming `agents/` to `pipeline/`
- any DB schema redesign
- orchestration redesign

## Backward-Compatibility Strategy

To minimize risk:

1. Introduce new paths and modules before removing old ones.
2. Keep compatibility wrappers for renamed scripts or modules during transition.
3. Update imports incrementally.
4. Move one concern at a time.
5. Validate after each phase rather than stacking large moves.

## Recommended Acceptance Criteria

The refactor should be considered successful only if all of the following remain true:

- pipeline stages still execute correctly
- API still starts and serves read endpoints
- Telegram session reuse still works
- DB path and backup behavior are explicit and predictable
- no new duplicate data is created
- tests pass
- operational docs match actual behavior

## Risks To Watch Closely

- hidden path assumptions in scripts
- hardcoded session file locations
- DB path assumptions in tests and shell scripts
- imports that rely on current package names
- stale docs after moving operator-facing commands

## Implementation Guidance

- do not combine structural refactors with business logic changes unless unavoidable
- keep each PR/change set narrow and reversible
- prefer compatibility aliases and wrappers over breaking moves
- verify runtime commands after every structural change
- create backups before moving live DB or session artifacts

## Recommended First Execution Batch

The safest high-value first batch is:

1. add a settings/path module
2. introduce `runtime/` directories
3. update code to resolve paths through the settings layer
4. move DB/session/log paths behind configuration
5. move root helper scripts into `scripts/`
6. update Makefile and runbook

This batch gives the highest structural improvement for the lowest runtime risk.

## Final Recommendation

The project does not need a rewrite. It needs a controlled structural cleanup.

The best strategy is:
- stabilize paths first
- separate runtime artifacts from source code
- then refine package ownership

That approach will improve maintainability and reduce operational risk without destabilizing the working pipeline.
