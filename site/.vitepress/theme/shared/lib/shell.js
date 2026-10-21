// beadloom:generated version=9.0.0 sha256=a8d4569f07ca6365d3ab5576c320504136750399e40ac17fe587b62aa456116b; written by `beadloom docs site`, a change belongs in .beadloom/site/.vitepress/theme/shared/lib/shell.js
// A word quoted for a POSIX shell, so a command pasted into a terminal names what it shows.

/** The characters a shell reads as themselves in an unquoted word. */
const PLAIN_WORD = /^[A-Za-z0-9_\-./:@%+=,]+$/;

/**
 * `word` as the shell reads it back whole: unchanged when every character is
 * plain, otherwise in single quotes, with each `'` closed, escaped and reopened.
 */
export function shellQuote(word) {
  const text = String(word ?? "");
  if (PLAIN_WORD.test(text)) return text;
  return `'${text.replace(/'/g, "'\\''")}'`;
}
