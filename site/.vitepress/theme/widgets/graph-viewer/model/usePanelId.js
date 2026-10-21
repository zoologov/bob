// beadloom:generated version=9.0.0 sha256=11820414ca143234108944613ed16752788532c2ffea69f53903565d23f0de71; written by `beadloom docs site`, a change belongs in .beadloom/site/.vitepress/theme/widgets/graph-viewer/model/usePanelId.js
// The id of a viewer's panel, which its toolbar's "Panel" button controls.
//
// A constant id gave two viewers on one page one id, and the second button
// controlled the first panel. Vue's `useId` is unique within the app and the
// same on the server and in the browser, so it is called in the viewer's setup.

import { useId } from "vue";

/** The panel id of the viewer whose setup calls it. */
export function usePanelId() {
  return `bl-viewer-panel-${useId()}`;
}
