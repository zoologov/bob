// beadloom:generated version=9.0.0 sha256=754af8890eb734dd97d4ab47cddb9e7d99690173dc07a86a238a937be779f050; written by `beadloom docs site`, a change belongs in .beadloom/site/.vitepress/theme/shared/theme-tokens/useThemeTokens.js
// The resolved theme tokens as a ref that follows VitePress's light/dark switch.
//
// VitePress toggles the `dark` class on `<html>`. A mutation observer on that
// attribute re-resolves every token, so a canvas stylesheet built from the ref
// is rebuilt with the dark values rather than keeping the light ones.

import { onBeforeUnmount, onMounted, ref } from "vue";
import { isBrowser } from "../lib/index.js";
import { resolveTokens } from "./resolve.js";

/** `{ tokens }`: null until mounted, then the tokens resolved under `scopeRef`. */
export function useThemeTokens(scopeRef) {
  const tokens = ref(null);
  let observer = null;

  function refresh() {
    const scope = scopeRef.value || (isBrowser() ? document.documentElement : null);
    if (scope) tokens.value = resolveTokens(scope);
  }

  onMounted(() => {
    if (!isBrowser()) return;
    refresh();
    observer = new MutationObserver(refresh);
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
  });

  onBeforeUnmount(() => {
    observer?.disconnect();
    observer = null;
  });

  return { tokens, refresh };
}
