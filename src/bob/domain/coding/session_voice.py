# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=coding-domain

"""session_voice — голос Боба на гейтах coding-сессии (BOB-041 .3).

Канон Бобиверса: **Боб — личность**, он дирижирует сессией от первого лица; **GUPPI —
сухой детерминированный исполнитель** («руки» без личности), которым Боб правит. Эти
билдеры — ЧИСТЫЕ детерминированные ШАБЛОНЫ (никакого LLM-вызова на сообщение:
латентность/стоимость): ключевые реплики сессии (берусь / план готов / готово-PR /
провал / нет-правок / остановил) — в персоне Боба, с GUPPI как исполнителем, на
которого Боб ссылается. Формулировки персона-окрашенные, но сдержанные — гэги по
чуть-чуть, без перебора.

Это голос (как Боб ЗВУЧИТ), а не машинерия безопасности: гейты/поток/изоляция
(BOB-039/040/.2) живут в use-case :mod:`~bob.application.usecases.coding_assistant`
и не меняются — здесь только текст owner-facing сообщений. Все строки render-safe
(markdown .1-пути не ломается): встроенный план уже очищен апстримом.
"""

from __future__ import annotations

__all__ = [
    "accepted",
    "busy",
    "cannot_approve",
    "failed",
    "no_changes",
    "no_session",
    "panel_executing",
    "panel_failed",
    "panel_plan_ready",
    "panel_planning",
    "panel_pr",
    "panel_stopped",
    "plan",
    "pr",
    "status_idle",
    "status_line",
    "stopped",
]

# --- Голос Боба (русский — язык проекта; Cyrillic look-alikes интенциональны) ---

# Берусь: Боб от первого лица принимает задачу и тут же направляет GUPPI.
_ACCEPTED = "Окей, берусь. Сейчас прикину план — GUPPI, погнали."

# План готов: Боб представляет план (детали набросал GUPPI) и зовёт к апруву. Хинт
# покрывает обе поверхности апрува — естественный язык в топике Боба и явную команду.
_PLAN_INTRO = "Прикинул, вот что планирую — GUPPI накидал детали. Глянь:"
_PLAN_HINT = (
    'Если ок — скажи «давай» (или /code approve). Передумал — «стоп» (/code stop).'
)
_NO_PLAN = "GUPPI плана не вернул — пустой прогон. Попробуем ещё раз?"

# Готово-PR: Боб докладывает результат, GUPPI всё исполнил; напоминание про main.
_PR = (
    "Готово — GUPPI всё сделал. Вот PR, глянь: {url}. "
    "Мержить — твоё дело, в main я не лезу."
)

# Честные реплики провала/нет-правок/стопа — Боб от первого лица, GUPPI прибрал.
_NO_CHANGES = (
    "Глянул — GUPPI правок не внёс, коммитить нечего. "
    "PR не открываю, рабочую копию убрал."
)
_FAILED = "Сорвалось: {detail}. GUPPI прибрал рабочую копию."
_STOPPED = "Окей, остановил. GUPPI свернулся, рабочую копию убрал."

# Операционные отказы/статус — короткие реплики Боба (не на «горячем» пути канона).
_BUSY = "Я уже в работе над сессией — сначала закроем её («стоп» / /code stop)."
_CANNOT_APPROVE = (
    "Сейчас апрувить нечего — нет плана, ждущего добра "
    "(поставь задачу, я набросаю план)."
)
_NO_SESSION = "Активной сессии нет — я сейчас ничем не занят."
_STATUS_IDLE = "Активной сессии нет — я сейчас ничем не занят."
_STATUS_LINE = "Сессия «{task}» — состояние {state} (ветка {branch})."

# --- Индикатор работы: одна короткая строка editable-панели по фазам (BOB-046 .2) ---
# Не нарратив и не гейт — просто видимый owner маркер «процесс идёт», который use-case
# редактирует на месте (одно сообщение, не спам): план → выполняю → PR / провал / стоп.
_PANEL_PLANNING = "⏳ Прикидываю план…"
_PANEL_PLAN_READY = "📝 План готов — жду добро."
_PANEL_EXECUTING = "⚙️ GUPPI выполняет…"
_PANEL_PR = "✅ PR открыт."
_PANEL_FAILED = "⚠️ Не получилось."
_PANEL_STOPPED = "⏹️ Остановил."


def accepted() -> str:
    """Реплика «берусь»: Боб принимает задачу и направляет GUPPI (старт сессии).

    Короткая реплика от первого лица, которую use-case шлёт owner, как только
    NL-задача принята — до построения плана. Чистая, без аргументов.
    """
    return _ACCEPTED


def plan(plan_text: str) -> str:
    """Реплика «план готов»: интро Боба + уже очищенный план + хинт апрува.

    ``plan_text`` — авторитетный, дедуплицированный и очищенный план (.1); он
    встраивается ДОСЛОВНО (markdown .1-путь его отрендерит). Пустой план →
    честная заметка про пустой прогон вместо тела.
    """
    body = plan_text if plan_text else _NO_PLAN
    return f"{_PLAN_INTRO}\n\n{body}\n\n{_PLAN_HINT}"


def pr(url: str) -> str:
    """Реплика «готово-PR»: Боб докладывает результат + ссылку, GUPPI всё исполнил."""
    return _PR.format(url=url)


def no_changes() -> str:
    """Реплика «нет правок»: GUPPI ничего не изменил — честно, PR не открываем."""
    return _NO_CHANGES


def failed(detail: str) -> str:
    """Реплика «провал»: честная строка с ``detail``; GUPPI прибрал рабочую копию."""
    return _FAILED.format(detail=detail)


def stopped() -> str:
    """Реплика «остановил»: Боб погасил сессию, GUPPI свернулся и убрал копию."""
    return _STOPPED


def busy() -> str:
    """Отказ: уже идёт сессия — сначала её завершить."""
    return _BUSY


def cannot_approve() -> str:
    """Отказ: апрувить нечего — нет плана, ждущего добра."""
    return _CANNOT_APPROVE


def no_session() -> str:
    """Отказ/инфо: активной сессии нет."""
    return _NO_SESSION


def status_idle() -> str:
    """Статус: активной сессии нет."""
    return _STATUS_IDLE


def status_line(*, task: str, state: str, branch: str) -> str:
    """Статус идущей сессии: задача, состояние и ветка одной строкой."""
    return _STATUS_LINE.format(task=task, state=state, branch=branch)


def panel_planning() -> str:
    """Фаза панели «прикидываю план» — стартовая строка индикатора работы."""
    return _PANEL_PLANNING


def panel_plan_ready() -> str:
    """Фаза панели «план готов» — план собран, ждём добро owner."""
    return _PANEL_PLAN_READY


def panel_executing() -> str:
    """Фаза панели «выполняю» — GUPPI вносит правки по одобренному плану."""
    return _PANEL_EXECUTING


def panel_pr() -> str:
    """Финал панели «PR открыт» — успешное завершение сессии."""
    return _PANEL_PR


def panel_failed() -> str:
    """Финал панели «не получилось» — провал/нет правок."""
    return _PANEL_FAILED


def panel_stopped() -> str:
    """Финал панели «остановил» — owner погасил сессию kill-switch'ем."""
    return _PANEL_STOPPED
