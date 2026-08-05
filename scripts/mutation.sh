#!/usr/bin/env bash
# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
#
# Per-slice mutation run (BOB-066 Срез 0). Mutation testing is a DELIBERATE, targeted
# check on the PURE DOMAIN core a slice touched — NOT a pre-commit/pre-push hook (too
# slow). See .claude/dev-docs/MUTATION.md for the convention (score >= 85%, explicit
# equivalent-mutant triage) and which code is in/out of scope.
#
# Usage:
#   scripts/mutation.sh social.sulk            # mutate only src/bob/social/sulk.py
#   scripts/mutation.sh conversation.brevity   # mutate only src/bob/conversation/brevity.py
#   scripts/mutation.sh                        # WHOLE pure-domain surface (slow; rarely needed)
#
# The argument is a dotted module suffix; it is wrapped into an fnmatch glob and passed to
# mutmut as a mutant-name filter, so only that module's mutants actually run (the
# coverage-stats phase still uses the fast tests/domain suite configured in pyproject.toml).
set -euo pipefail

cd "$(dirname "$0")/.."

# A clean sandbox each run — mutmut copies src/ into ./mutants/ (git-ignored).
rm -rf mutants .mutmut-cache

if [ "$#" -eq 0 ]; then
    echo "Running mutation over the WHOLE pure-domain surface (this is slow)…"
    uv run mutmut run
else
    module="$1"
    echo "Running mutation on module: ${module}"
    uv run mutmut run "*${module}.*"
fi

echo
echo "Survivors (each must be KILLED with a tighter assertion, or triaged as a"
echo "genuinely-equivalent mutant in the bead comment — never padded):"
uv run mutmut results

# 🔴 BOB-090.C1: mutmut оставляет в src/**/__pycache__ байткод из своей песочницы
# (unchecked-hash .pyc), и следующий прогон тестов может молча исполнить СТАРЫЙ код —
# то есть верификация после мутации способна показать зелёное, ничего не проверив.
# Чистим сами: цена — доли секунды, цена ошибки — ложное доверие к гейту.
find src tests -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
