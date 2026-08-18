# ACTIVE: BOB-095

> **Обновлено:** 2026-08-18

## Сейчас
Спека утверждена. Строю `.github/workflows/ci.yml` (pull_request→main): uv sync --extra dev → ruff +
mypy + pytest -rs + beadloom ci на чистом индексе; §6 CLAUDE.md — честно «информативная, не required».

## Ловушки (уже известны)
- uv sync --extra dev (иначе нет ruff/mypy — Issues #57);
- pytest -rs (drift-gate на раннере = SKIP с причиной, не молчание);
- beadloom ci на ЧИСТОМ индексе (§0.3 п.1);
- НЕ называть проверку required (branch protection недоступна).
