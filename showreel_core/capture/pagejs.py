"""JavaScript run inside captured pages (via ``Runtime.evaluate``; not subject to the page's CSP).

Everything is namespaced under ``window.__srcap`` and returns JSON-able values. Elements found for
crops/interactions are marked with ``data-sr-cap="<n>"`` so Python can address them by selector.
"""
from __future__ import annotations

import json

HELPERS_JS = r"""(() => {
if (window.__srcap) return true;
const vis = (el) => {
  if (!el || !el.getBoundingClientRect) return false;
  const r = el.getBoundingClientRect();
  if (r.width < 4 || r.height < 4) return false;
  const cs = getComputedStyle(el);
  return cs.visibility !== 'hidden' && cs.display !== 'none' && parseFloat(cs.opacity || '1') >= 0.05;
};
const norm = (s) => (s || '').replace(/\s+/g, ' ').trim().toLowerCase();
const cls = (el) => (typeof el.className === 'string' ? el.className : (el.getAttribute && el.getAttribute('class')) || '');
const pageRect = (el) => { const r = el.getBoundingClientRect();
  return {x: r.left + scrollX, y: r.top + scrollY, w: r.width, h: r.height}; };
const solid = (c) => c && c !== 'transparent' && !/rgba\([^)]*,\s*0(\.0+)?\)$/.test(c);
const boxy = (el) => {
  const tag = el.tagName.toLowerCase();
  if (['article', 'li', 'figure', 'form', 'aside', 'dialog', 'fieldset', 'details', 'table', 'pre'].includes(tag)) return true;
  // BEM element classes (card__head, feature__icon) are parts of a card, not the card itself
  const blocks = cls(el).split(/\s+/).filter(c => c && !c.includes('__')).join(' ');
  if (/(^|[\s_-])(card|feature|tile|panel|box|item|widget|module|pricing|plan|step|benefit)s?([\s_-]|$)/i.test(blocks)) return true;
  const cs = getComputedStyle(el);
  const bg = cs.backgroundColor, pbg = el.parentElement ? getComputedStyle(el.parentElement).backgroundColor : '';
  if (solid(bg) && bg !== pbg) return true;
  if (cs.borderTopStyle !== 'none' && parseFloat(cs.borderTopWidth) > 0 && parseFloat(cs.borderLeftWidth) > 0) return true;
  if (cs.boxShadow && cs.boxShadow !== 'none') return true;
  return false;
};
const expand = (el, maxArea) => {
  if (boxy(el) && el.tagName.toLowerCase() !== 'li' && !/^H[1-6]$/.test(el.tagName)) return el;
  let cur = el;
  for (let i = 0; i < 8 && cur.parentElement && cur.parentElement !== document.body
       && cur.parentElement !== document.documentElement; i++) {
    const p = cur.parentElement, r = p.getBoundingClientRect();
    if (r.width * r.height > maxArea || r.height > innerHeight * 1.15) break;
    cur = p;
    if (boxy(cur)) return cur;
  }
  return el;
};
const REGION = 'section,article,aside,form,figure,fieldset,[role=region],[role=group],main > div';
const slugOf = (s) => norm(s).replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
const byText = (q) => {
  const nq = norm(q); if (!nq) return null;
  let best = null, bestScore = -1e9, n = 0;
  const offer = (el, score) => { if (el && vis(el) && score > bestScore) { best = el; bestScore = score; } };
  // a region NAMED by the query: aria-labelledby/aria-label, or a visually hidden (sr-only) heading inside it
  for (const el of document.querySelectorAll('[aria-labelledby],[aria-label]')) {
    const ids = (el.getAttribute('aria-labelledby') || '').split(/\s+/).filter(Boolean);
    const name = norm(ids.map(id => (document.getElementById(id) || {}).textContent || '').join(' ')
      || el.getAttribute('aria-label') || '');
    if (name === nq && !/^(BUTTON|A|INPUT|SPAN|SVG)$/i.test(el.tagName)) offer(el, 5);
  }
  for (const h of document.querySelectorAll('h1,h2,h3,h4,h5,h6,legend')) {
    if (norm(h.textContent) !== nq || vis(h)) continue;
    offer(h.closest(REGION), 4.5);
  }
  // a block whose id or class names the feature (section.stats, #pricing)
  const sl = slugOf(q);
  if (sl.length >= 3) {
    for (const el of document.querySelectorAll(`[id],[class]`)) {
      if (++n > 6000) break;
      const tokens = [el.id, ...cls(el).split(/\s+/)].map(x => (x || '').toLowerCase());
      if (tokens.includes(sl) && boxy(el)) offer(el, 2.5);
    }
  }
  n = 0;
  const tags = 'h1,h2,h3,h4,h5,h6,button,a,label,summary,th,dt,strong,b,p,li,span,div,figcaption,legend,td';
  const word = (t) => { for (let k = t.indexOf(nq); k >= 0; k = t.indexOf(nq, k + 1)) {
    if (!/[a-z0-9]/.test(t[k - 1] || ' ') && !/[a-z0-9]/.test(t[k + nq.length] || ' ')) return true; } return false; };
  for (const el of document.querySelectorAll(tags)) {
    if (++n > 6000) break;
    const raw = el.textContent || '';
    if (raw.length > 600 || !norm(raw).includes(nq) || !vis(el)) continue;
    const t = norm(el.innerText || raw);
    if (!t.includes(nq)) continue;
    const exact = t === nq ? 3 : (t.startsWith(nq) ? 1.5 : 0);
    const kind = /^H[1-6]$/.test(el.tagName) ? 2 : (['BUTTON', 'A', 'LABEL', 'SUMMARY', 'DT', 'TH', 'STRONG', 'B'].includes(el.tagName) ? 1 : 0);
    // the word inside a longer sentence ("your tasks and stats stay in this browser") is a mention, not the feature
    const mention = !exact && (t.length > nq.length * 3 + 24 || !word(t)) ? 1.5 : 0;
    const score = exact + kind - Math.min(2, t.length / 200) - mention;
    if (score > bestScore) { best = el; bestScore = score; }
  }
  return bestScore >= 0 ? best : null;
};
let counter = 0;
const mark = (el) => { if (!el.dataset.srCap) el.dataset.srCap = String(++counter); return `[data-sr-cap="${el.dataset.srCap}"]`; };
const find = (q) => {
  let el = null, how = '';
  if (q.selector) {
    try { el = [...document.querySelectorAll(q.selector)].find(vis) || null; how = 'selector'; } catch (e) { el = null; }
  }
  if (!el && (q.text || q.selector)) { el = byText(q.text || q.selector); how = 'text'; }
  if (!el) return null;
  const target = q.expand === false ? el : expand(el, innerWidth * innerHeight * 0.6);
  const label = ((el.innerText || el.getAttribute('aria-label') || '').trim().split('\n')[0] || '').slice(0, 80);
  return {selector: mark(target), how, label, expanded: target !== el, rect: pageRect(target)};
};
const features = (maxN) => {
  const vp = innerWidth * innerHeight, cards = [];
  for (const h of document.querySelectorAll('h2,h3,h4')) {
    if (!vis(h)) continue;
    const c = expand(h, vp * 0.4);
    if (c === h) continue;
    const r = c.getBoundingClientRect();
    if (r.width < 160 || r.height < 80 || r.width * r.height < vp * 0.012) continue;
    if (cards.some(x => x.contains(c) || c.contains(x))) continue;
    cards.push(c);
  }
  const sib = c => cards.some(x => x !== c && x.parentElement === c.parentElement) ? 1 : 0;
  cards.sort((a, b) => (sib(b) - sib(a)) || (a.getBoundingClientRect().top - b.getBoundingClientRect().top));
  return cards.slice(0, maxN).map(c => {
    const h = c.querySelector('h2,h3,h4');
    return {selector: mark(c), how: 'auto', label: ((h && h.innerText) || '').trim().slice(0, 80), expanded: true,
            rect: pageRect(c)};
  });
};
const toHex = (c) => {
  if (!c) return null;
  const cv = document.createElement('canvas'); cv.width = cv.height = 1;
  const g = cv.getContext('2d'); g.fillStyle = '#000'; g.fillStyle = c; g.fillRect(0, 0, 1, 1);
  const d = g.getImageData(0, 0, 1, 1).data;
  if (d[3] < 128) return null;
  return '#' + [d[0], d[1], d[2]].map(v => v.toString(16).padStart(2, '0')).join('');
};
const cta = () => {
  const els = [...document.querySelectorAll('a,button,[role=button],input[type=submit],input[type=button]')]
    .filter(e => vis(e) && e.getBoundingClientRect().top < innerHeight && e.getBoundingClientRect().width >= 60);
  let best = null, bestScore = -1;
  for (const e of els) {
    const bg = getComputedStyle(e).backgroundColor;
    if (!solid(bg)) continue;
    const m = bg.match(/\d+(\.\d+)?/g).map(Number), mx = Math.max(m[0], m[1], m[2]), mn = Math.min(m[0], m[1], m[2]);
    const sat = mx ? (mx - mn) / mx : 0;
    const score = sat + (/btn|button|cta|primary/i.test(cls(e)) ? 0.3 : 0);
    if (score > bestScore) { best = e; bestScore = score; }
  }
  return best;
};
const scroller = () => {
  const d = document.scrollingElement || document.documentElement;
  if (d.scrollHeight > innerHeight + 50) return d;
  let best = null, area = 0, n = 0;
  for (const el of document.querySelectorAll('body *')) {
    if (++n > 5000) break;
    if (el.scrollHeight <= el.clientHeight + 200) continue;
    if (!/(auto|scroll)/.test(getComputedStyle(el).overflowY)) continue;
    const r = el.getBoundingClientRect(), a = r.width * r.height;
    if (a > area && a > innerWidth * innerHeight * 0.3) { best = el; area = a; }
  }
  return best || d;
};
window.__srcap = {vis, norm, pageRect, boxy, expand, byText, find, features, mark, toHex, cta, solid, scroller};
return true;
})()"""


def call(fn: str, *args: object) -> str:
    """JS expression calling ``__srcap.<fn>(*args)`` after (re)installing the helpers."""
    a = ", ".join(json.dumps(x) for x in args)
    return f"({HELPERS_JS}, window.__srcap.{fn}({a}))"


META_JS = "(" + HELPERS_JS + r""", (() => {
const S = window.__srcap;
const theme = document.querySelector('meta[name="theme-color" i]:not([media]), meta[name="theme-color" i]');
const desc = document.querySelector('meta[name="description" i], meta[property="og:description" i]');
const link = [...document.querySelectorAll('a[href]')].find(S.vis);
const b = S.cta();
const sc = S.scroller();
const inner = sc !== (document.scrollingElement || document.documentElement);
const H = inner ? sc.scrollHeight : Math.max(document.documentElement.scrollHeight, document.body ? document.body.scrollHeight : 0);
const bodyBg = getComputedStyle(document.body || document.documentElement).backgroundColor;
const htmlBg = getComputedStyle(document.documentElement).backgroundColor;
return {title: document.title || '', lang: document.documentElement.lang || '',
        description: desc ? (desc.content || '').slice(0, 300) : '',
        theme_color: theme ? S.toHex(theme.content) : null,
        cta_color: b ? S.toHex(getComputedStyle(b).backgroundColor) : null,
        cta_text: b ? (b.innerText || b.value || '').trim().slice(0, 40) : '',
        cta_selector: b ? S.mark(b) : '',
        link_color: link ? S.toHex(getComputedStyle(link).color) : null,
        background: S.toHex(S.solid(bodyBg) ? bodyBg : htmlBg) || null,
        scroll_height: H, inner_scroller: inner ? S.mark(sc) : '', width: innerWidth, height: innerHeight, url: location.href,
        text_chars: (document.body && document.body.innerText || '').trim().length,
        media: [...document.querySelectorAll('img,canvas,svg,video')].filter(S.vis).length};
})())"""

BANNER_JS = r"""(async () => {
  const vis = (el) => { if (!el || !el.getBoundingClientRect) return false; const r = el.getBoundingClientRect();
    const cs = getComputedStyle(el); return r.width > 4 && r.height > 4 && cs.visibility !== 'hidden' && cs.display !== 'none'
      && parseFloat(cs.opacity || '1') > 0.05; };
  const CTX = /cookie|consent|gdpr|ccpa|tracking|datenschutz|privacy (settings|preferences)/i;
  const REJECT = /^(reject( all)?( cookies)?|decline( all)?|deny( all)?|refuse( all)?|(use |allow )?(only )?(strictly )?(necessary|essential)( cookies)?( only)?|continue without (accepting|agreeing))$/i;
  const ACCEPT = /^(accept( all)?( cookies)?|allow( all)?( cookies)?|(i )?agree|i accept|got it!?|ok(ay)?!?|i understand|understood|dismiss|close|continue|yes|sounds good|alright)$/i;
  const known = '#onetrust-banner-sdk,#onetrust-consent-sdk,#CybotCookiebotDialog,.cc-window,.cc-banner,#cookie-banner,#cookieBanner,#cookie-consent,#cookieConsent,.cookie-banner,.cookie-consent,.cookie-notice,#cookie-notice,[id*="cookie" i],[class*="cookie" i],[id*="consent" i],[class*="consent" i],[aria-label*="cookie" i],[role="dialog"],[role="alertdialog"]';
  const cands = [];
  for (const el of document.querySelectorAll(known + ',div,section,aside,footer,form')) {
    if (cands.length > 40) break;
    if (!vis(el)) continue;
    const txt = (el.innerText || '').slice(0, 3000);
    if (txt.length > 2500 || !CTX.test(txt)) continue;
    const pos = getComputedStyle(el).position;
    const inKnown = el.matches(known);
    if (!(inKnown || pos === 'fixed' || pos === 'sticky')) continue;
    if (cands.some(c => c.contains(el))) continue;
    for (let i = cands.length - 1; i >= 0; i--) if (el.contains(cands[i])) cands.splice(i, 1);
    cands.push(el);
  }
  const out = {found: cands.length, actions: []};
  const label = (b) => ((b.innerText || b.value || b.getAttribute('aria-label') || b.title || '').replace(/\s+/g, ' ').trim());
  for (const c of cands) {
    const btns = [...c.querySelectorAll('button,a,[role=button],input[type=button],input[type=submit]')].filter(vis);
    const pick = btns.find(b => REJECT.test(label(b))) || btns.find(b => ACCEPT.test(label(b)))
      || btns.find(b => /^(\u00d7|\u2715|x)$/i.test(label(b)) || /close|dismiss/i.test(b.getAttribute('aria-label') || ''));
    if (pick) {
      try { pick.click(); out.actions.push({action: 'click', text: label(pick).slice(0, 40)}); } catch (e) {}
    }
  }
  await new Promise(r => setTimeout(r, 400));
  for (const c of cands) {
    if (c.isConnected && vis(c)) {
      c.style.setProperty('display', 'none', 'important');
      out.actions.push({action: 'hide', text: (c.id || c.className || c.tagName).toString().slice(0, 40)});
    }
  }
  if (out.actions.some(a => a.action === 'hide')) {
    for (const e of [document.documentElement, document.body]) {
      if (e && getComputedStyle(e).overflowY === 'hidden') e.style.setProperty('overflow', 'auto', 'important');
    }
  }
  return out;
})()"""

PAGE_STATE_JS = r"""(() => {
  const vis = (el) => { if (!el) return false; const r = el.getBoundingClientRect(); return r.width > 4 && r.height > 4; };
  const overlay = document.querySelector('vite-error-overlay, #webpack-dev-server-client-overlay, nextjs-portal, '
    + '[data-nextjs-dialog-overlay], #__next-build-watcher, .error-overlay, #react-error-overlay');
  return {error_overlay: overlay && vis(overlay) ? overlay.tagName.toLowerCase() : '',
          text_chars: (document.body && document.body.innerText || '').trim().length,
          media: [...document.querySelectorAll('img,canvas,svg,video')].filter(vis).length};
})()"""

SCROLL_PASS_JS = r"""(async (maxH, pauseMs) => {
  const H = () => Math.max(document.documentElement.scrollHeight, document.body ? document.body.scrollHeight : 0);
  const sleep = (ms) => new Promise(r => setTimeout(r, ms));
  let y = 0;
  while (y < Math.min(H(), maxH)) { window.scrollTo(0, y); await sleep(pauseMs); y += Math.max(200, innerHeight * 0.8); }
  window.scrollTo(0, Math.min(H(), maxH)); await sleep(pauseMs);
  window.scrollTo(0, 0); await sleep(pauseMs);
  return {height: H(), width: Math.max(document.documentElement.clientWidth, innerWidth)};
})"""

FAVICON_JS = r"""(async () => {
  const links = [...document.querySelectorAll('link[rel~="icon" i], link[rel="apple-touch-icon" i], link[rel="shortcut icon" i]')];
  const size = (l) => { const s = (l.getAttribute('sizes') || '').split(/\s+/)[0]; const n = parseInt(s, 10);
    return /svg/i.test(l.type || l.href) ? 1000 : (isNaN(n) ? (/apple-touch/i.test(l.rel) ? 180 : 16) : n); };
  links.sort((a, b) => size(b) - size(a));
  const hrefs = links.map(l => l.href).filter(Boolean);
  hrefs.push(new URL('/favicon.ico', location.href).href);
  for (const href of hrefs.slice(0, 3)) {
    try {
      if (href.startsWith('data:')) return {href: 'data:', data: href};
      const r = await fetch(href, {cache: 'no-store'});
      if (!r.ok) continue;
      const b = await r.blob();
      if (!b.size || b.size > 524288) continue;
      const data = await new Promise(res => { const fr = new FileReader(); fr.onload = () => res(fr.result); fr.readAsDataURL(b); });
      return {href, type: b.type, data};
    } catch (e) {}
  }
  return null;
})()"""


def scroll_pass(max_h: int, pause_ms: int = 120) -> str:
    return f"{SCROLL_PASS_JS}({int(max_h)}, {int(pause_ms)})"


def rect_of(selector: str) -> str:
    """Page-coordinate rect + viewport-centre of the first match (None if gone or hidden)."""
    return (f"(() => {{ const el = document.querySelector({json.dumps(selector)}); if (!el) return null;"
            " const r = el.getBoundingClientRect(); if (r.width < 2 || r.height < 2) return null;"
            " return {x: r.left + scrollX, y: r.top + scrollY, w: r.width, h: r.height,"
            " cx: r.left + r.width / 2, cy: r.top + r.height / 2,"
            " text: ((el.innerText || el.value || el.getAttribute('aria-label') || '') + '').trim().slice(0, 120),"
            " doc_w: Math.max(document.documentElement.scrollWidth, innerWidth),"
            " doc_h: Math.max(document.documentElement.scrollHeight, document.body ? document.body.scrollHeight : 0),"
            " vw: innerWidth, vh: innerHeight}; })()")


def scroll_into_view(selector: str) -> str:
    return (f"(() => {{ const el = document.querySelector({json.dumps(selector)}); if (!el) return false;"
            " el.scrollIntoView({block: 'center', inline: 'nearest'}); return true; })()")


def scroll_to(y: float, fraction: bool) -> str:
    """Scroll the page - or its main inner scroll container (app shells) - to px ``y`` or a fraction."""
    target = f"Math.round({float(y)} * Math.max(0, s.scrollHeight - s.clientHeight))" if fraction else str(int(y))
    return f"({HELPERS_JS}, (() => {{ const s = window.__srcap.scroller(); s.scrollTop = {target}; return s.scrollTop; }})())"


def type_into(selector: str, text: str) -> str:
    return (f"(() => {{ const el = document.querySelector({json.dumps(selector)}); if (!el) return false;"
            " el.focus(); const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;"
            " const set = Object.getOwnPropertyDescriptor(proto, 'value'); if (set && set.set) set.set.call(el,"
            f" {json.dumps(text)}); else el.value = {json.dumps(text)};"
            " el.dispatchEvent(new Event('input', {bubbles: true})); el.dispatchEvent(new Event('change', {bubbles: true}));"
            " return true; })()")
