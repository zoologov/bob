# ACTIVE — BOB-071 (bob-4fu.1 dev)

## Статус: bob-4fu.1 ГОТОВ (dev-волна)

### Seam A — вокатив-с-точкой (`src/bob/conversation/addressivity.py`)
- Добавлен `_SENTENCE_DOT` + `_LEFT_ADDRESS_SEPARATOR` + чистый хелпер `_has_left_comma_context`.
- В `_is_vocative_at`: точка-справа ВПЛОТНУЮ = терминатор-обращения ТОЛЬКО при запятой-обращении
  слева (`lowered[:start].rstrip().endswith(',')`).
- «Привет, Боб.» / «Кстати, Боб.» / «,Боб.» → DIRECTED_TO_BOB; «Это Боб.» / «Меня зовут Боб.» /
  «Мой друг Боб.» / «Боб.» → AMBIENT. Матрица BOB-069 цела.

### Seam B — персист рефлексивного non-reply (`src/bob/conversation/usecases/turn_gate.py`)
- `_advance_silent(event, soul, signals)` теперь `_persist(event, _SILENT_MARKER, soul)` перед advance.
- `_react_turn` теперь `_persist(event, _reaction_marker(emoji), soul)` перед advance.
- Read-failure ветка `_reflective_gate` теперь идёт через `_advance_silent` (тоже персистит).
- Симметрия с judge-`_act_non_reply`. БЕЗ owner-activity (периферия ≠ owner). Reply-путь не
  персистит в гейте (нет двойного персиста).

### Гейты
- pytest: 4073 passed · ruff clean · mypy --strict (src+tests) clean · lint --strict 0 violations.
- mutation (ядро адресности): 94.1% (89.8% строго); новый dot-guard 100% killed. 7 survivors —
  ПРЕДСУЩЕСТВУЮЩИЕ (`_decide_ambient`/`others_present`/`decide_response`/find-step +1→+2), вне scope.

### Осталось (DAG)
- .2 test — матрица точки + BDD + mutation. .3 review. .4 tech-writer (docs: conversation README
  addressivity точка + turn_gate персист — sync-check `hash_changed` на этих двух файлах ждёт .4).
