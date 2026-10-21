// beadloom:generated version=9.0.0 sha256=8656fa47632f9513ef0cc792b17e7d3e2b9c4a088e40a1b0911e9393a1b35634; written by `beadloom docs site`, a change belongs in .beadloom/site/.vitepress/theme/shared/lib/browser.js
// Whether the code runs in a browser, not in VitePress's server-side render.

/** True in a browser with a DOM; false during the server-side render. */
export function isBrowser() {
  return typeof window !== "undefined" && typeof document !== "undefined";
}
