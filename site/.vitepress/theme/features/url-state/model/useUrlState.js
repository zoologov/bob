// beadloom:generated version=9.0.0 sha256=ae03174907bc52d2c570428ab17d7d05fb92fd36a574558048bbd9a60ab6270c; written by `beadloom docs site`, a change belongs in .beadloom/site/.vitepress/theme/features/url-state/model/useUrlState.js
// A reactive view state that round-trips through the page's query string.
//
// The state is read from the URL once, when the viewer is set up, so a linked
// view opens as it was shared. Every change is written back with
// `history.replaceState`, which keeps the history VitePress stores in
// `history.state` and adds no entry per keystroke.

import { reactive, watch } from "vue";
import { isBrowser } from "../../../shared/lib/index.js";
import { readQuery, writeQuery } from "../lib/queryState.js";

/** A reactive object over `defaults`, initialised from and written back to the URL. */
export function useUrlState(defaults) {
  const initial = isBrowser() ? readQuery(window.location.search, defaults) : { ...defaults };
  const state = reactive(initial);

  if (isBrowser()) {
    watch(
      () => ({ ...state }),
      (current) => {
        const { pathname, search, hash } = window.location;
        const next = writeQuery(search, current, defaults);
        if (next !== search) {
          window.history.replaceState(window.history.state, "", `${pathname}${next}${hash}`);
        }
      }
    );
  }
  return state;
}
