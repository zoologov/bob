#!/usr/bin/env python3
"""Sanitize the generated VitePress content so every page compiles + renders.

VitePress runs Markdown through Vue's template compiler, which chokes on two
things in `beadloom docs site` output:

1. **C4 mermaid blocks** — long node descriptions carry backticks / `<->` / angle
   brackets that break mermaid's in-browser C4 parser. Inside a ```mermaid block
   whose first line is `C4*`, those are swapped for safe look-alikes.
2. **Bare `<` in prose** (the raw `docs/` mirror) — `<word`, `</`, `<-` read as
   an unclosed HTML tag and fail the build. Outside code fences and inline-code
   spans, a tag-looking `<` is escaped to `&lt;`.

Code fences and inline code are left byte-identical. Idempotent (re-escaping
`&lt;` is a no-op). Run after `beadloom docs site --out site`.
"""
from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent  # site/
TARGET_DIRS = ["", "domains", "features", "services", "other", "docs"]

_C4_TRANS = {"`": "'", "<": "‹", ">": "›"}
_INLINE_CODE = re.compile(r"(`[^`]*`)")
# A `<` that Vue would read as a tag start: followed by a letter, `/`, `!` or `-`.
_TAGLIKE_LT = re.compile(r"<(?=[A-Za-z/!\-])")


def _escape_prose(line: str) -> str:
    # Escape tag-looking `<` only in the non-inline-code segments of the line.
    parts = _INLINE_CODE.split(line)
    for i, seg in enumerate(parts):
        if i % 2 == 0:  # even segments are outside `...` inline code
            parts[i] = _TAGLIKE_LT.sub("&lt;", seg)
    return "".join(parts)


def _process(text: str) -> str:
    out: list[str] = []
    in_fence = False
    fence_is_c4 = False
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("```"):
            if not in_fence:
                in_fence = True
                fence_is_c4 = stripped[3:].strip().lower() == "mermaid"
                out.append(line)
                continue
            in_fence = False
            fence_is_c4 = False
            out.append(line)
            continue
        if in_fence:
            if fence_is_c4:
                # Only sanitize when the block is actually a C4 diagram.
                if line.lstrip().startswith("C4") or any(
                    o[0] in line for o in _C4_TRANS.items()
                ):
                    for bad, good in _C4_TRANS.items():
                        line = line.replace(bad, good)
            out.append(line)
            continue
        out.append(_escape_prose(line))
    return "\n".join(out)


def main() -> None:
    changed = 0
    for d in TARGET_DIRS:
        base = ROOT / d if d else ROOT
        if not base.exists():
            continue
        for md in base.rglob("*.md"):
            original = md.read_text(encoding="utf-8")
            updated = _process(original)
            if updated != original:
                md.write_text(updated, encoding="utf-8")
                changed += 1
    print(f"sanitize-content: {changed} file(s) rewritten")


if __name__ == "__main__":
    main()
