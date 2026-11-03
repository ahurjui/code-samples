# Python — code samples

Excerpts from an automated trading platform I built (Python 3.12, FastAPI, SQLAlchemy 2,
MySQL, Docker). It runs dry-run only and has never traded real money. The module follows a
layered architecture: `domain/` (pure business rules, no I/O) → `services/` (use cases) →
repositories → API routers. The codebase is fully type-hinted, linted with a strict Ruff
rule set, and mutation-tested — the test suite is larger than the application code.

These are real files from the platform, unmodified. All credentials are environment-driven and
encrypted at rest; nothing sensitive is included. The files are excerpts and won't run
standalone — they're here to show design, defensive coding around order execution, and testing depth.

| File | What it shows |
|---|---|
| `app/domain/kelly.py` | Pure domain logic: Kelly-criterion position sizing, no I/O, fully deterministic |
| `app/domain/money.py` | Money value handling — exact arithmetic, no floats where it matters |
| `app/services/idempotency.py` | Idempotency-key generation so order submission is safe to retry |
| `app/services/execution_service.py` | Order execution use case: validation, risk gates, idempotent submission, audit logging |
| `tests/domain/test_kelly.py` | Focused unit tests for the sizing math |
| `tests/services/test_idempotency.py` | Unit tests for idempotency behavior |
| `tests/services/test_execution_service.py` | Deep service-level tests: failure paths, rejection handling, edge cases |
