// beadloom:generated version=9.0.0 sha256=6869e41a8826e479426069adaccc84a161ff6b5d6f66acc5db0a98b65f19a465; written by `beadloom docs site`, a change belongs in .beadloom/site/.vitepress/theme/features/select-neighbourhood/model/options.js
// The choices of the neighbourhood controls, and how a depth reads.
//
// Depth is 1 to 5 steps, or "all". It is kept as a string because it lives in
// the URL; `depthLimit` turns it into the number of steps the walk takes, and
// reads anything it does not know as the nearest choice rather than failing.

/** The neighbourhood's neutral state: one step in both directions, the rest dimmed. */
export const NEIGHBOURHOOD_DEFAULTS = Object.freeze({ depth: "1", dir: "both", hide: false });

/** The largest depth offered as a number; beyond it the choice is "all". */
export const MAX_DEPTH = 5;

/** The value of the depth that has no limit. */
export const ALL_DEPTHS = "all";

/** The depths the control offers, as the URL writes them. */
export const DEPTH_CHOICES = Object.freeze([
  ...Array.from({ length: MAX_DEPTH }, (_, index) => String(index + 1)),
  ALL_DEPTHS,
]);

/** The directions the control offers: along the arrows, against them, or both. */
export const DIRECTION_CHOICES = Object.freeze([
  { value: "out", label: "outgoing" },
  { value: "in", label: "incoming" },
  { value: "both", label: "both" },
]);

/** The number of steps a depth value allows: Infinity for "all", else 1 to `MAX_DEPTH`. */
export function depthLimit(value) {
  if (value === ALL_DEPTHS) return Infinity;
  const steps = Number.parseInt(value, 10);
  if (!Number.isFinite(steps) || steps < 1) return 1;
  return Math.min(steps, MAX_DEPTH);
}
