// beadloom:generated version=9.0.0 sha256=585ecaff9210b1af3587344cd60b10db0e1d21368b6327b454747e55470954a7; written by `beadloom docs site`, a change belongs in .beadloom/site/.vitepress/theme/shared/elk/elk.worker.js
// The Web Worker ELK lays a graph out in, so the page's main thread stays free meanwhile.
//
// elkjs ships its layout engine as a worker script: loaded in a worker, it
// answers ELK's own messages (`register`, then `layout`) on the worker's
// `onmessage`. Importing it is the whole worker. Vite bundles this module as a
// worker of its own because `layOut.js` names it with
// `new Worker(new URL("./elk.worker.js", import.meta.url))`.

import "elkjs/lib/elk-worker.min.js";
