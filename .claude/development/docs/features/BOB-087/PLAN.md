> **Status:** Approved
> **Type:** epic
> **Created:** 2026-08-02
> **Issue:** BOB-087

# PLAN — BOB-087 (срезы A–E)

## Срезы (каждый = свой parent-подэпик + dev→test→review→tw → PR/мерж/рестарт)
- **A GUPPI-канал** — стрим ботом GUPPI + флаг coder.stream_via_guppi; Боб-голос ботом Боба. (низкий риск)
- **B Боб-оператор + дистиллированная память** — оператор-голос + дистиллятор сессии→детальные эпизоды. (средний)
- **C Целостность памяти** — work-домен + провенанс + register-aware recall (OFF→байт-в-байт). (🔴 высокий)
- **D Интерактив срез 2** — resume/continue + permission bypass (флаг owner-only) + --add-dir (флаг). (🔴 security)
- **E Tier-0 Ollama-fallback** — локальный fallback в llm_router (#34). (инфра)

## Срез A — беады (стартуем сейчас)
```
A [dev] — стрим→GUPPI-бот: notifier поверх resolved_guppi_bot (composition.py:516/536/548 + wiring/coding.py);
          флаг coder.stream_via_guppi (default OFF→бот Боба как сейчас); Боб-голос/реакции остаются ботом Боба;
          narrate GUPPI-префикс упростить (атрибуция теперь настоящая). Feasibility DM/топик GUPPI отметить.
A [test] — unit (флаг ON→стрим через GUPPI-бот, OFF→бот Боба байт-в-байт; голос Боба всегда бот Боба) + BDD.
A [review] — канон (firehose=GUPPI, голос=Боб); OFF байт-в-байт; DM-феасибилити.
A [tw] — docs coding/GUPPI-канал.
```
(Беады B–E создаются при входе в срез — держим эпик управляемым, урок BOB-062 8 срезов.)

## Волны / критерии
Срез за срезом. 🔴 Каждый: живой смоук ЧЕЛОВЕЧНОСТИ + флаг OFF байт-в-байт. C/D — отдельный пристальный
тест (память не засоряет личное / актор не путается; bypass owner-only, main цел). Боб в личку отчёт на вехах.

## Риски (PRD/RFC)
Флуд памяти → дистилляция не firehose (B); засорение личного → register-recall + провенанс (C);
recall-яд → firehose у GUPPI + first-person эпизоды (A/B); ослабление защиты → флаги owner-only + main-PR (D).
