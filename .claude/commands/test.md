# /test — Tester Role

> **When to invoke:** when writing tests, checking coverage
> **Focus:** pytest, test quality, coverage >= 80%, edge cases

---

## Test structure

Tests are in `tests/` (flat layout, no subdirectories). Discover test targets via Beadloom:

```bash
# 1. Understand the area under test
beadloom prime                   # project health: stale docs, lint violations
beadloom ctx <domain> --json     # source files, symbols, docs → derive test targets
beadloom why <ref-id>            # impact: what else might break?
beadloom search "<module>"       # find related code and existing tests

# 2. List existing tests
ls tests/test_*.py
```

Naming conventions (discover actual paths via `beadloom ctx`):
- Domain module: `src/<package>/<domain>/<module>.py` → `tests/test_<module>.py`
- CLI/API commands: `tests/test_cli_<command>.py` or `tests/test_api_<endpoint>.py`
- Integration: `tests/test_integration*.py`

---

## AAA Pattern (Arrange-Act-Assert)

```python
def test_goal_engine_creates_goal_with_priority(db: aiosqlite.Connection) -> None:
    # Arrange
    engine = GoalEngine(db)

    # Act
    goal = await engine.create(title="Learn user preferences", priority=1)

    # Assert
    assert goal.id is not None
    assert goal.title == "Learn user preferences"
    assert goal.status == "pending"
```

---

## Test types

### Unit tests
- Test a single function/class in isolation
- Mocks for all dependencies
- Fast (< 10ms)

### Integration tests
- Test interaction between components (CLI -> Core -> SQLite)
- Real SQLite database (in-memory or tmp_path)
- Medium speed (< 1s)

---

## Fixtures (conftest.py)

```python
import pytest
import aiosqlite
from pathlib import Path

# Discover actual DB helpers via: beadloom ctx <infrastructure-domain>

@pytest.fixture
async def db(tmp_path: Path) -> AsyncIterator[aiosqlite.Connection]:
    """Clean SQLite database for each test."""
    async with aiosqlite.connect(tmp_path / "test.db") as conn:
        # Apply schema — discover actual schema module via beadloom search "create_schema"
        yield conn

@pytest.fixture
def sample_config(tmp_path: Path) -> Path:
    """Minimal YAML config for tests."""
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "bob.yaml").write_text(
        "name: test-bob\n"
        "version: 0.1.0\n"
    )
    return tmp_path
```

---

## Edge Cases Checklist

### Input validation
- [ ] `None` / empty string
- [ ] Non-existent `ref_id`
- [ ] Duplicate `ref_id`
- [ ] Special characters and Unicode in `ref_id` / `summary`
- [ ] Very long `summary` (>10K characters)
- [ ] Empty YAML file
- [ ] Invalid YAML

### SQLite
- [ ] Empty database (no nodes)
- [ ] `ref_id` with SQL special characters (`'`, `"`, `;`)
- [ ] Broken foreign keys (orphaned edges)
- [ ] WAL mode with concurrent access

### File system
- [ ] Missing files (`docs/` does not exist)
- [ ] Empty Markdown files
- [ ] Markdown without H2 headings
- [ ] Files >1MB
- [ ] Symlinks

### Graph
- [ ] Circular dependencies
- [ ] Isolated nodes (no edges)
- [ ] depth=0
- [ ] max_chunks=0

---

## Commands

```bash
# Run all tests
uv run pytest

# With coverage (package name from pyproject.toml [tool.pytest.ini_options])
uv run pytest --cov --cov-report=term-missing

# Integration only
uv run pytest tests/test_integration*.py

# Single file
uv run pytest tests/test_<module>.py

# With verbose
uv run pytest -v

# Watch mode (pytest-watch)
uv run ptw
```

---

## Checking coverage

```bash
uv run pytest --cov --cov-report=term-missing --cov-fail-under=80
```

Minimum thresholds:
- Statements: 80%
- Branches: 80%

---

## Mocking

### pytest.mock / monkeypatch

```python
from unittest.mock import AsyncMock, patch

async def test_reflection_loop_evaluates_actions(db: aiosqlite.Connection) -> None:
    # Arrange — discover actual classes via beadloom ctx <domain>
    reflection = ReflectionLoop(db)
    mock_action = AsyncMock(return_value={"success": True})

    # Act
    result = await reflection.evaluate(mock_action)

    # Assert
    assert result.score > 0.0


async def test_api_health_endpoint(client: AsyncClient) -> None:
    """Integration test for FastAPI endpoint."""
    response = await client.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
```

### Factory for test data

```python
# tests/factories.py — factory helpers for test data
# Discover actual models via: beadloom search "dataclass"
import aiosqlite

async def insert_goal(
    conn: aiosqlite.Connection,
    goal_id: str = "test-goal",
    title: str = "Test goal",
    priority: int = 1,
    status: str = "pending",
) -> None:
    await conn.execute(
        "INSERT INTO goals (id, title, priority, status) VALUES (?, ?, ?, ?)",
        (goal_id, title, priority, status),
    )
```

---

## Testing result

```bash
bd comments add <bead-id> "$(cat <<'EOF'
TESTS:
- Unit: XX passed
- Integration: XX passed
- Coverage: XX%
- Edge cases: [list of checked cases]
- Known limitations: [if any]
EOF
)"
```

---

## Beadloom validation (after tests pass)

```bash
beadloom reindex                 # re-index if code changed
beadloom sync-check              # verify docs aren't stale after code changes
beadloom lint --strict           # architecture boundaries still hold
```

---

## Tester checklist

- [ ] `beadloom ctx <ref-id>` — understood the area under test
- [ ] `beadloom why <ref-id>` — checked impact on dependents
- [ ] Unit tests for all business logic
- [ ] Integration tests for CLI and indexer
- [ ] Edge cases covered (see checklist above)
- [ ] Coverage >= 80% (`--cov-fail-under=80`)
- [ ] Tests are independent (can be run in any order)
- [ ] Tests are fast (unit <10ms, integration <1s)
- [ ] Tests are readable (AAA pattern)
- [ ] Fixtures in `conftest.py`, using `tmp_path`
- [ ] No hardcoded paths (only `tmp_path` / `Path`)
- [ ] `beadloom sync-check` — no stale docs after code changes
- [ ] `beadloom lint --strict` — no architecture violations
