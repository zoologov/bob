#!/usr/bin/env python3
"""Sanitize C4 mermaid blocks in the generated VitePress content.

`beadloom docs site` embeds a C4Container diagram per node whose long
descriptions carry characters that break mermaid's in-browser C4 parser
(backticks, `<->`, angle brackets). This rewrites ONLY C4 blocks (first content
line starts with `C4`) — replacing backticks and angle brackets with safe
look-alikes — so the diagrams render. Flowchart blocks (which use `-->`) are
left untouched. Idempotent. Run after `beadloom docs site --out site`.
"""
from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent  # site/
TARGET_DIRS = ["", "domains", "features", "services", "other"]
_TRANS = {"`": "'", "<": "‹", ">": "›"}


def _sanitize_block(body: str) -> str:
    for bad, good in _TRANS.items():
        body = body.replace(bad, good)
    return body


_BLOCK = re.compile(r"(```mermaid\n)([\s\S]*?)(```)", re.MULTILINE)


def _process(text: str) -> str:
    def repl(m: re.Match[str]) -> str:
        body = m.group(2)
        first = body.lstrip().split("\n", 1)[0].strip()
        if first.startswith("C4"):  # only C4 diagrams, never flowcharts
            body = _sanitize_block(body)
        return m.group(1) + body + m.group(3)

    return _BLOCK.sub(repl, text)


def main() -> None:
    changed = 0
    for d in TARGET_DIRS:
        base = ROOT / d if d else ROOT
        for md in base.glob("*.md"):
            original = md.read_text(encoding="utf-8")
            updated = _process(original)
            if updated != original:
                md.write_text(updated, encoding="utf-8")
                changed += 1
    print(f"sanitize-mermaid: {changed} file(s) rewritten")


if __name__ == "__main__":
    main()
