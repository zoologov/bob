# Beadloom UX Issues

> Dogfooding feedback: issues, friction points, and improvement ideas collected while using Beadloom in the Bob project.
>
> **How to use:** Add entries during development. Each entry should include date, context, and severity.

---

## Template

```markdown
### [YYYY-MM-DD] Short description

**Severity:** low | medium | high | critical
**Command:** `beadloom <command>`
**Context:** What were you trying to do?
**Issue:** What went wrong or felt awkward?
**Expected:** What would be better?
**Workaround:** How did you work around it? (if applicable)
```

---

## Issues

### [2026-02-26] Edge YAML field names: `src`/`dst` vs `src_ref_id`/`dst_ref_id`

**Severity:** medium
**Command:** `beadloom reindex`
**Context:** Creating initial architecture graph for Bob project.
**Issue:** Used `src_ref_id` / `dst_ref_id` in edges (matching SQLite column names). Beadloom silently ignored all edges — showed `Edges: 0` with only `[warn] Edge src '' not found` warnings. Expected field names are `src` / `dst`. Not documented in generated README.md or AGENTS.md.
**Expected:** Either (a) accept both field name variants, or (b) emit a clear error: `"Unknown field 'src_ref_id' in edge, did you mean 'src'?"`.
**Workaround:** Read loader.py source to discover correct field names.

---

### [2026-02-26] Rules YAML: `tags` vs `tag` in node matcher

**Severity:** medium
**Command:** `beadloom reindex`
**Context:** Writing deny rule with `from: { tags: [layer-domain] }`.
**Issue:** Error message says `"node matcher must have at least one of 'ref_id', 'kind', or 'tag'"` — but the field is `tag` (singular), while the top-level section is `tags` (plural). Easy to confuse.
**Expected:** Accept both `tag` and `tags` in node matchers, or make the error message explicitly say: `"did you mean 'tag' (singular)?"`.
**Workaround:** Changed `tags: [...]` to `tag: <name>`.

---

### [2026-02-26] Rules YAML: `forbid_cycles` requires `edge_kind` but error is unclear

**Severity:** low
**Command:** `beadloom reindex`
**Context:** Writing forbid_cycles rule without `edge_kind` field.
**Issue:** Error `"forbid_cycles.edge_kind is required"` is clear enough, but the field is not mentioned in AGENTS.md or any generated docs.
**Expected:** Include `edge_kind` in the rule examples in AGENTS.md / README.md.
**Workaround:** Added `edge_kind: depends_on`.
