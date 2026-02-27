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

## License

Bob uses a mixed licensing model to keep the code open to read and
hack on, while protecting the project from commercial exploitation
and low-effort rebranding.

| Component | License |
|---|---|
| Core (`src/bob/`, except `src/bob/skills/`) | [Business Source License 1.1](./LICENSE) |
| Skills & plugins (`src/bob/skills/`) | [Apache License 2.0](./LICENSE-APACHE.md) |
| Soul & assets (`bob-soul/`, `assets/`) | [CC BY-NC-SA 4.0](./LICENSE-CC-BY-NC-SA.md) |

**Personal non-commercial use** on your own hardware is permitted
under the Business Source License 1.1.

**Commercial use, SaaS, paid courses, consulting, or rebranding Bob as
your own product** requires a separate written agreement with the author.

On 2030-03-01 the core code transitions to Apache License 2.0.

"Bob" is inspired by the character Bob Johansson from
*We Are Legion (We Are Bob)* by Dennis E. Taylor. This project is not
affiliated with or endorsed by Dennis E. Taylor or Audible Originals.
