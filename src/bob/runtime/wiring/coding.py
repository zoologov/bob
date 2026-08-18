# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""Composition-root coding wiring — the gated «Bob runs Claude Code» assistant + NL router.

Assembles the gated :class:`CodingAssistant` (only when ``coder.enabled``: shell-free infra
adapters over the durable session store, the owner gate + a BOB-bot owner-notifier, the
UNBYPASSABLE plan gate) and the natural-language :class:`CodingIntentRouter`. Off → both
``None`` (inert). Part of the ``bob.runtime`` composition root (BOB-062.7a).
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, cast

from bob.capabilities.introspection.privacy_guard import PrivacyGuard
from bob.coding.adapters import (
    ForkCompareLink,
    GhPullRequestOpener,
    GitClone,
    GitWorktree,
    SubprocessClaudeRunner,
)
from bob.coding.adapters.gh_pr import PullRequestError
from bob.coding.adapters.indicator import StatusPanel, TypingKeepalive
from bob.coding.adapters.live_stream import _DmLiveStreamer
from bob.coding.adapters.owner_notifier import _CodingOwnerNotifier
from bob.coding.adapters.session_store import SqliteCodingSessionStore
from bob.coding.pr_link import repo_slug
from bob.coding.usecases.classify_coding_intent import ClassifyCodingIntent
from bob.coding.usecases.coding_assistant import CodingAssistant, LiveRunStreamer
from bob.coding.usecases.coding_context import make_coding_context
from bob.coding.usecases.coding_intent_router import CodingIntentRouter
from bob.identity.adapters.spawn_isolation_files import SpawnIsolationFiles
from bob.interactive.adapters.runner import InteractiveClaudeRunner
from bob.interactive.usecases.intake import InteractiveIntakeRouter
from bob.interactive.usecases.recover_sessions import RecoverInteractiveSessions
from bob.interactive.usecases.session import InteractiveSessionManager
from bob.kernel.config_paths import under_root
from bob.runtime.config import (
    _CODING_TYPING_INTERVAL,
    _REPO_ROOT,
    _flag,
    _int,
    _section,
    _str,
    _str_list,
)
from bob.runtime.wiring.capabilities import _build_introspector

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from bob.application.router import LLMRouter
    from bob.coding.adapters.indicator import EditableStatusBot, TypingActionBot
    from bob.coding.usecases.coding_assistant import WorkJournalRecorder
    from bob.identity.spawn_isolation import SpawnIsolation
    from bob.infrastructure.persistence import SqliteConnection
    from bob.infrastructure.telegram.gateway import BotLike
    from bob.kernel.ports import Clock
    from bob.memory.ports import SelfActionRecorder
    from bob.social.usecases import Authorizer

#: Каталог контролируемого окружения спавна — СОСЕД клонов внутри ``coder.clone_root``.
#: Имя с точки: рабочее место зовётся по слагу ветки ``bob/<slug>``, а точка в слаге
#: невыразима, поэтому столкнуться этим именам не с чем.
_SPAWN_ENV_DIR = ".spawn-env"

#: Каталог трекера beads в репозитории ВЛАДЕЛЬЦА — тот самый, который спавн получает через
#: ``BEADS_DIR`` (BOB-088, срез 2). Имя фиксировано самим ``bd``, ключа в конфиге у него
#: сознательно нет: это не настройка, а факт устройства репозитория, и второй источник
#: правды тут однажды разъехался бы с первым.
_TRACKER_DIR = ".beads"

#: 🔴 Безопасная дорога — ДЕФОЛТ (bob-c3r.1, лечение P0 ``bob-l3t``). Раньше дефолтом было
#: OFF, а включение жило в ``config/bob.yaml``, который GITIGNORED: на чистом клоне и на
#: любой другой машине Боб снова работал в linked worktree владельца. Защита, которую
#: держит untracked-файл, — не защита; owner отказывается от неё ЯВНО.
_ISOLATED_CLONE_DEFAULT = True

#: Формы, которыми пишут «да» и «нет» (yaml даёт bool, окружение — строку). Всё, что не
#: входит ни в одно множество, — НЕ отказ и НЕ согласие, а неразобранное значение.
_EXPLICIT_YES = frozenset({"1", "true", "yes", "on"})
_EXPLICIT_NO = frozenset({"0", "false", "no", "off"})


def _uses_isolated_clone(coder: Mapping[str, object]) -> bool:
    """ОДНО решение: рабочее место — отдельный КЛОН, а спавн — без кредов owner'а.

    🔴 ЕДИНСТВЕННОЕ место, где читается ``coder.isolated_clone``. Раньше его читали ТРИ
    функции подряд (:func:`_build_workspace`, :func:`_build_spawn_isolation`,
    :func:`_build_pr_integration`), при том что докстрока первой обещала «ОДНО место»;
    разъехавшись, три чтения дали бы ПОЛУ-включённое состояние — клон есть, кредов не
    убрали, — и звучало бы оно как включённое. Клон и изоляция — две половины ОДНОЙ
    гарантии, поэтому и решение одно.

    Дефолт — :data:`_ISOLATED_CLONE_DEFAULT` (ON): безопасная дорога не должна зависеть от
    того, дописал ли кто-то ключ в untracked-конфиг. Явный отказ owner'а уважается в любой
    форме, которой его пишут (``false`` / ``"no"`` / ``0`` / ``off``).

    🔴 А значение, которое ЧИТАЕТСЯ как настройка, но ни «да», ни «нет» (пустая строка,
    опечатка, ``"да"``, список), отвергается ГРОМКО и на СБОРКЕ — не молча в OFF, как
    делал прежний :func:`~bob.runtime.config._flag`. Тихий OFF здесь и есть класс этого
    эпика: ключ в конфиге стоит, выглядит включённым, а защиты нет. Отказ на сборке —
    та же конвенция, что у :func:`_refuse_a_fork_the_credentials_do_not_cover` и у
    :class:`GitClone` с кредами в URL: дефект конфигурации ронять до старта, назвав ключ.
    """
    value = coder.get("isolated_clone")
    if value is None:
        return _ISOLATED_CLONE_DEFAULT
    if isinstance(value, bool):
        return value
    written = str(value).strip().lower() if isinstance(value, (str, int)) else ""
    if written in _EXPLICIT_YES:
        return True
    if written in _EXPLICIT_NO:
        return False
    raise ValueError(
        f"coder.isolated_clone={value!r} is neither an explicit yes nor an explicit no — "
        "and this key decides whether Bob works in an isolated clone without the owner's "
        "credentials, so a value that merely LOOKS configured must not silently answer it. "
        f"Write one of {sorted(_EXPLICIT_YES)} / {sorted(_EXPLICIT_NO)}, or drop the key: "
        "the isolated clone is the default."
    )


def _under_repo_root(value: str) -> Path:
    """Привязать относительный путь к КОРНЮ РЕПОЗИТОРИЯ, а не к текущему каталогу.

    🔴 Урок BOB-087.D5b, он же ревью bob-a6b.6 (M4): ``source`` клона абсолютен
    (:data:`~bob.runtime.config._REPO_ROOT`), а ``coder.clone_root`` по умолчанию
    относителен — при ``cwd ≠ корень репозитория`` рабочие места и файлы окружения спавна
    уехали бы в чужой каталог, и заметил бы это не тест, а прод. Абсолютное значение
    владельца уважается как есть.

    Само правило живёт в ядре (:func:`bob.kernel.config_paths.under_root`) — его же читает
    домен, разбирая путь к приватному ключу принципала (bob-a6b.15). Здесь остался только
    ОДИН вопрос композиции: какой корень подставить.
    """
    return under_root(value, root=_REPO_ROOT)


def _build_coding_router(
    config: Mapping[str, object],
    *,
    router: LLMRouter,
    coder: CodingAssistant | None,
) -> CodingIntentRouter | None:
    """Assemble the natural-language coding-intent router, or ``None`` when off (BOB-041 .2).

    Built ONLY when the gated coding assistant is wired (``coder.enabled``). It pairs the
    cheap Tier-0 :class:`ClassifyCodingIntent` (coding vs chat) with the same gated
    :class:`CodingAssistant` the ``/code`` command drives, so an owner message in Bob's
    topic can plan / approve / stop a session naturally. Off (coder disabled → ``coder``
    is ``None``) → ``None``, and HandleMessage's natural-language path stays inert.

    🔴 SAFETY (BOB-076): auto-starting a FRESH session from natural chat is gated behind
    ``coder.nl_autostart`` (default OFF). A cheap Tier-0 misclassification of a casual
    owner reply once launched a runaway coder from ordinary chat, so by default the
    router only drives approve/stop of an ALREADY-live session and a fresh session starts
    ONLY via an explicit ``/code`` command. Flip the flag on to opt back into NL start.
    """
    if coder is None:
        return None
    return CodingIntentRouter(
        coder=coder,
        classifier=ClassifyCodingIntent(router=router),
        nl_autostart=_flag(_section(config, "coder"), "nl_autostart"),
    )


def _build_workspace(coder: Mapping[str, object]) -> GitWorktree | GitClone:
    """Собрать рабочее место Боба: отдельный КЛОН (default) или linked worktree (BOB-089.A).

    Решение читается у :func:`_uses_isolated_clone` — ОДНОГО места, где живёт флаг
    ``coder.isolated_clone`` и его дефолт. Оба адаптера реализуют одни и те же порты
    (:class:`~bob.coding.ports.Worktree` + :class:`~bob.coding.ports.PersistentWorkspace`),
    поэтому ни гейтед-ассистент, ни менеджер интерактива не знают, во что они приземляются.

    🔴 ИСПРАВЛЕНО ПО ФАКТУ 2026-08-15 (bob-c3r.1; правка видимая). Здесь стояло «ОДНО
    место, где читается флаг ``coder.isolated_clone`` (default OFF)», и оба утверждения
    были неверны: читали флаг ТРИ функции этого модуля, а дефолт OFF означал, что живая
    сессия claude работает в репозитории владельца, если только кто-то не дописал ключ в
    gitignored ``config/bob.yaml``. Теперь место действительно одно, а дефолт — ON.

    OFF (ЯВНЫЙ отказ owner'а) → ровно прежний :class:`GitWorktree` с прежним аргументом
    (``coder.worktree_root``, default ``.worktrees``): сборка байт-в-байт как до среза, и
    это проверяется РАВЕНСТВОМ типа и аргументов, а не «похожестью».

    ON (дефолт) → :class:`GitClone`: клон в ``coder.clone_root`` (default ``.clones``) из
    локального пути репозитория, единственный remote — ``coder.fork_url`` (пусто → у
    клона remote'а нет вовсе). 🔴 Смысл включения: у клона свой ``.git``, поэтому
    ``git update-ref refs/heads/main`` внутри него до main owner'а не достаёт — в linked
    worktree достаёт, без сети и без кредов.

    🔴 ИСПРАВЛЕНО ПО ФАКТУ ×2 (bob-a6b.17; обе ошибки оставлены ВИДИМЫМИ, а не переписаны
    задним числом — Issues #49). Докстрока утверждала два уже опровергнутых в этом же
    эпике факта:

    * «апстрим не прописывается ни при каком значении» — СЕДЬМОЙ повтор формы, которую
      ревьюер снял на настоящем git (bob-a6b.6, MAJOR-7/8): модель дописывает
      ``remote.origin.pushurl`` локальным конфигом поверх нашего argv, а
      ``url.<апстрим>.pushInsteadOf`` уводит ветку даже при push'е по значению. Верно
      только узко — ПРИ ЗАВЕДЕНИИ клона (:func:`bob.coding.clone_plan.origin_argv`);
    * «изоляции КРЕДОВ этот флаг не даёт (это срез C)» — ровно наоборот, и опровергается
      функцией :func:`_build_spawn_isolation` ПЯТНАДЦАТЬЮ строками ниже: она читает ТОТ ЖЕ
      ``coder.isolated_clone``. Срез C приехал под этим же флагом сознательно — клон и
      изоляция две половины одной гарантии, поэтому флаг один.
    """
    if not _uses_isolated_clone(coder):
        return GitWorktree(_str(coder, "worktree_root", ".worktrees"))
    return GitClone(
        _under_repo_root(_str(coder, "clone_root", ".clones")),
        source=_REPO_ROOT,
        fork_url=_str(coder, "fork_url", ""),
        # Подпись работы в клоне (BOB-089.D): ``bob[ai]`` + ботовский noreply-адрес,
        # ЛОКАЛЬНО в клоне. Пустой id → адрес без числового префикса; имя стоит всегда.
        app_user_id=_str(coder, "app_user_id", ""),
    )


def _build_spawn_isolation(coder: Mapping[str, object]) -> SpawnIsolation | None:
    """Собрать изоляцию окружения спавна от кредов owner'а, или ``None`` при OFF (BOB-089.C).

    Читается ТОТ ЖЕ флаг, что выбирает рабочее место (``coder.isolated_clone``), и
    отдельного у изоляции нет сознательно: клон и изоляция — две половины ОДНОЙ гарантии.
    Клон закрывает локальную дорогу к ``main`` (свой ``.git``), изоляция — сетевую (нет
    кредов owner'а); включить одну без другой значит получить половину, а звучать это
    будет как целое (срез A так и записал: «клон в одиночку — половина гарантии» — эта
    фраза верна про СРЕЗ A во времени, но не про ФЛАГ сегодня, и ровно так её прочитала
    докстрока :func:`_build_workspace`, пока bob-a6b.17 её не поправил).

    OFF → ``None``: спавн вообще без ``env=`` (байт-в-байт прежний) и НИ ОДНОГО файла на
    диске. ON → файлы контролируемого окружения в ``<clone_root>/.spawn-env`` (0700):
    подменный global-конфиг, пустой каталог конфигурации ``gh``, askpass в никуда и
    «ключ» ssh в никуда (bob-a6b.10 — без него git ходил по ``git@host:`` ключом owner'а
    из ``~/.ssh``, и сетевая дорога к апстриму по ssh была ОТКРЫТА).

    🔴 Кредов спавну не выдаётся (стор не создаётся): ветку в форк пушит процесс САМОГО
    Боба (``GitClone.commit_and_push``), а не ``claude`` внутри клона. Механизм выдачи
    токена существует и проверен (:func:`bob.identity.spawn_isolation.credential_store_line`),
    но вызывающего в проде у него пока НЕТ — и это записано честно, а не выдано за фичу.

    🔴 А ВОТ ОДНА ДОРОГА ЗДЕСЬ ОТКРЫВАЕТСЯ, И НАЗЫВАЕТСЯ ВСЛУХ (BOB-088, срез 2): спавн
    получает :data:`_TRACKER_DIR` владельца (``BEADS_DIR``), то есть ЗАПИСЬ в его трекер
    beads. Причина — тем же срезом 1 рабочее место стало клоном, а из клона ``bd`` не
    находит базу вовсе; конвейер без ``bd`` не работает. Что именно этим открыто, чем
    оплачено и почему приемлемо — в докстроке
    :data:`bob.identity.spawn_isolation.PURGED_SPAWN_VARS`. Каталог берётся от КОРНЯ
    РЕПОЗИТОРИЯ, а не от ``cwd``: иначе спавн, поднятый из другого каталога, уехал бы в
    чужой (или несуществующий) трекер — урок bob-a6b.6 M4 про ``clone_root``.
    """
    if not _uses_isolated_clone(coder):
        return None
    root = _under_repo_root(_str(coder, "clone_root", ".clones")) / _SPAWN_ENV_DIR
    return SpawnIsolationFiles(root).materialize(beads_dir=str(_REPO_ROOT / _TRACKER_DIR))


def _build_pr_integration(
    coder: Mapping[str, object],
    github: Mapping[str, object],
) -> tuple[GhPullRequestOpener | ForkCompareLink, bool]:
    """Собрать путь «работа доехала до owner'а» + честен ли он как «PR открыт» (BOB-089.D).

    ОДНО место, где решается, чем заканчивается сессия, и решение ПАРНОЕ: адаптер и флаг
    ``opens_pr`` для use-case'а приезжают отсюда вместе. Разведи их — и Боб скажет «вот PR»
    там, где PR не открыт; это ровно тот класс неправды, который owner проверит первым же
    нажатием.

    Default (и любой неполный набор) → прежний :class:`GhPullRequestOpener` с ``opens_pr``
    ``True``: сборка байт-в-байт как до среза.

    Ссылочный путь (:class:`ForkCompareLink`, ``opens_pr`` ``False``) заводится ТОЛЬКО когда
    он осмыслен целиком: рабочее место — клон (``coder.isolated_clone``), у клона настроен
    форк на GitHub (``coder.fork_url`` → слаг ``owner/repo`` берётся из ТОГО ЖЕ адреса, куда
    уходит push, чтобы ссылка не разошлась с местом работы) и известен апстрим. 🔴 Почему
    вообще ссылка: cross-repo PR из ПРИВАТНОГО форка installation-токену недоступен
    (проверено три способа, не-цель PRD), поэтому owner жмёт «Create pull request» сам.

    🔴 ОДИН ФАКТ — ОДИН КЛЮЧ (bob-a6b.9). Апстрим — это ``github.propose_repo``, и другого
    источника у него нет: та же секция, которой принципал ``propose`` находит свою
    установку, называет и цель ссылки. Прежний ``coder.upstream_repo`` УБРАН, а не оставлен
    «на всякий случай»: два ключа на один факт однажды разъезжаются, и тогда Боб отдаёт
    ссылку на один репозиторий, а права на чтение имеет к другому.
    """
    fork = repo_slug(_str(coder, "fork_url", ""))
    upstream = _str(github, "propose_repo", "").strip()
    if not (_uses_isolated_clone(coder) and fork and upstream):
        return GhPullRequestOpener(gh_bin=_str(coder, "gh_bin", "gh")), True
    _refuse_a_fork_the_credentials_do_not_cover(fork, _str(github, "work_repo", ""))
    return ForkCompareLink(upstream=upstream, fork=fork), False


def _refuse_a_fork_the_credentials_do_not_cover(fork: str, work_repo: str) -> None:
    """Сверить два УГЛА одного факта — репозитория, куда Боб пушит (bob-a6b.9).

    ``coder.fork_url`` — транспортный адрес (может быть ssh, может быть ``file://``), а
    ``github.work_repo`` — слаг ``owner/repo``, по которому находится УСТАНОВКА принципала
    ``work``. Дублем они не являются (из слага не собрать ssh-адрес, а из адреса не всегда
    добыть слаг — см. :func:`~bob.coding.pr_link.repo_slug`), поэтому ключи остаются два.
    Но факт за ними ОДИН, и разъехаться им нельзя: тогда ветка уезжает в один репозиторий,
    ссылка обещает owner'у второй, а права у Боба к третьему.

    🔴 Отказ громкий и на СБОРКЕ, а не тихий уход на gh-путь: молчаливый фолбэк спрятал бы
    дефект конфига и Боб пошёл бы пушить в апстрим кредами owner'а (урок BOB-087 — верхний
    фолбэк не маскирует наши дефекты). В тексте отказа — ИМЕНА обоих ключей.

    Пустой ``work_repo`` расхождением НЕ считается: пока принципалы не настроены (а это
    дефолт), сверять не с чем, и падать на этом значило бы ронять сборку у owner'а с пустой
    секцией ``github``. Сравнение регистронезависимо — имена репозиториев на GitHub такие же.
    """
    expected = work_repo.strip()
    if not expected or fork.casefold() == expected.casefold():
        return
    raise PullRequestError(
        f"coder.fork_url points at {fork!r}, but github.work_repo says Bob's credentials "
        f"cover {expected!r}; these are two angles of ONE repository and must agree — "
        "refusing to hand the owner a link to a fork Bob has no rights to"
    )


def _build_coding_assistant(
    config: Mapping[str, object],
    *,
    repo: SqliteConnection,
    authorizer: Authorizer,
    notifier_bot: BotLike,
    stream_bot: BotLike,
    chat_id: int,
    topic_id: int | None,
    owner_id: int,
    clock: Clock,
    recorder: SelfActionRecorder,
    work_journal: WorkJournalRecorder,
) -> CodingAssistant | None:
    """Assemble the gated coding assistant, or ``None`` when off (BOB-039 .3).

    Built ONLY when ``coder.enabled`` is on (conservative default off): «Bob runs Claude
    Code» is the most powerful capability, so it stays unwired unless the owner switches
    it on (unwired → ``/code`` answers "disabled"). It composes the shell-free infra
    adapters — :class:`SubprocessClaudeRunner` (a fixed ``--permission-mode`` allowlist),
    :class:`GitWorktree` (an isolated worktree of TRACKED files only — Bob's private data
    never reaches Claude Code) and :class:`GhPullRequestOpener` (``gh pr create`` only,
    NO merge / push-main) — over the durable :class:`SqliteCodingSessionStore`, with the
    shared :class:`Authorizer` as the owner gate and a BOB-bot owner-notifier (BOB-046 .1:
    Bob speaks, GUPPI executes). The UNBYPASSABLE plan gate lives in the use-case + domain
    machine; this only wires it. The assistant is deliberately NOT added to
    ``goals.safe_capabilities`` (never autonomous).

    The flag-gated ``recorder`` (BOB-079) is threaded in from the composition root so each
    lifecycle transition records a first-person ``self_action`` episode; when
    ``memory.autobiography`` is OFF it is the NoOp (zero writes, unchanged behaviour).

    🔴 Firehose channel (BOB-087.A1): the mechanical per-event narration + the DM
    live-stream are GUPPI's work (the dry executor), so under ``coder.stream_via_guppi``
    (default OFF) they are routed AS GUPPI — the ``stream_notifier`` + the live-streamer are
    built over ``stream_bot`` (GUPPI's bot). Bob's OWN voice (the ``session_voice`` gate
    lines, the "продолжаю" cap notice, the typing/status indicators) stays on ``notifier_bot``
    (Bob's bot). OFF → the firehose falls back to Bob's bot exactly as before (byte-identical:
    ``stream_notifier`` is ``None`` and the live-streamer targets ``notifier_bot``).

    🔴 WHO says WHAT is not decided here (BOB-090.D). The wiring only answers «does GUPPI
    have a channel of his own this boot» (the flag); the canon line — mechanics is GUPPI's
    voice, everything live and addressed to people is Bob's, and a permission request is
    Bob's too — lives in the pure :mod:`bob.coding.speaker`, and the use-case routes every
    single message through it. Change the canon there, never at a send site or here.

    🔴 Owner-only sandbox relaxations (BOB-087.D2): ``coder.allow_bypass`` (default OFF)
    admits ``bypassPermissions`` into the runner's ``--permission-mode`` allowlist, and
    ``coder.extra_dirs`` (default empty) passes ``--add-dir`` paths OUTSIDE the worktree.
    Both are threaded into the runner here and are inert by default. 🔴 Said honestly
    (BOB-087.D5b): Bob's OWN code still has no push/merge path, but ``bypassPermissions``
    hands claude an unsupervised shell in a worktree that SHARES the main repo's ``.git``
    (refs, remotes, credentials), so with that flag on «main is reached only through a PR»
    rests on the owner's judgement rather than on structure.

    🔴 ИСПРАВЛЕНО ПО ФАКТУ 2026-08-15 (bob-c3r.1, находка ``bob-l3t``; правка ВИДИМАЯ, а не
    переписанная задним числом). Здесь стояло: «OFF (the default) keeps the per-action gate
    that actually makes it structural». Живая проба настоящим CLI ТОЧНОЙ формой спавна Боба
    (``-p --input-format stream-json --output-format stream-json --verbose
    --permission-mode acceptEdits``) показала, что пер-действенного гейта в headless-режиме
    НЕТ: пишущая команда вне ``--allowedTools`` выполнилась молча, события запроса
    разрешения не пришло, зависания тоже не было. Фраза обещала гарантию, которой никогда
    не существовало, и ровно на неё опиралось «main достижим только через PR».

    🔴 ЧТО ДЕРЖИТ ГРАНИЦУ НА САМОМ ДЕЛЕ (после этого среза, по убыванию силы):
    ``coder.isolated_clone`` — рабочее место как отдельный КЛОН со своим ``.git``, поэтому
    локальный ``update-ref`` до ствола owner'а не достаёт, плюс окружение спавна без кредов
    owner'а (:func:`_build_spawn_isolation`), поэтому у амбиентной сетевой дороги нет права
    записи; и БЕЗУСЛОВНЫЙ push-барьер (см. ниже) — страховка от нечаянного, не граница. В
    самом Бобе пути push/merge по-прежнему нет. Пер-действенного гейта в этом списке нет и
    не будет: имитировать его поверх CLI значило бы завести третью иллюзию защиты в одном
    месте (решение RFC BOB-088).

    🔴 Push guard (BOB-087.E, bob-5ao; развязан с ослаблением в bob-c3r.1): спавн раннера
    ВСЕГДА несёт git-конфиг (``url.<stub>.pushInsteadOf``), от которого сетевой push из
    рабочего места умирает на несуществующем remote-хелпере — см.
    :mod:`bob.coding.push_guard`, включая честные пределы (это страховка от НЕЧАЯННОГО
    push, а не граница: процесс владеет своим окружением). Раньше барьер стоял РОВНО при
    ``allow_bypass``, то есть включался только вместе с ослаблением, которое его же
    обесценивает, — в живом конфиге барьера не было вовсе. Собственный интеграционный путь
    Боба барьер не трогает, и это ИЗМЕРЕНО настоящим git, а не заявлено:
    :class:`GitWorktree` / :class:`GitClone` / :class:`GhPullRequestOpener` спавнят git
    через ``ExecRunner`` в процессе САМОГО Боба, без ``env=``, тогда как окружение с
    барьером собирается только в дефолтных спавнерах ``claude``
    (``tests/infrastructure/coding/test_push_barrier_always_real_git.py``).
    """
    coder = _section(config, "coder")
    if not _flag(coder, "enabled"):
        return None
    timeout = float(_int(coder, "timeout", 600))
    # Firehose bot selection (BOB-087.A1): GUPPI's bot when the flag is ON, else Bob's bot
    # (so the OFF path is byte-identical — the same single channel as today).
    stream_via_guppi = _flag(coder, "stream_via_guppi")
    firehose_bot = stream_bot if stream_via_guppi else notifier_bot
    # Интеграционный путь + честность терминальной реплики — ОДНО решение (BOB-089.D),
    # см. :func:`_build_pr_integration`.
    pr_opener, opens_pr = _build_pr_integration(coder, _section(config, "github"))
    return CodingAssistant(
        recorder=recorder,
        # Distilled work memory (BOB-087.B1): flag-gated (``memory.work_journal``, OFF → NoOp)
        # recorder that distills the run's key facts into first-person operator episodes at
        # session end. Threaded from the composition root, like ``recorder``.
        work_journal=work_journal,
        context=make_coding_context(
            _build_introspector(config), PrivacyGuard(repo_root=_REPO_ROOT)
        ),
        runner=SubprocessClaudeRunner(
            claude_bin=_str(coder, "claude_bin", "claude"),
            timeout=timeout,
            # 🔴 Owner-only sandbox relaxations (BOB-087.D2), both inert by default:
            # ``allow_bypass`` OFF keeps the allowlist at {plan, acceptEdits} and an empty
            # ``extra_dirs`` appends no ``--add-dir`` — the argv stays byte-identical.
            allow_bypass=_flag(coder, "allow_bypass"),
            extra_dirs=_str_list(coder, "extra_dirs"),
            # 🔴 Изоляция от кредов owner'а (BOB-089.C) под ``coder.isolated_clone``:
            # OFF → ``None``, спавн байт-в-байт прежний. См. :func:`_build_spawn_isolation`.
            isolation=_build_spawn_isolation(coder),
        ),
        # Рабочее место: linked worktree (default) или отдельный клон под
        # ``coder.isolated_clone`` (BOB-089.A) — см. :func:`_build_workspace`.
        worktree=_build_workspace(coder),
        store=SqliteCodingSessionStore(repo),
        pr_opener=pr_opener,
        # 🔴 Идёт В ПАРЕ с выбранным адаптером: True → «вот PR», False → «работа в форке,
        # PR за тобой» со ссылкой. Расхождение этой пары было бы ложью owner'у.
        opens_pr=opens_pr,
        notifier=_CodingOwnerNotifier(
            bot=notifier_bot, chat_id=chat_id, topic_id=topic_id
        ),
        # The mechanical per-event narration firehose → GUPPI's bot when the flag is ON; OFF
        # → ``None`` so the use-case falls back to the Bob ``notifier`` (byte-identical).
        stream_notifier=(
            _CodingOwnerNotifier(bot=firehose_bot, chat_id=chat_id, topic_id=topic_id)
            if stream_via_guppi
            else None
        ),
        owner=authorizer,
        clock=clock,
        execute_mode=_str(coder, "permission_mode", "acceptEdits"),
        # Work indicator (BOB-046 .2): "Bob is typing…" through the silent claude waits
        # + one editable status panel, both into Bob's topic via Bob's bot. Both degrade
        # to a no-op if the bot cannot send the action / edit the message. These are Bob's
        # own presence markers → they stay on Bob's bot regardless of the firehose flag.
        typing_keepalive=TypingKeepalive(
            bot=cast("TypingActionBot", notifier_bot),
            chat_id=chat_id,
            thread_id=topic_id,
            interval=_CODING_TYPING_INTERVAL,
            sleep=asyncio.sleep,
        ),
        status_panel=StatusPanel(
            bot=cast("EditableStatusBot", notifier_bot),
            chat_id=chat_id,
            thread_id=topic_id,
        ),
        # Dev-channel live-stream (BOB-082.3): when ``coder.dev_dm`` is ON, the raw,
        # UNCAPPED execute stream renders into the owner's private DM (the group topic gets
        # only a one-line pointer, INV-5). OFF (default) → ``None`` and the run is narrated
        # to the group capped exactly as before (zero behaviour change). The raw stream is
        # firehose → it follows ``firehose_bot`` (GUPPI when ``stream_via_guppi`` is ON).
        live_streamer=_build_dm_live_streamer(
            coder, bot=firehose_bot, owner_id=owner_id
        ),
    )


def _build_dm_live_streamer(
    coder: Mapping[str, object],
    *,
    bot: BotLike,
    owner_id: int,
) -> LiveRunStreamer | None:
    """Assemble the DM live-stream renderer, or ``None`` when the dev-channel is off (BOB-082.3).

    Built ONLY when ``coder.dev_dm`` is on (conservative default off). It targets the
    owner's private DM (``coder.dev_dm_chat_id``, default = ``owner_id``; a 1:1 chat, so
    ``message_thread_id`` is ``None``) through the same BOB-bot :class:`_CodingOwnerNotifier`
    used for the group — only the chat/thread differ — plus a rolling editable
    :class:`StatusPanel` for the live "terminal" feel. Off (the default) → ``None`` and the
    use-case narrates the run to the group capped, exactly as before.
    """
    if not _flag(coder, "dev_dm"):
        return None
    dm_chat_id = _int(coder, "dev_dm_chat_id", owner_id)
    return _DmLiveStreamer(
        notifier=_CodingOwnerNotifier(bot=bot, chat_id=dm_chat_id, topic_id=None),
        panel=StatusPanel(
            bot=cast("EditableStatusBot", bot), chat_id=dm_chat_id, thread_id=None
        ),
    )


def _build_interactive_session(
    config: Mapping[str, object],
    *,
    repo: SqliteConnection,
    authorizer: Authorizer,
    bot: BotLike,
    stream_bot: BotLike,
    owner_id: int,
    clock: Clock,
) -> InteractiveSessionManager | None:
    """Assemble the interactive-session manager, or ``None`` when off (BOB-083 .3).

    Built ONLY when ``coder.interactive`` is on (conservative default off): a live,
    bidirectional ``claude`` terminal in the owner's DM is the most powerful capability
    of the coding seam, so it stays unwired unless the owner switches it on (off → the
    manager is not built and the ``.4`` intake mode is inert). It injects a FRESH
    :class:`InteractiveClaudeRunner` per session (a factory), the SAME isolated
    :class:`GitWorktree` (edits go to a ``bob/<slug>`` branch — NEVER main, INV-2) and
    durable :class:`SqliteCodingSessionStore` the gated coder uses, the shared
    :class:`Authorizer` as the owner gate, and a per-session :class:`_DmLiveStreamer`
    (reuse of BOB-082) targeting the owner's private DM for the live output. 🔴 There is
    DELIBERATELY no PR-opener here — the manager physically cannot merge/push; the owner
    reviews the worktree branch and lands it through the existing BOB-039 gate.

    🔴 Firehose channel (BOB-087.A1): the interactive DM live-stream IS the mechanical
    firehose, so under ``coder.stream_via_guppi`` (default OFF) it is rendered AS GUPPI —
    the per-session streamer is built over ``stream_bot`` (GUPPI's bot). OFF → ``bot`` (Bob's
    bot) exactly as before (byte-identical). The short Bob mode lines (open/stop) live in the
    intake router (`_build_interactive_intake`) and stay on Bob's bot regardless. In the
    canon vocabulary (:mod:`bob.coding.speaker`, BOB-090.D) the split here is structural, so
    it needs no per-message verdict: the raw stream is ``TOOL_OUTPUT`` (GUPPI's), while every
    line the manager and the router speak is a ``MODE_NOTICE`` — Bob talking to a person.

    🔴 Owner-only sandbox relaxations (BOB-087.D2): ``coder.allow_bypass`` (default OFF)
    and ``coder.extra_dirs`` (default empty) are read once and baked into every
    per-session runner, so the owner can trade sandbox strictness for speed INSIDE the
    worktree. Inert by default → the spawn argv is byte-identical to BOB-083. 🔴 Honestly
    (BOB-087.D5b): the manager itself still has no PR-opener and cannot merge / push, and
    that part IS structural. But a worktree is a LINKED checkout sharing the main repo's
    ``.git`` — refs, remotes, credentials — so once ``allow_bypass`` gives claude an
    unsupervised shell in it, the trunk is protected by the owner's judgement about what
    he lets claude do, not by the absence of a code path in Bob. 🔴 BOB-087.E (bob-5ao)
    lowers that risk WITHOUT pretending to close it: the spawn of every per-session runner
    built here carries the push guard (:mod:`bob.coding.push_guard`) — a network push from
    the live terminal dies on a non-existent remote helper. It is an accident guard, not a
    boundary (the process owns its environment; a local ``update-ref`` on the shared
    ``.git`` never touches push).

    🔴 ИСПРАВЛЕНО ПО ФАКТУ 2026-08-15 (bob-c3r.1, находка ``bob-l3t``; правка видимая, а не
    переписанная задним числом). Абзац выше говорил: «every per-session runner inherits the
    same ``allow_bypass``, so its spawn carries the push guard» — то есть барьер приезжал
    ТОЛЬКО ВМЕСТЕ С ОСЛАБЛЕНИЕМ, которое его же обесценивает; в живом конфиге ослабления
    нет, значит не было и барьера. Теперь барьер безусловен, а ``allow_bypass`` влияет
    ровно на allowlist режимов. И то же самое про слово «структурная» рядом с песочницей:
    живая проба настоящим CLI показала, что пер-действенного гейта в headless-режиме НЕТ
    ни при каком флаге. Границу держит структура — клон со своим ``.git`` и окружение без
    кредов owner'а (:func:`_build_workspace`, :func:`_build_spawn_isolation`).

    🔴 Реплика о конце сеанса (bob-kv4): менеджер получает СВОЙ owner-нотификатор в личку
    (бот Боба) — единственный канал для того, что он говорит по собственной инициативе,
    когда ``claude`` кончился САМ. Все прочие реплики возвращаются ходу, который их
    попросил; у смерти процесса такого хода нет, и без этого сейма Боб просто немел.

    🔴 Стартовый промпт конвейера (BOB-088, срез 2): под флагом ``coder.pipeline_prompt``
    (default OFF) свежая сессия получает ПЕРВЫМ КАДРОМ постановку — задачу owner'а плюс
    указание вести работу по ``CLAUDE.md`` (эпик — через ``/coordinator``, роли
    субагентами). До этого среза ``runner.open(...)`` вызывался и в сессию не уходило
    НИЧЕГО: ``claude`` стартовал с пустым контекстом и ждал, пока owner напишет сам.
    OFF → спавн байт-в-байт прежний. 🔴 Текст решает домен
    (:func:`bob.interactive.pipeline_prompt.pipeline_first_frame`), здесь только флаг: строка в
    композиции была бы поведением конвейера вне mutation-гейта (§0.3 п.7).

    🔴 Долгоживущее рабочее место + resume (BOB-087.D3, D5b): под флагом ``coder.resume``
    (default OFF) в менеджер инъектируются два узких порта: ``lookup`` (поиск сессий по
    ветке, структурно тот же :class:`SqliteCodingSessionStore`) и ``workspace``
    (персистентный worktree, структурно тот же :class:`GitWorktree`). Они обслуживают ОБА
    конца цикла: ``open_workspace`` (завести накапливающее дерево) и ``resume`` (поднять в
    нём прошлую сессию). OFF → порты ``None``, путь не собран: ни ``/workspace``, ни
    ``/resume`` не распознаются интейком, персистентное дерево не создаётся, поведение
    байт-в-байт как в BOB-083.
    """
    coder = _section(config, "coder")
    if not _flag(coder, "interactive"):
        return None
    dm_chat_id = _int(coder, "dev_dm_chat_id", owner_id)
    claude_bin = _str(coder, "claude_bin", "claude")
    # 🔴 Owner-only sandbox relaxations (BOB-087.D2) — read ONCE here and baked into every
    # per-session runner. Both inert by default (allowlist {plan, acceptEdits}, no
    # ``--add-dir``), so an unconfigured interactive spawn is byte-identical to BOB-083.
    allow_bypass = _flag(coder, "allow_bypass")
    extra_dirs = _str_list(coder, "extra_dirs")
    # 🔴 Изоляция окружения спавна (BOB-089.C) — читается ОДИН раз и запекается в каждый
    # посессионный рантайм, как и ослабления песочницы. OFF → ``None``: спавн живого
    # терминала байт-в-байт прежний. См. :func:`_build_spawn_isolation`.
    isolation = _build_spawn_isolation(coder)
    firehose_bot = stream_bot if _flag(coder, "stream_via_guppi") else bot
    # Рабочее место: linked worktree (default) или отдельный клон под
    # ``coder.isolated_clone`` (BOB-089.A) — см. :func:`_build_workspace`. Один объект
    # обслуживает ОБА шва (эфемерный ``worktree`` + персистентный ``workspace``), как и
    # раньше: подмена происходит здесь, а не в менеджере.
    worktree = _build_workspace(coder)
    store = SqliteCodingSessionStore(repo)
    # 🔴 Resume seams (BOB-087.D3) — wired ONLY under ``coder.resume``. The same two
    # adapters, seen through their narrow read/ensure ports; OFF → ``None`` → the whole
    # resume path is structurally unavailable.
    resume_on = _flag(coder, "resume")
    # 🔴 Права инструментов (BOB-088, срез 3), и они РАЗНОЙ природы — поэтому читаются
    # по-разному. Запрет необратимого (push / remotes / reset --hard / rm / gh pr merge /
    # curl / wget) флага НЕ имеет вовсе: он приезжает в каждый спавн из домена
    # (:func:`bob.interactive.tool_permissions.tool_permission_argv`), и выключить его
    # нечем — ровно урок среза 1, где страховка, выражаемая одним ключом, в проде
    # оказалась выключенной. А ЯВНОЕ разрешение рутины конвейера — ослабление, поэтому
    # оно за owner-флагом ``coder.pipeline_tools`` (default OFF), как ``allow_bypass`` и
    # ``extra_dirs``. 🔴 Без него, по живому замеру, встроенный гейт CLI отказывает даже
    # ``git add`` и ``git commit``: конвейер встанет на первом же коммите, и включать
    # флаг придётся вместе с ``coder.pipeline_prompt``.
    routine_tools = _flag(coder, "pipeline_tools")
    return InteractiveSessionManager(
        runner_factory=lambda: InteractiveClaudeRunner(
            claude_bin=claude_bin,
            allow_bypass=allow_bypass,
            extra_dirs=extra_dirs,
            isolation=isolation,
            routine_tools=routine_tools,
        ),
        worktree=worktree,
        store=store,
        lookup=store if resume_on else None,
        workspace=worktree if resume_on else None,
        # verbose=True (BOB-085.2): the INTERACTIVE DM output renders the FULL curated rich
        # event (assistant text in full + markdown passthrough) and chunks an over-limit
        # piece into ≤ Telegram-limit messages, so claude's answer arrives whole + formatted.
        # The group one-way dev-channel path (`_build_dm_live_streamer`) stays concise.
        streamer_factory=lambda: _DmLiveStreamer(
            notifier=_CodingOwnerNotifier(
                bot=firehose_bot, chat_id=dm_chat_id, topic_id=None
            ),
            panel=StatusPanel(
                bot=cast("EditableStatusBot", firehose_bot),
                chat_id=dm_chat_id,
                thread_id=None,
            ),
            verbose=True,
        ),
        owner=authorizer,
        clock=clock,
        permission_mode=_str(coder, "permission_mode", "acceptEdits"),
        # 🔴 Реплика «сеанс кончился сам» (bob-kv4) — единственная, которую менеджер шлёт
        # по СОБСТВЕННОЙ инициативе: у смерти процесса нет хода-адресата, а раньше она не
        # доходила вообще (сеанс оставался «живым», Боб в личке нем до «стоп»). Это голос
        # САМОГО Боба, поэтому она идёт на ботe Боба в его личку — как короткие строки
        # режима интейка, а не за GUPPI (тот везёт только механический firehose).
        notifier=_CodingOwnerNotifier(bot=bot, chat_id=dm_chat_id, topic_id=None),
        # 🔴 Стартовый промпт конвейера (BOB-088, срез 2) — ЕДИНСТВЕННОЕ место, где
        # читается ``coder.pipeline_prompt``. OFF (дефолт) → в открытый stdin не уходит
        # ничего и сессия ждёт owner'а, ровно как до среза. ON → свежая сессия (обе
        # двери: ``open`` и ``open_workspace``) получает первым кадром задачу и указание
        # идти по ``CLAUDE.md``; сам текст решает домен
        # (:func:`bob.interactive.pipeline_prompt.pipeline_first_frame`), а не композиция —
        # иначе поведение конвейера жило бы в строке проводки, вне mutation-гейта.
        pipeline_prompt=_flag(coder, "pipeline_prompt"),
    )


def _build_interactive_recovery(
    *, repo: SqliteConnection, clock: Clock
) -> RecoverInteractiveSessions:
    """Assemble the boot-time sweep of orphaned live sessions (BOB-087.D5b).

    Built UNCONDITIONALLY — and that is deliberate, not an oversight of the flag rule. An
    ``INTERACTIVE`` row can only exist because a live terminal once ran, and the process
    that could have closed it is gone by the time this runs; leaving it non-terminal
    blocks the GATED coder («я уже в работе») even after the owner switches
    ``coder.interactive`` back off. With no such row the sweep writes nothing at all, so
    the flags-off path stays behaviourally identical.
    """
    return RecoverInteractiveSessions(store=SqliteCodingSessionStore(repo), clock=clock)


def _build_interactive_intake(
    config: Mapping[str, object],
    *,
    manager: InteractiveSessionManager | None,
    bot: BotLike,
    owner_id: int,
) -> InteractiveIntakeRouter | None:
    """Assemble the interactive-terminal intake router, or ``None`` when off (BOB-083 .4).

    Built ONLY when the interactive-session ``manager`` is wired (``coder.interactive``
    on); off → ``None`` and HandleMessage's interactive intake gate stays inert (the mode
    is entirely unavailable — no entry, the consume-gate never fires). It pairs the live
    :class:`InteractiveSessionManager` with a DM-targeted :class:`_CodingOwnerNotifier`
    (the owner's private 1:1 chat, ``message_thread_id`` ``None``) that carries the short
    explicit mode lines Bob sends on open/stop (INV-5). 🔴 owner-only + DM-only live inside
    the router (defense-in-depth over the manager's own owner gate); HandleMessage threads
    the perceived owner verdict + the channel signal in.

    🔴 Persistent workspace + resume (BOB-087.D3, D5b): the manager doubles as the router's
    ``resume`` seam ONLY under ``coder.resume`` (default OFF). OFF → the router holds no
    reference to it at all, so neither ``/workspace …`` nor ``/resume …`` is a command and
    the pending-answer path cannot fire — the turn goes down the ordinary chat path exactly
    as in BOB-083.
    """
    if manager is None:
        return None
    coder = _section(config, "coder")
    dm_chat_id = _int(coder, "dev_dm_chat_id", owner_id)
    return InteractiveIntakeRouter(
        manager=manager,
        notifier=_CodingOwnerNotifier(bot=bot, chat_id=dm_chat_id, topic_id=None),
        resume=manager if _flag(coder, "resume") else None,
    )
