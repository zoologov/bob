#!/usr/bin/env python3
# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.
# ruff: noqa: RUF002, RUF003 — русские тексты для лога выкатки и владельца, кириллица намеренна

"""Проверки конфигурации прода на выкатке — против НАСТОЯЩЕГО ``/opt/bob/.env`` (BOB-116 D8b).

Одна ответственность: ответить выкатке, соберётся ли конфигурация Боба на этом сервере, —
до того, как ``systemctl restart bob`` превратит ответ «нет» в немого Боба. Скрипт
запускается от пользователя ``bob`` интерпретатором выкаченного ``.venv``, поэтому читает
конфигурацию тем же лоадером, что и сам Боб (``ConfigLoader``), и тем же решением о
дублёре, что и фабрика провайдеров (``understudy_endpoint``).

🔴 Вывод уходит в ПУБЛИЧНЫЙ лог GitHub Actions. Скрипт печатает имена переменных и пути
настроек, но ни одного значения из ``.env``: текст ошибки лоадера, где значение есть
(``KEY='…' cannot be read as …``), проходит через вымарывание каждого значения файла.

Окружение берётся из ФАЙЛА, а не из оболочки выкатки: systemd стартует Боба с
``EnvironmentFile=/opt/bob/.env``, и переменная, которая есть только у оболочки, Бобу не
достанется. Разбор — как у systemd для простых значений: ``KEY=VALUE`` построчно,
комментарии ``#``/``;``, внешние кавычки снимаются.

Режимы (код возврата 0 — да, 1 — нет, 2 — неверный вызов)::

    require-env      --env-file .env                  обязательные переменные на месте
    validate         --config X --env-file .env       конфигурация собирается и полна
    understudy-model --config X [--env-file .env]     модель дублёра или пусто
    compare-keys     --old X --new Y                  пути настроек старого файла, которых
                                                      нет или иначе в новом (без значений)
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml

from bob.infrastructure.config.loader import ConfigLoader
from bob.infrastructure.llm.factory import understudy_endpoint

RUNBOOK_POINTER = "deploy/RUNBOOK.md §9"

# Обязательные переменные /opt/bob/.env — те, что шапка config/bob.vps.yaml называет
# обязательными (идентификаторы и секреты живут только там, BOB-116 D8a).
REQUIRED_ENV: tuple[str, ...] = (
    "BOB_TELEGRAM__CHAT_ID",
    "BOB_TELEGRAM__OWNER_ID",
    "BOB_TELEGRAM__ALLOWED_CHAT_IDS",
    "BOB_TELEGRAM__BOB__TOPIC_ID",
    "BOB_TELEGRAM__TOKEN",
    "GUPPI_TELEGRAM__TOKEN",
    "BOB_LLM__TIER0_API_KEY",
    "BOB_LLM__TIER1_API_KEY",
)

# Настройки, без которых Боб не стартует осмысленно: id — ненулевое целое, список id —
# непустой, токен или ключ — непустая строка.
_REQUIRED_IDS: tuple[str, ...] = (
    "telegram.owner_id",
    "telegram.chat_id",
    "telegram.bob.topic_id",
)
_REQUIRED_ID_LISTS: tuple[str, ...] = ("telegram.allowed_chat_ids",)
_REQUIRED_SECRETS: tuple[str, ...] = (
    "telegram.bob.token",
    "telegram.guppi.token",
    "llm.tier0_api_key",
    "llm.tier1_api_key",
)

# Ключ, имя которого несёт такой маркер, в трекаемом файле значения не имеет (тот же
# перечень, что у гарда tests/infrastructure/config/test_vps_config_is_clean.py).
_SENSITIVE_MARKERS: tuple[str, ...] = (
    "token",
    "key",
    "chat_id",
    "owner_id",
    "topic_id",
    "allowed_chat_ids",
    "owner_dm_chat_id",
    "owner_name",
)

_COMMENT_PREFIXES = ("#", ";")
_QUOTED_MIN_LENGTH = 2  # открывающая и закрывающая кавычка
_QUOTES = ('"', "'")
_REDACTED = "<скрыто>"
# Значение из одного символа не секрет, а вымарывание его ломает весь текст ошибки.
_MIN_REDACTED_LENGTH = 2

_EXIT_OK = 0
_EXIT_FAILED = 1


class CheckFailedError(Exception):
    """Проверка ответила «нет»; текст — для лога выкатки, без значений."""


# --- окружение из файла ------------------------------------------------------------------


def read_env_file(path: Path) -> dict[str, str]:
    """Разобрать файл окружения так, как systemd читает простые значения."""
    if not path.is_file():
        raise CheckFailedError(f"нет файла окружения {path} — мигрируй идентификаторы в .env — "
                          f"{RUNBOOK_POINTER}")
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith(_COMMENT_PREFIXES) or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = _unquote(value.strip())
    return values


def _unquote(value: str) -> str:
    if len(value) >= _QUOTED_MIN_LENGTH and value[0] == value[-1] and value[0] in _QUOTES:
        return value[1:-1]
    return value


def _redact(text: str, env: Mapping[str, str]) -> str:
    """Вымарать из ``text`` каждое значение окружения — длинные первыми."""
    secrets = sorted(
        (value for value in env.values() if len(value) >= _MIN_REDACTED_LENGTH),
        key=len,
        reverse=True,
    )
    for secret in secrets:
        text = text.replace(secret, _REDACTED)
    return text


# --- конфигурация ------------------------------------------------------------------------


def _load(config_path: Path, env: Mapping[str, str]) -> Mapping[str, Any]:
    if not config_path.is_file():
        raise CheckFailedError(f"нет файла конфигурации {config_path}")
    try:
        return ConfigLoader(yaml_path=config_path, env=env).load()
    except (ValueError, TypeError, KeyError, yaml.YAMLError) as exc:
        reason = _redact(f"{type(exc).__name__}: {exc}", env)
        raise CheckFailedError(f"конфигурация не собирается: {reason}") from None


def _lookup(config: Mapping[str, Any], dotted: str) -> object:
    node: object = config
    for part in dotted.split("."):
        if not isinstance(node, Mapping):
            return None
        node = node.get(part)
    return node


def _is_nonzero_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value != 0


def _completeness_findings(config: Mapping[str, Any]) -> list[str]:
    findings = [
        f"{path}: нужно ненулевое целое"
        for path in _REQUIRED_IDS
        if not _is_nonzero_int(_lookup(config, path))
    ]
    for path in _REQUIRED_ID_LISTS:
        value = _lookup(config, path)
        if not (isinstance(value, list) and value and all(map(_is_nonzero_int, value))):
            findings.append(f"{path}: нужен непустой список ненулевых целых")
    findings += [
        f"{path}: нужна непустая строка"
        for path in _REQUIRED_SECRETS
        if not (isinstance(value := _lookup(config, path), str) and value.strip())
    ]
    return findings


def _understudy_model(config: Mapping[str, Any], env: Mapping[str, str]) -> str | None:
    try:
        endpoint = understudy_endpoint(config)
    except KeyError as exc:
        raise CheckFailedError(_redact(f"llm.tier0_fallback: {exc}", env)) from None
    return None if endpoint is None else endpoint.model


# --- режимы ------------------------------------------------------------------------------


def require_env(env_file: Path) -> str:
    env = read_env_file(env_file)
    missing = [name for name in REQUIRED_ENV if not env.get(name, "").strip()]
    if missing:
        raise CheckFailedError(
            f"в {env_file} нет обязательных переменных: {', '.join(missing)} — "
            f"мигрируй идентификаторы в .env — {RUNBOOK_POINTER}"
        )
    return f"env OK: все {len(REQUIRED_ENV)} обязательных переменных на месте"


def validate(config_path: Path, env_file: Path) -> str:
    env = read_env_file(env_file)
    config = _load(config_path, env)
    findings = _completeness_findings(config)
    if findings:
        raise CheckFailedError("конфигурация неполна: " + "; ".join(findings))
    _understudy_model(config, env)
    return "config OK"


def understudy_model(config_path: Path, env_file: Path | None) -> str:
    env = read_env_file(env_file) if env_file is not None else {}
    model = _understudy_model(_load(config_path, env), env)
    return model or ""


def _leaves(node: object, prefix: str = "") -> Iterator[tuple[str, object]]:
    if isinstance(node, Mapping) and node:
        for key, value in node.items():
            yield from _leaves(value, f"{prefix}.{key}" if prefix else str(key))
    elif prefix:
        yield prefix, node


def _is_sensitive(dotted: str) -> bool:
    leaf = dotted.rsplit(".", 1)[-1]
    return any(marker in leaf for marker in _SENSITIVE_MARKERS)


def compare_keys(old_path: Path, new_path: Path) -> str:
    old = dict(_leaves(yaml.safe_load(old_path.read_text(encoding="utf-8")) or {}))
    new = dict(_leaves(yaml.safe_load(new_path.read_text(encoding="utf-8")) or {}))
    lines: list[str] = []
    for path in sorted(old):
        if _is_sensitive(path):
            if old[path] not in (None, "", [], 0):
                lines.append(f"{path}: идентификатор или секрет -> перенести в .env")
        elif path not in new:
            lines.append(f"{path}: нет в config/bob.vps.yaml -> добавить коммитом или "
                         f"согласиться на дефолт")
        elif old[path] != new[path]:
            lines.append(f"{path}: значение отличается -> решить в config/bob.vps.yaml")
    lines.append(f"итого расхождений: {len(lines)}")
    return "\n".join(lines)


# --- вход --------------------------------------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0] if __doc__ else None)
    modes = parser.add_subparsers(dest="mode", required=True)
    env_only = modes.add_parser("require-env")
    env_only.add_argument("--env-file", type=Path, required=True)
    full = modes.add_parser("validate")
    full.add_argument("--config", type=Path, required=True)
    full.add_argument("--env-file", type=Path, required=True)
    model = modes.add_parser("understudy-model")
    model.add_argument("--config", type=Path, required=True)
    model.add_argument("--env-file", type=Path, default=None)
    keys = modes.add_parser("compare-keys")
    keys.add_argument("--old", type=Path, required=True)
    keys.add_argument("--new", type=Path, required=True)
    return parser


def _dispatch(args: argparse.Namespace) -> str:
    if args.mode == "require-env":
        return require_env(args.env_file)
    if args.mode == "validate":
        return validate(args.config, args.env_file)
    if args.mode == "understudy-model":
        return understudy_model(args.config, args.env_file)
    return compare_keys(args.old, args.new)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        message = _dispatch(args)
    except CheckFailedError as exc:
        sys.stderr.write(f"❌ {exc}\n")
        return _EXIT_FAILED
    if message:
        sys.stdout.write(f"{message}\n")
    return _EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
