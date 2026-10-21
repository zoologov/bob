// beadloom:generated version=9.0.0 sha256=a3a821168b55099e10928e1e44ab0b6577e90b54de13353f34ff896fe1303d95; written by `beadloom docs site`, a change belongs in .beadloom/site/steiger.config.js
// The Feature-Sliced Design linter's configuration for the portal's theme.
//
// `npm run lint:fsd` runs Steiger, the official FSD linter, over
// `.vitepress/theme` with its recommended rule set. Exactly one rule is switched
// off, and the reason is written here, beside the switch, where a reader of the
// configuration sees it.
//
// `fsd/insignificant-slice` reports a slice only one other slice uses and asks
// for the two to be merged. Its premise is that a slice exists to be reused.
// This theme is cut for a different reason: each slice is a node of the
// project's graph, and pieces of work (beads) that touch disjoint nodes can run
// in parallel without editing one file. A feature that only the graph viewer
// widget uses is therefore the intended shape, and merging it back into the
// widget would rebuild the single module the cut took apart. Every other
// recommended rule stays on.

import { defineConfig } from "steiger";
import fsd from "@feature-sliced/steiger-plugin";

export default defineConfig([
  ...fsd.configs.recommended,
  {
    rules: {
      "fsd/insignificant-slice": "off",
    },
  },
]);
