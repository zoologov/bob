# ACTIVE — BOB-082 Dev-канал в личке (лайв-стрим + сквозная память)

> **Focus:** dev-режим в личке с живым стримом Claude Code; Боб — один разум across личка+группа.

## Статус волн

| Волна | Беад | Роль | Статус |
|------|------|------|--------|
| 1 | bob-pdo.1 | dev — КАНАЛ+SCOPE (chat_type сигнал + scope по месту) | ⏳ ready |
| 2 | bob-pdo.2 | dev — AUTHZ owner-DM | ⛔ blocked(.1) |
| 3 | bob-pdo.3 | dev — ЛАЙВ-СТРИМ в личку + флаг | ✅ dev-done (in_progress, ждёт coordinator) |
| 4 | bob-pdo.4 | dev — КОНСЕНТ-РАСКРЫТИЕ | ✅ dev-done (in_progress, ждёт coordinator) |
| 5 | bob-pdo.5 | test — unit+BDD+mutation | ⛔ blocked(.4) |
| 6 | bob-pdo.6 | review — SECURITY+PRIVACY | ⛔ blocked(.5) |
| 7 | bob-pdo.7 | tech-writer — docs | ⛔ blocked(.6) |

## Критический путь
.1 → .2 → .3 → .4 → .5 → .6 → .7 (линейно; dev последовательно — общие касания gateway/handle/disclosure).

## Живой смоук (после мержа + активации флага)
`/code` из лички → живой стрим в личку; группа чистая (указатель); память сквозная (в личке про группу и
наоборот); S5 «расскажи ребятам про X» в группе → раскрывает; без спроса — молчит; S6 гость не получает
dev-канал. 🔴 Feasibility: бот пишет в DM (owner нажал Start).

## Прогресс
- 2026-08-01: PRD/RFC/CONTEXT/PLAN approved; беады созданы (parent bob-pdo); ветка features/BOB-082.
- 2026-08-01: ✅ ЗАВЕРШЁН. Все беады закрыты. PR #114 смержен (799a194). pytest 4669, mutation 100%
  эффект. (disclosure/stream_render/consent), security+privacy-review OK, beadloom ci PASS, mypy
  src+tests clean. Флаг coder.dev_dm=true (dev_dm_chat_id→owner 27468732); Боб перезапущен (pid 71264);
  _DmLiveStreamer ACTIVE (не None). Boot чист. 🔴 Осталось для полного E2E-смоука: owner нажимает Start
  на боте Боба (чтобы бот мог писать в личку) + `/code` из лички → живой стрим. S1–S6 доказаны BDD.
  Следующий срез: T3.C⁺ двусторонний интерактив (stdin-мост).
- 2026-08-01: .4 dev-done — owner-consent disclosure override. Чистое ядро may_surface/filter_surfaceable
  +owner_consented (дефолт byte-identical); Tier-0 семант. консент-детектор (social/disclosure_consent +
  adapter + TaskType DISCLOSURE_CONSENT local); DisclosureConsentGate (только OWNER+GROUP, best-effort→нет
  согласия); _recall_surfaceable→_surface_audience (в группе surface как GUEST, лифт по консенту; DM/off →
  byte-identical); wiring за coder.dev_dm (OFF→инертно). 24 теста, pytest 4641 green, ruff/mypy/lint --strict чисто.
  Доки (SPEC/README/architecture) → tech-writer .7. Консервативно: неуверен/сбой/off → НЕ раскрывать.
