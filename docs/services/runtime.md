# runtime

> Composition root (`app.py`) — the only module allowed to wire all layers at once: loads layered config, builds infrastructure adapters, composes application policy + use-cases, subscribes handlers to the EventBus, registers ticks + Telegram polling, runs Genesis once, and starts the process.

## Source

`src/bob/app.py`

## Public API

| Symbol | Kind |
|--------|------|
| `Application` | class |
| `SystemClock` | class |
| `build_application` | function |
| `main` | function |

## Dependencies

- Depends on: bob-domain, bob-application, bob-infrastructure
- Used by: (none)

<!-- enrich with: beadloom docs polish -->
