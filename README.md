# Bob

Autonomous home agent inspired by "We Are Legion (We Are Bob)" by Dennis E. Taylor.

## Quick Start

```bash
uv sync --extra dev    # install dependencies
uv run pytest          # run tests
uv run ruff check src/ # lint
uv run mypy src/       # type check
```

## Project Structure

```
src/bob/          — main Python package (discover domains via `beadloom prime`)
tests/            — pytest tests
config/           — YAML configuration files
docs/             — project documentation
.claude/dev-docs/ — internal development docs (PRD, RFC, ROADMAP)
.beadloom/        — architecture graph and rules
```

## Development

- **Python 3.12+**, asyncio, FastAPI, SQLite
- **TDD** — write tests first
- **DDD + Clean Architecture** — domains discovered via Beadloom
- **Pre-commit hook** — ruff + mypy + pytest run before every commit
