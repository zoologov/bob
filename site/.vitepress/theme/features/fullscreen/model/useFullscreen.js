// beadloom:generated version=9.0.0 sha256=b26b7eda5e44a49952a438bdbe2262de679991a6edb7c35f3cc10f7f747018d4; written by `beadloom docs site`, a change belongs in .beadloom/site/.vitepress/theme/features/fullscreen/model/useFullscreen.js
// Full screen for one element, with a CSS fallback over the same element.
//
// The element is the viewer's whole space, so the toolbar, the canvas and the
// panel go full screen together. In an earlier version only the canvas and the
// card did, and the controls stayed behind in the page. When the Fullscreen API is
// missing or refuses, the same element is pinned over the viewport instead;
// `fallback` says which of the two is on.

import { onBeforeUnmount, onMounted, ref } from "vue";
import { isBrowser } from "../../../shared/lib/index.js";

/** `{ active, fallback, toggle, exit }` for the element `targetRef` holds. */
export function useFullscreen(targetRef, { onChange = () => {} } = {}) {
  const active = ref(false);
  const fallback = ref(false);

  function sync() {
    active.value = Boolean(document.fullscreenElement) || fallback.value;
    onChange(active.value);
  }

  function useFallback(on) {
    fallback.value = on;
    sync();
  }

  function exit() {
    if (fallback.value) return useFallback(false);
    if (document.fullscreenElement) document.exitFullscreen?.();
  }

  function toggle() {
    const target = targetRef.value;
    if (!target) return;
    if (active.value) return exit();
    if (!target.requestFullscreen) return useFallback(true);
    Promise.resolve()
      .then(() => target.requestFullscreen())
      .catch(() => useFallback(true));
  }

  onMounted(() => {
    if (isBrowser()) document.addEventListener("fullscreenchange", sync);
  });
  onBeforeUnmount(() => {
    if (isBrowser()) document.removeEventListener("fullscreenchange", sync);
  });

  return { active, fallback, toggle, exit };
}
