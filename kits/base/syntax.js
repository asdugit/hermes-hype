// Auteur kits/base — a tiny per-line syntax tokenizer for CODE / DIFF panels.
// Returns [[cls, text], ...] with cls in: '' (plain), 'k' keyword, 's' string, 'c' comment,
// 'n' number, 'f' defined name, 'p' punctuation-ish operators. Themes colour these via .tk-* classes.

const KW = {
  python: 'and as assert async await break class continue def del elif else except False finally for from global if import in is lambda None nonlocal not or pass raise return True try while with yield match case self',
  js: 'async await break case catch class const continue debugger default delete do else export extends false finally for function from if import in instanceof let new null of return static super switch this throw true try typeof undefined var void while yield interface type enum implements readonly public private protected as',
  go: 'break case chan const continue default defer else fallthrough for func go goto if import interface map package range return select struct switch type var nil true false',
  rust: 'as async await break const continue crate else enum extern false fn for if impl in let loop match mod move mut pub ref return self Self static struct super trait true type unsafe use where while',
  sh: 'if then else elif fi for in do done while until case esac function return export local echo cd set unset source exit',
  c: 'auto break case char const continue default do double else enum extern float for goto if int long register return short signed sizeof static struct switch typedef union unsigned void volatile while class public private protected virtual namespace using template typename new delete true false nullptr bool include define',
  ruby: 'begin class def do else elsif end ensure false for if in module next nil not or redo rescue retry return self super then true undef unless until when while yield require',
  sql: 'select from where and or not insert into values update set delete create table index primary key foreign references join left right inner outer on group by order having limit as distinct null is in like',
};
const ALIAS = {
  py: 'python', python: 'python', python3: 'python', javascript: 'js', js: 'js', jsx: 'js', ts: 'js', tsx: 'js',
  typescript: 'js', mjs: 'js', json: 'js', go: 'go', golang: 'go', rust: 'rust', rs: 'rust', bash: 'sh', sh: 'sh',
  shell: 'sh', zsh: 'sh', powershell: 'sh', c: 'c', cpp: 'c', 'c++': 'c', java: 'c', csharp: 'c', cs: 'c', kotlin: 'c',
  swift: 'c', ruby: 'ruby', rb: 'ruby', sql: 'sql', toml: 'sh', yaml: 'sh', yml: 'sh', ini: 'sh', dockerfile: 'sh',
  makefile: 'sh', lua: 'sql', html: 'html', xml: 'html', svg: 'html', vue: 'html', css: 'css', scss: 'css',
};
const sets = {};
function kwSet(lang) {
  if (!sets[lang]) sets[lang] = new Set((KW[lang] || '').split(' '));
  return sets[lang];
}
function langOf(lang, path) {
  const l = String(lang || '').toLowerCase();
  if (ALIAS[l]) return ALIAS[l];
  const ext = String(path || '').split('.').pop().toLowerCase();
  return ALIAS[ext] || 'plain';
}

/** Tokenize one line of code. */
export function highlight(line, lang, path) {
  const L = langOf(lang, path);
  const s = String(line);
  if (L === 'html') return highlightMarkup(s);
  if (L === 'css') return highlightCss(s);
  if (L === 'plain') return [['', s]];
  const kws = kwSet(L);
  const hashComment = L === 'python' || L === 'sh' || L === 'ruby';
  const dashComment = L === 'sql';
  const out = [];
  let i = 0;
  let prevWord = '';
  const push = (c, t) => {
    if (!t) return;
    const last = out[out.length - 1];
    if (last && last[0] === c) last[1] += t; else out.push([c, t]);
  };
  while (i < s.length) {
    const ch = s[i];
    const rest = s.slice(i);
    if ((hashComment && ch === '#') || (!hashComment && rest.startsWith('//')) || (dashComment && rest.startsWith('--'))) {
      push('c', rest); break;
    }
    if (ch === '"' || ch === "'" || ch === '`') {
      let j = i + 1;
      while (j < s.length && s[j] !== ch) { if (s[j] === '\\') j++; j++; }
      // python prefixes like f"..." handled by the identifier branch leaving the quote here
      push('s', s.slice(i, j + 1)); i = j + 1; continue;
    }
    if (/[0-9]/.test(ch) && !/[A-Za-z_]/.test(s[i - 1] || '')) {
      const m = /^(0x[0-9a-fA-F_]+|[0-9][0-9_]*(\.[0-9_]+)?([eE][+-]?[0-9]+)?)/.exec(rest);
      if (m) { push('n', m[0]); i += m[0].length; continue; }
    }
    if (/[A-Za-z_$@]/.test(ch)) {
      const m = /^[A-Za-z_$@][A-Za-z0-9_$]*/.exec(rest);
      const w = m[0];
      let c = '';
      if (kws.has(w)) c = 'k';
      else if (['def', 'class', 'function', 'fn', 'func', 'struct', 'interface', 'type', 'enum'].includes(prevWord)) c = 'f';
      else if (L === 'python' && /^[frbu]{1,2}$/i.test(w) && /["']/.test(s[i + w.length] || '')) c = 's';
      push(c, w);
      prevWord = w;
      i += w.length;
      continue;
    }
    if (!/\s/.test(ch)) prevWord = prevWord && /[A-Za-z0-9_]/.test(ch) ? prevWord : (/[.:]/.test(ch) ? '' : prevWord);
    push('', ch);
    i++;
  }
  return out;
}

function highlightMarkup(s) {
  const out = [];
  const re = /(<!--.*?(-->|$))|(<\/?[A-Za-z][\w:-]*)|("[^"]*"|'[^']*')|(\/?>)/g;
  let last = 0, m;
  while ((m = re.exec(s))) {
    if (m.index > last) out.push(['', s.slice(last, m.index)]);
    out.push([m[1] ? 'c' : m[3] ? 'k' : m[4] ? 's' : 'k', m[0]]);
    last = m.index + m[0].length;
  }
  if (last < s.length) out.push(['', s.slice(last)]);
  return out;
}

function highlightCss(s) {
  const out = [];
  const re = /(\/\*.*?(\*\/|$))|("[^"]*"|'[^']*')|(#[0-9a-fA-F]{3,8}\b|-?\d+(\.\d+)?(px|em|rem|%|s|ms|deg|vh|vw)?)|([\w-]+(?=\s*:))/g;
  let last = 0, m;
  while ((m = re.exec(s))) {
    if (m.index > last) out.push(['', s.slice(last, m.index)]);
    out.push([m[1] ? 'c' : m[3] ? 's' : m[4] ? 'n' : 'k', m[0]]);
    last = m.index + m[0].length;
  }
  if (last < s.length) out.push(['', s.slice(last)]);
  return out;
}

/**
 * Soft-wrap a token line at `max` chars, preferring whitespace; never splits inside a word unless a
 * single word is longer than the line. Returns an array of token lines (display-only continuation).
 */
export function wrapTokens(tokens, max) {
  const flat = tokens.map(([c, t]) => t).join('');
  if (flat.length <= max || max < 8) return [tokens];
  // char -> class map
  const classes = [];
  for (const [c, t] of tokens) for (let k = 0; k < t.length; k++) classes.push(c);
  const indent = (/^\s*/.exec(flat)[0].length);
  const contIndent = Math.min(indent + 4, Math.floor(max / 3));
  const lines = [];
  let start = 0, first = true;
  while (start < flat.length) {
    const room = first ? max : max - contIndent;
    if (flat.length - start <= room) { lines.push([start, flat.length]); break; }
    let cut = flat.lastIndexOf(' ', start + room);
    if (cut <= start + Math.floor(room * 0.35)) cut = start + room; // one huge token: hard cut
    lines.push([start, cut]);
    start = cut;
    while (flat[start] === ' ') start++;
    first = false;
  }
  return lines.map(([a, b], li) => {
    const toks = [];
    if (li > 0) toks.push(['', ' '.repeat(contIndent)]);
    for (let k = a; k < b; k++) {
      const c = classes[k];
      const last = toks[toks.length - 1];
      if (last && last[0] === c && !(li > 0 && toks.length === 1)) last[1] += flat[k]; else toks.push([c, flat[k]]);
    }
    return toks;
  });
}
