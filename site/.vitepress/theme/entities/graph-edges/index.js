// beadloom:generated version=9.0.0 sha256=e3bf77e6d45696331280f94a471c01fd36c8d1637c2664f455c89dca6d9b8373; written by `beadloom docs site`, a change belongs in .beadloom/site/.vitepress/theme/entities/graph-edges/index.js
// Public API of the `graph-edges` entity.

export {
  CONTAINMENT_KIND,
  DOT_PATTERN,
  DRAWN_KINDS,
  EDGE_STYLES,
  SEVERAL_KINDS,
  VIOLATION_KEY,
  contractStyleKey,
  dashOf,
  isDrawnKind,
  isViolation,
  legendKeysOf,
  styleKeyOf,
} from "./model/edgeKinds.js";
export {
  DEPENDENCY_KINDS,
  DEPENDENT_ENDS,
  NEIGHBOURHOOD_KINDS,
  adjacencyOf,
  dependentsOf,
  edgeGroupsOf,
  edgeKeyOf,
} from "./model/adjacency.js";
export { boxEdgesOf } from "./model/boxEdges.js";
export { DIMMED_SHARE, edgePaletteOf } from "./lib/edgePalette.js";
export {
  HEAD_ROOM,
  NO_SOURCE_HEAD,
  NO_TARGET_HEAD,
  SAME_END,
  crowdedHeadsOf,
  departuresBeside,
  droppedHeadsOf,
  headEndsOf,
  headRoomsOf,
} from "./lib/heads.js";
export {
  LINE_MARKS,
  arrowScaleOf,
  cornerRadiiOf,
  dashOffsetOf,
  dashOnScreen,
  edgeCornerRadiiOf,
  endHeadLength,
  headLengthOf,
  lineWidthOf,
  routePointsOf,
} from "./lib/lineMarks.js";
export { default as EdgeLegend } from "./ui/EdgeLegend.vue";
