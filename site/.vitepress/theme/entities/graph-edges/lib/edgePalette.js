// beadloom:generated version=9.0.0 sha256=7e2e4563d58c3fb5f7120a3e3d3eeda0f14d7afadcc3e6ed88f11c5856f62c59; written by `beadloom docs site`, a change belongs in .beadloom/site/.vitepress/theme/entities/graph-edges/lib/edgePalette.js
// The colours each edge look is drawn in, from resolved theme tokens: at rest, followed, and outside a selection.
//
// A line at rest takes its kind's share of its tone over the background
// (`EDGE_STYLES`, `strength`): an import is a light neutral and a violation is
// the full danger colour. A followed line — under the pointer, or on a
// selection's walk — is drawn in its full tone. A line outside a selection is its
// rest colour faded towards the background at full opacity: edges bundled into
// one trunk are drawn along the same line, and see-through ones would add up
// there, ten at a seventh of full strength drawing the trunk at four fifths. A
// line behind the lines of the node under the pointer is faded the same way,
// less: it stays readable, and the lines in front stand out.
//
// Every value is a literal `rgb(...)` from `shared/theme-tokens`: Cytoscape and a
// canvas both draw it as it is, and the stylesheet and the layer over the canvas
// draw one edge in one colour.

import { mixRgb } from "../../../shared/theme-tokens/index.js";
import { EDGE_STYLES } from "../model/edgeKinds.js";

/** How visible a node or a line outside the selection stays when it is dimmed. */
export const DIMMED_SHARE = 0.14;
/** How visible a line behind the lines of the node under the pointer stays. */
export const BEHIND_SHARE = 0.4;

/** Each style key's colours for `tokens`: `{ [styleKey]: { rest, full, behind, dimmed } }`. */
export function edgePaletteOf(tokens) {
  return Object.fromEntries(
    Object.entries(EDGE_STYLES).map(([key, look]) => {
      const full = tokens[look.tone];
      const rest = mixRgb(full, tokens.bg, look.strength);
      return [key, { rest, full, behind: mixRgb(rest, tokens.bg, BEHIND_SHARE), dimmed: mixRgb(rest, tokens.bg, DIMMED_SHARE) }];
    })
  );
}
