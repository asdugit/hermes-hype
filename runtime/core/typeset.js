// Display typography for words a model or a README wrote (E5): captions and headline-like params lose inline
// markdown markers (`code`, **bold**, *em*) and get real dashes. Never applied to code, terminal or diff
// content: only whitelisted headline keys of non-code scenes and the caption track pass through here, and text
// that was inside backticks stays verbatim (its `--` is guarded against font ligatures that draw it as a dash).

const ZWNJ = '\u200c';
// headline-like params kits print as display type (never cmd/output/lines/hunks/cta/url/path/code)
const TEXT_KEYS = new Set(['title', 'tagline', 'label', 'one_liner', 'text', 'headline', 'kicker', 'subtitle', 'eyebrow',
  'caption', 'quote', 'line', 'heading', 'subhead', 'product', 'name', 'who', 'body', 'note']);
const CODE_SCENE = /(^|\/)(code|diff|terminal|term|shell|cli|repl|editor)([-_]|$)/i;

/** Guard a verbatim code span: hyphen runs must not ligate into a dash. */
const guard = (s) => s.replace(/-{2,}/g, (m) => m.split('').join(ZWNJ));

/** Typeset one display string (idempotent). */
export function typeset(input) {
  if (typeof input !== 'string' || !input) return input;
  const parts = input.split(/(`+[^`\n]+?`+)/);
  let out = '';
  for (const part of parts) {
    const m = /^(`+)([^`\n]+?)\1$/.exec(part);
    if (m) { out += guard(m[2]); continue; }
    let s = part;
    s = s.replace(/\*\*([^*\n]+?)\*\*/g, '$1');
    s = s.replace(/(^|[\s(])\*([^*\s][^*\n]*?)\*(?=[\s).,;:!?]|$)/g, '$1$2');
    s = s.replace(/`/g, '');
    // dashes: a spaced double/triple hyphen -> em dash, a spaced single hyphen -> en dash; '--flag' and
    // 'a-b' stay as typed (a hyphen run that is left is guarded so the font cannot ligate it into a dash)
    s = s.replace(/(^|\s)-{2,3}(?=\s|$)/g, '$1—');
    s = s.replace(/(\S) - (?=\S)/g, '$1 – ');
    s = s.replace(/\.\.\.(?!\.)/g, '…');
    s = guard(s);
    out += s;
  }
  return out.replace(/ {2,}/g, ' ');
}

/** Scene ids whose params are code-like (never typeset, even their labels keep hyphens as typed). */
export function isCodeScene(sceneId) {
  const name = String(sceneId || '').split('/').pop();
  return CODE_SCENE.test(name);
}

/** Copy of shot params with headline-like strings typeset (code scenes untouched except `label`). */
export function typesetParams(sceneId, p) {
  if (!p || typeof p !== 'object') return p;
  const code = isCodeScene(sceneId);
  const out = { ...p };
  for (const [k, v] of Object.entries(p)) {
    if (!TEXT_KEYS.has(k)) continue;
    if (code && k !== 'label') continue;
    if (typeof v === 'string') out[k] = code ? stripMarkers(v) : typeset(v);
  }
  return out;
}

/** Only drop markdown markers (labels over code scenes): no dash changes. */
export function stripMarkers(s) {
  if (typeof s !== 'string') return s;
  return s.replace(/`+([^`\n]+?)`+/g, (_, c) => guard(c)).replace(/\*\*([^*\n]+?)\*\*/g, '$1');
}
