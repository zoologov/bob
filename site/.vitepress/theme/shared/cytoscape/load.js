// beadloom:generated version=9.0.0 sha256=f052ee719df9ca5f63f66050b5697816506399775f9bdebd8290d2e558e91d2c; written by `beadloom docs site`, a change belongs in .beadloom/site/.vitepress/theme/shared/cytoscape/load.js
// Cytoscape.js, loaded in the browser only and once.
//
// Cytoscape touches the DOM at import time, so it is imported lazily: VitePress
// renders every page on the server first, where it cannot load. The layout is
// not Cytoscape's: ELK runs in a worker of its own (`shared/elk`).

let loading = null;

/** The `cytoscape` factory. */
export function loadCytoscape() {
  loading ||= import("cytoscape").then(({ default: cytoscape }) => cytoscape);
  return loading;
}
