// Committed VitePress scaffold for the Bob showcase site.
//
// Beadloom produces, VitePress renders: `beadloom docs site --out site`
// regenerates the content tree (index.md, per-node pages, config.generated.mjs
// with nav/sidebar). This file is the stable shell that imports that generated
// nav/sidebar, enables Mermaid, and publishes the full architecture landing.
//
// Served as a GitHub *project page* at https://zoologov.github.io/bob/.
// Run `npm ci && npm run docs:build` to render (CI does this in deploy-site.yml).

import { withMermaid } from "vitepress-plugin-mermaid";

// The generated nav/sidebar. Regenerate with `beadloom docs site` before build.
let nav = [];
let sidebar = [];
try {
  const generated = await import("./config.generated.mjs");
  nav = generated.nav ?? [];
  sidebar = generated.sidebar ?? [];
} catch {
  // config.generated.mjs is produced by `beadloom docs site`; absent on a
  // fresh checkout before the first generation.
}

// The full multi-layer architecture landing (mermaid + click-zoom) shipped as a
// self-contained HTML asset in public/ — linked from the top nav.
const archLink = { text: "Схема архитектуры", link: "/bob-architecture.html", target: "_self" };

export default withMermaid({
  title: "Bob",
  description:
    "Автономный Telegram-компаньон со своей личностью: живая документация — архитектура, домены и весь Higher Mind.",
  base: "/bob/",
  lastUpdated: false,
  // The raw dev-docs mirror (docs/**) is Bob's Markdown, not written for Vue's
  // template compiler — bare `<` in prose trips it. The showcase value is the
  // per-node architecture pages + the landing, so the mirror is excluded and any
  // orphaned sidebar links tolerated.
  srcExclude: ["docs/**"],
  ignoreDeadLinks: true,
  themeConfig: {
    nav: [...nav, archLink],
    sidebar,
    socialLinks: [
      { icon: "github", link: "https://github.com/zoologov/bob" },
    ],
  },
  mermaid: {
    // Mermaid renderer options (C4 + flowchart render natively).
  },
});
