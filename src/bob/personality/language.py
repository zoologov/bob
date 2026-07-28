# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=personality
# beadloom:layer=domain

"""Persona language directive — pin self-generated text to Bob's language (BOB-012).

When Bob speaks *unprompted* — the proactive compose, the Tier-0 self-gate, and
the inner-monologue / reflection heartbeat ticks — there is no user message to
mirror, so without an explicit constraint the model drifts to its default
(English). :func:`language_directive` returns the short imperative line that pins
the persona to his configured language; callers prepend it to those prompts.

Pure and config-light by design: the directive text lives here in the domain
(a persona/identity concern), the *choice* of language comes from config
(``runtime.language``, default :data:`DEFAULT_LANGUAGE`) and is injected into the
application use-cases. A future Bobiverse replica can speak a different language
by configuration alone, without touching this contract.
"""

from __future__ import annotations

# Bob's default language: the owner is Russian-speaking, so a self-generated
# message with nothing to mirror must default to Russian, not English.
DEFAULT_LANGUAGE = "ru"

# Known languages get a directive written *in that language* so the model reads
# the instruction natively (the strongest steer). An unknown code falls back to a
# generic English instruction that still names the code, so the model is always
# constrained rather than left to drift to English.
_DIRECTIVES: dict[str, str] = {
    "ru": "Думай и пиши только по-русски.",
    "en": "Think and write only in English.",
}


def language_directive(language: str) -> str:
    """Return the imperative directive pinning self-generated text to ``language``.

    A known language code yields a directive written in that language; any other
    code yields a generic directive that names the code so the model is still
    constrained (never silently left to default to English).
    """
    known = _DIRECTIVES.get(language)
    if known is not None:
        return known
    return f"Think and write only in this language (code: {language})."
