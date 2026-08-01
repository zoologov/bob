> **Status:** Approved
> **Type:** feature (Тир-3 T3.C, срез 1)
> **Created:** 2026-08-01
> **Issue:** BOB-082

# PLAN — BOB-082 (DAG + seam-точки)

## Seam-точки (авторитетно, из разведки)

- Сигнал канала: `_ChatLike` (`gateway.py:188-190`, только id), `MessageReceived` (`application/runtime/
  events.py:55-62`), вход `_to_message_received` (`gateway.py:606-621`, chat.id@614).
- Authz: `is_authorized` (`social/usecases/authorizer.py:55-67`), дроп `_passes_gate` (`gateway.py:530-553`),
  wiring `runtime/wiring/access.py:40-42`.
- Scope: `_turn_is_shared_scope` (`handle_message.py:2190-2201`), `_turn_visibility` (`:2095-2104`),
  `visibility_for_scope` (`social/disclosure.py:71-79`, pure).
- Стрим: `claude_runner.py:87-122` (сырые события), `narrate.py:129-137` (lossy, НЕ для лички),
  `coding_assistant.py:421-461` (кап) + порты `OwnerNotifier`:103-113 / `StatusPanel`:144-160,
  `indicator.py:57-161` (edit_message_text прецедент), `owner_notifier.py:47-58` (адаптер чата),
  `RichMarkdownSender.send` (`gateway.py:866-920`), wiring `coding.py:84-149` + `composition.py:504-515`.
- Disclosure: `may_surface`/`filter_surfaceable` (`disclosure.py:55-96`), вызыватель `_recall_surfaceable`
  (`handle_message.py:2106-2125`), `disclosure_guard.py:55-84` (guest-only). Консент — net-new. Образец
  Tier-0 намерения: `social/permission/intent.py`.
- Память: `episodic_log` без chat_id (`schema.sql:6-38`), recall `fts_recall.py:85-98`, персист
  `_persist` (`handle_message.py:2133-2174`). Config: `config/bob.yaml` telegram/coder, `runtime/config.py:185-235`.

## Беады

```
BOB-082 [feature] — dev-канал в личке: лайв-стрим Claude Code + сквозная память
├── .1 [dev] — КАНАЛ+SCOPE: сигнал chat_type/is_group (gateway→MessageReceived→handle) + scope по МЕСТУ
│              (_turn_is_shared_scope на is_group: личка→owner_private, группа→public, фикс owner-в-группе).
│              Чистое: chat_type→is_group + visibility_for_scope по месту. НЕ сломать surface owner'у/BOB-066/078.
├── .2 [dev] — AUTHZ owner-DM: спец-кейс is_authorized (chat_id==owner_id и user_id==owner_id → allow),
│              owner-only; opt telegram.owner_dm_chat_id (дефолт owner_id); wiring access.py. deps .1
├── .3 [dev] — ЛАЙВ-СТРИМ: render_stream_event (pure, сырые события) + DM-notifier/StatusPanel в личку
│              (progressive edit, без капа) + группа-указатель + флаг coder.dev_dm(+dev_dm_chat_id).
│              use-case не менять (порт transport-free), адаптер+wiring coding.py/composition.py. deps .2
├── .4 [dev] — КОНСЕНТ-РАСКРЫТИЕ: Tier-0 консент-детектор (owner разрешает вынести приватное в этот чат,
│              консервативно, только owner+группа) + per-turn override filter_surfaceable(..., owner_consented)
│              в _recall_surfaceable (recall-time, без мутации visibility). Дефолт S4 не раскрывать. deps .3
├── .5 [test] — unit (chat_type/scope-по-месту; render_stream_event; filter owner_consented; authz owner-DM)
│              + BDD (S1 стрим-в-DM/S2 группа-указатель/S3 сквозной recall/S4 приватность-дефолт/S5 консент-
│              раскрытие/S6 owner-only) + mutation ≥85% (disclosure+render ядра). deps .4
├── .6 [review] — 🔴 SECURITY+PRIVACY: сквозная память (нет сило); scope-по-месту не ломает группу/surface
│              owner; консент консервативен (S4 vs S5, ложных раскрытий нет); owner-only канал; firehose
│              только в личку; гейты/worktree BOB-039 целы; DDD. deps .5
└── .7 [tech-writer] — docs (conversation/social disclosure scope-по-месту; capabilities/coding dev-канал
                     стрим+флаг; memory сквозная; consent-override). deps .6
```

## Волны / критерии

Dev последовательно (.1→.4 — общие касания gateway/handle/disclosure/wiring; урок BOB-066). Test → review
→ tw → PR → self-merge → рестарт → живой прогон.

🔴 **Живой смоук (после активации флага):** `/code` из лички → живой стрим в личку; группа чистая (указатель);
память сквозная (спросить в личке про группу и наоборот); S5 «расскажи ребятам про X» в группе → раскрывает;
без спроса — молчит; S6 гость не получает dev-канал. 🔴 Feasibility: бот пишет в DM (owner нажал Start).
Ядра disclosure+render mutation ≥85%.

## Риски (из RFC)

- Scope-фикс (.1) — правка корректности, меняет поведение и при OFF → review контролирует; owner surface цел.
- Консент ложно → консервативный Tier-0 + BDD S4/S5 + живой смоук.
- DM недостижима → feasibility-смоук (.2/.3).
- Утечка firehose → строго DM chat_id; группа указатель.
- Память силосится → НЕ добавлять chat_id-фильтр; тест сквозного recall.
