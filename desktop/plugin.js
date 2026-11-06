/**
 * Showreel — the Hermes Desktop half of the `showreel` plugin.
 *
 *   Pane + page   one studio, two sizes: a right-side pane ("Showreel") and a full page at /showreel with a
 *                 sidebar entry. Tabs:
 *                   Make        mode (Trailer · Lore · Speedrun), style gallery with looping previews, length,
 *                               aspect, narration, effort, and a free-text Direction box (-> Directed film)
 *                   Live        the running film: stage list, progress, ETA, cancel; for Directed films the
 *                               Director's live log (treatment, scenes being coded, keyframe contact sheets,
 *                               critic scores per round) — "watch the Director work"
 *                   Storyboard  scene cards: thumbnail, editable narration and label, drop, drag to reorder,
 *                               re-render without a model call
 *                   Result      the core video player (MessageTextContent + MEDIA:), Reveal file, Render the
 *                               other aspect, Revise with notes, Copy post text
 *                   Library     scenes and worlds the Director saved, reusable by name
 *   Palette       "Showreel: make a trailer / the lore / a speedrun of this chat", "Showreel: open the studio"
 *   Status bar    a chip with the active render's progress (click: open the studio)
 *   Tool media    a card around the core player for showreel_render / showreel_status results (Hermes >= 0.22.6)
 *
 * Data comes from this plugin's own backend (dashboard/plugin_api.py, reached with ctx.rest) and the
 * `plugin.showreel.job.progress` event; every live view also polls, so it keeps working where events do
 * not arrive. Imports: the SDK (namespace import, optional exports feature-detected), react and
 * react/jsx-runtime only. Colours come from the app theme's variables only.
 */
import * as sdk from '@hermes/plugin-sdk'
import { Fragment, jsx, jsxs } from 'react/jsx-runtime'
import { useEffect, useMemo, useRef, useState } from 'react'

const ID = 'showreel'
const ROUTE = '/showreel'
const PROGRESS_EVENT = 'plugin.showreel.job.progress'
const TERMINAL = new Set(['done', 'failed', 'cancelled'])
const STAGES = ['reading', 'storyboard', 'voice', 'layout', 'render', 'mix', 'qa']
const TABS = [
  { id: 'make', label: 'Make', icon: 'wand' },
  { id: 'live', label: 'Live', icon: 'pulse' },
  { id: 'board', label: 'Storyboard', icon: 'list-ordered' },
  { id: 'result', label: 'Result', icon: 'play-circle' },
  { id: 'library', label: 'Library', icon: 'library' }
]
const MODES = [
  { id: 'product', label: 'Trailer', hint: 'A launch trailer: the product is the hero, the session is the proof.' },
  { id: 'making_of', label: 'Lore', hint: 'The making-of: how it got built, told by the session itself.' },
  { id: 'speedrun', label: 'Speedrun', hint: 'The build as a speedrun: live split timer, real timestamps, a PB card.' }
]
const LENGTHS = [{ id: '30', label: '30 s' }, { id: '60', label: '60 s' }, { id: '90', label: '90 s' }]
const ASPECTS = [{ id: '16:9', label: '16:9' }, { id: '9:16', label: '9:16' }, { id: 'both', label: 'Both' }]
const EFFORTS = [{ id: 'quick', label: 'Quick' }, { id: 'standard', label: 'Standard' }, { id: 'max', label: 'Max' }]
const EFFORT_HINT = {
  quick: 'One critique round. About 15 minutes.',
  standard: 'Two critique rounds. About 25 minutes.',
  max: 'Four critique rounds. 40 minutes or more.'
}
// Shown when the backend is not reachable yet (and as the roster order the backend also follows).
const FALLBACK_STYLES = [
  { id: 'launch', name: 'Launch', blurb: 'Premium product-launch motion graphics' },
  { id: 'cinematic', name: 'Cinematic', blurb: 'Captures as lit cards in dark 3D space' },
  { id: 'pixel', name: 'Pixel', blurb: '16-bit arcade: pixel art, chiptune, quest log' },
  { id: 'terminal', name: 'Terminal', blurb: 'Phosphor CRT terminal with scanlines' },
  { id: 'blueprint', name: 'Blueprint', blurb: 'Engineering drawing, line art drawn on' }
]
const DIRECTION_EXAMPLES = [
  'pixel but transition into a different style mid way through, goal is to sell the product',
  'a slow cinematic teaser that ends on the dashboard, no narration in the first ten seconds',
  'make it feel like a late-night infomercial for developers'
]
const RAIL = [
  { id: 'setup', label: 'Brief' },
  { id: 'treatment', label: 'Treatment' },
  { id: 'film', label: 'Script' },
  { id: 'scenes', label: 'Scene code' },
  { id: 'dryrun', label: 'Dry run' },
  { id: 'critic', label: 'Critic' },
  { id: 'revise', label: 'Revise' },
  { id: 'final', label: 'Final cut' }
]
const RAIL_OF = { 'revise-film': 'revise', 'revise-scenes': 'revise', done: 'final', library: 'final' }
const RUBRIC_LABEL = {
  product_clarity: 'Product clarity',
  composition: 'Composition',
  beauty_craft: 'Beauty / craft',
  story_clarity: 'Story clarity',
  legibility: 'Legibility',
  style_coherence: 'Style coherence',
  transition_quality: 'Transitions'
}

// ── module state (reset on unload) ─────────────────────────────────────────────────────────────────
let CTX = null
const notified = new Set()
const seenRunning = new Set()
const throttles = new Map()

function makeAtom(value) {
  if (typeof sdk.atom === 'function') return sdk.atom(value)
  let v = value
  const subs = new Set()
  return { get: () => v, set: n => { v = n; subs.forEach(f => f(v)) }, listen: f => { subs.add(f); return () => subs.delete(f) } }
}

// The studio's shared UI state: the job picked per chat, a tab request (palette, chip, library), a
// Direction prefill (library "use in a film").
const $ui = makeAtom({ selected: {}, tabRequest: null, prefill: '' })
const patchUi = patch => $ui.set({ ...$ui.get(), ...patch })
const selectJob = (sid, jobId) => patchUi({ selected: { ...$ui.get().selected, [sid || '_']: jobId } })
// A tab request is one-shot: a studio mounted seconds later (the page the palette navigates to) still takes
// it, a studio opened minutes later does not replay it.
const requestTab = tab => patchUi({ tabRequest: { tab, n: Math.random(), at: Date.now() } })

function useAtomLocal(a) {
  const [v, setV] = useState(() => a.get())
  useEffect(() => {
    setV(a.get())
    return a.listen(() => setV(a.get()))
  }, [a])
  return v
}
// The SDK's useValue when present (it is the same store type host.state uses); a local subscription otherwise.
const useAtomValue = typeof sdk.useValue === 'function' ? a => sdk.useValue(a) : useAtomLocal

// ── backend ────────────────────────────────────────────────────────────────────────────────────────
const SRC = () => (CTX && CTX.source) || `plugin:${ID}`
const qk = (...parts) => [SRC(), ...parts]
const enc = encodeURIComponent

/** An error from ctx.rest as {status, message, body}: the host throws "<status>: <body>". */
function parseError(err) {
  const raw = String((err && err.message) || err || 'request failed')
  let status = Number(err && err.statusCode) || 0
  const m = raw.match(/\b([1-5]\d\d):\s/)
  if (!status && m) status = Number(m[1])
  let body = null
  const at = raw.indexOf('{')
  if (at >= 0) {
    try {
      body = JSON.parse(raw.slice(at))
    } catch (e) {
      body = null
    }
  }
  const detail = body && (body.error || (typeof body.detail === 'string' ? body.detail : ''))
  const message = detail || raw.replace(/^[\s\S]*?\b[1-5]\d\d:\s*/, '') || raw
  return { status, body, message }
}

async function api(path, opts) {
  if (!CTX) throw new Error('Showreel is not loaded')
  try {
    return await CTX.rest(path, opts)
  } catch (err) {
    const e = parseError(err)
    throw Object.assign(new Error(e.message), e)
  }
}

function useApi(key, path, { enabled = true, refetchInterval = false, staleTime = 0 } = {}) {
  return sdk.useQuery({ queryKey: key, queryFn: () => api(path), enabled: Boolean(enabled && path), refetchInterval, staleTime, retry: 1 })
}

/** React Query passes (query) in v5 and (data, query) in v4: read the data either way. */
const dataOf = (a, b) => (a && a.state ? a.state.data : b && b.state ? b.state.data : a)

function invalidate(...parts) {
  try {
    sdk.queryClient && sdk.queryClient.invalidateQueries({ queryKey: qk(...parts) })
  } catch (e) {
    console.warn('[showreel] invalidate failed', e)
  }
}

function throttled(key, ms, fn) {
  if (throttles.has(key) || !CTX) return
  throttles.set(key, true)
  CTX.setTimeout(() => {
    throttles.delete(key)
    fn()
  }, ms)
}

function notify(kind, message) {
  try {
    sdk.host && sdk.host.notify && sdk.host.notify({ kind, message })
  } catch (e) {
    console.warn('[showreel]', message, e)
  }
}

async function copyText(text) {
  try {
    if (CTX && CTX.os && CTX.os.writeClipboard && (await CTX.os.writeClipboard(text))) return true
  } catch (e) {
    console.warn('[showreel] clipboard door failed', e)
  }
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch (e) {
    return false
  }
}

async function reveal(path) {
  try {
    if (CTX && CTX.os && CTX.os.revealPath && (await CTX.os.revealPath(path))) return
  } catch (e) {
    console.warn('[showreel] reveal failed', e)
  }
  notify('warning', `Could not open the folder. The file is at ${path}`)
}

function navigate(path) {
  try {
    sdk.host && sdk.host.navigate && sdk.host.navigate(path)
  } catch (e) {
    console.warn('[showreel] navigate failed', e)
  }
}

/** Track jobs seen running; a job that was seen running and is now finished is announced once. Jobs that
 *  finished before the studio or the chip ever saw them run (an old failure when the pane opens) are not. */
function observe(job) {
  if (!job || !job.id) return
  if (isRunning(job)) {
    seenRunning.add(job.id)
  } else if (TERMINAL.has(job.stage) && seenRunning.has(job.id)) {
    seenRunning.delete(job.id)
    announce(job)
  }
}

/** Tell the user once when a film is ready (native notification only fires while Hermes is in the background). */
function announce(job) {
  if (!job || !job.id || notified.has(job.id) || !TERMINAL.has(job.stage)) return
  notified.add(job.id)
  const title = job.title || 'Your showreel'
  if (job.stage === 'done') {
    try {
      CTX && CTX.os && CTX.os.notify && CTX.os.notify({ title: 'Showreel ready', body: `${title} finished rendering.`, activate: ROUTE })
    } catch (e) {
      console.warn('[showreel] os notify failed', e)
    }
  } else if (job.stage === 'failed') {
    notify('error', `Showreel failed: ${job.error && job.error.message ? job.error.message : job.error || title}`)
  }
}

function onProgress(event) {
  const p = (event && event.payload) || {}
  if (!p.id) return
  try {
    sdk.queryClient && sdk.queryClient.setQueryData(qk('job', p.id), old =>
      old ? { ...old, stage: p.stage || old.stage, pct: p.pct ?? old.pct, eta_s: p.eta_s, note: p.note ?? old.note, updated: Date.now() / 1000 } : old)
  } catch (e) {
    console.warn('[showreel] progress patch failed', e)
  }
  throttled('lists', 1200, () => { invalidate('jobs'); invalidate('active') })
  if (TERMINAL.has(p.stage)) {
    invalidate('job', p.id)
    invalidate('thumbs', p.id)
  }
  observe(p)
}

// ── small helpers ──────────────────────────────────────────────────────────────────────────────────
const cx = (...c) => c.filter(Boolean).join(' ')
const isRunning = job => Boolean(job && job.stage && !TERMINAL.has(job.stage) && job.stage !== 'none')
const isDirected = job => Boolean(job && (job.kind === 'directed' || (job.options && String(job.options.direction || '').trim())))
const pctText = v => `${Math.round(Math.max(0, Math.min(1, Number(v) || 0)) * 100)}%`
const words = s => String(s || '').trim().split(/\s+/).filter(Boolean).length
const mediaLine = path => (/\s/.test(path) && !path.includes('`') ? `MEDIA:\`${path}\`` : `MEDIA:${path}`)
const modeLabel = m => (MODES.find(x => x.id === m) || MODES[0]).label

function fmtDur(s) {
  const n = Math.max(0, Math.round(Number(s) || 0))
  if (n < 60) return `${n} s`
  const m = Math.floor(n / 60)
  if (m < 60) return `${m} min ${String(n % 60).padStart(2, '0')} s`
  return `${Math.floor(m / 60)} h ${m % 60} min`
}

function fmtEta(s) {
  if (s == null || !isFinite(s)) return ''
  const n = Math.max(0, Math.round(s))
  if (n < 45) return 'under a minute left'
  if (n < 90) return 'about a minute left'
  if (n < 3600) return `about ${Math.round(n / 60)} min left`
  return `about ${Math.round(n / 360) / 10} h left`
}

function fmtAgo(ts, now) {
  if (!ts) return ''
  const d = Math.max(0, now / 1000 - Number(ts))
  if (d < 60) return 'just now'
  if (d < 3600) return `${Math.round(d / 60)} min ago`
  if (d < 86400) return `${Math.round(d / 3600)} h ago`
  return `${Math.round(d / 86400)} d ago`
}

const fmtTokens = n => (n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${Math.round(n / 1e3)}k` : String(n || 0))
const clock = t => {
  const n = Math.max(0, Math.round(Number(t) || 0))
  return `${Math.floor(n / 60)}:${String(n % 60).padStart(2, '0')}`
}

function storageGet(key, fallback) {
  try {
    const v = CTX && CTX.storage ? CTX.storage.get(key, fallback) : fallback
    return v === undefined || v === null ? fallback : v
  } catch (e) {
    return fallback
  }
}

function storageSet(key, value) {
  try {
    CTX && CTX.storage && CTX.storage.set(key, value)
  } catch (e) {
    console.warn('[showreel] storage write failed', e)
  }
}

/** A clock that ticks only while `active` (ctx.setInterval: cleared with the plugin). */
function useNow(ms, active) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!active || !CTX) return undefined
    setNow(Date.now())
    return CTX.setInterval(() => setNow(Date.now()), ms)
  }, [ms, active])
  return now
}

function useSessionId() {
  const st = (sdk.host && sdk.host.state) || {}
  const a = st.focusedStoredSessionId || st.activeSessionId
  const v = a ? useAtomValue(a) : null
  return v || null
}

// ── UI kit wrappers (the app's components when present, plain elements otherwise) ────────────────────
function Icon({ name, spin }) {
  if (!sdk.Codicon || !name) return null
  return jsx(sdk.Codicon, { name, spinning: spin || undefined, 'aria-hidden': true })
}

function withTip(label, el) {
  if (!label || !sdk.Tip) return el
  return jsx(sdk.Tip, { label, children: jsx('span', { className: 'srl-tipwrap', children: el }) })
}

function Btn({ variant = 'secondary', size = 'sm', icon, children, onClick, disabled, busy, tip, label }) {
  const inner = [icon ? jsx(Icon, { name: busy ? 'loading' : icon, spin: busy }, 'i') : null, children ? jsx('span', { children }, 't') : null]
  const props = { type: 'button', disabled: Boolean(disabled || busy), onClick, 'aria-label': label || undefined, 'aria-busy': busy || undefined }
  const el = sdk.Button
    ? jsx(sdk.Button, { ...props, variant, size, children: inner })
    : jsx('button', { ...props, className: cx('srl-btn', `srl-btn-${variant}`), children: inner })
  return withTip(tip, el)
}

function Seg({ options, value, onChange, disabled, label }) {
  const control = sdk.SegmentedControl
    ? jsx(sdk.SegmentedControl, { options, value, onChange, disabled, sizing: 'content' })
    : jsx('div', {
        className: 'srl-seg',
        children: options.map(o => jsx('button', {
          type: 'button', role: 'radio', 'aria-checked': o.id === value, className: 'srl-seg-opt', disabled,
          onClick: () => onChange(o.id), children: o.label
        }, o.id))
      })
  return jsx('div', { role: 'radiogroup', 'aria-label': label, className: 'srl-segwrap', children: control })
}

function Toggle({ checked, onChange, label }) {
  if (sdk.Switch) return jsx(sdk.Switch, { checked, onCheckedChange: v => onChange(Boolean(v)), 'aria-label': label })
  return jsx('input', { type: 'checkbox', checked, onChange: e => onChange(e.target.checked), 'aria-label': label })
}

function TextArea(props) {
  return sdk.Textarea ? jsx(sdk.Textarea, props) : jsx('textarea', { ...props, className: cx('srl-input', props.className) })
}

function TextInput(props) {
  return sdk.Input ? jsx(sdk.Input, props) : jsx('input', { ...props, className: cx('srl-input', props.className) })
}

function Spinner() {
  return jsx('i', { className: 'srl-spin', 'aria-hidden': true })
}

function Empty({ icon, title, children }) {
  return jsxs('div', {
    className: 'srl-empty',
    children: [
      icon ? jsx('div', { className: 'srl-empty-icon', children: jsx(Icon, { name: icon }) }) : null,
      jsx('div', { className: 'srl-empty-title', children: title }),
      children ? jsx('div', { className: 'srl-empty-body', children }) : null
    ]
  })
}

function Alert({ tone = 'warn', children }) {
  return jsx('div', { className: 'srl-alert', 'data-tone': tone, role: tone === 'error' ? 'alert' : 'status', children })
}

function Section({ label, aside, children, className }) {
  return jsxs('section', {
    className: cx('srl-section', className),
    children: [
      label ? jsxs('div', { className: 'srl-label', children: [jsx('span', { children: label }), aside ? jsx('span', { className: 'srl-label-aside', children: aside }) : null] }) : null,
      children
    ]
  })
}

// ── style previews ─────────────────────────────────────────────────────────────────────────────────
const PH_ROT = { launch: 0, cinematic: 170, pixel: 290, terminal: 130, blueprint: 225, comic: 25, ink: 0, nature: 95 }

/** A drawn stand-in for a style whose looping preview has not been generated yet (theme colours only). */
function StylePlaceholder({ id, name }) {
  const kind = PH_ROT[id] !== undefined ? id : 'other'
  const style = { '--rot': String(PH_ROT[id] ?? (Math.abs([...String(id)].reduce((a, c) => (a * 31 + c.charCodeAt(0)) % 3600, 7)) % 360)) }
  const parts = {
    launch: [jsx('i', { className: 'p a' }, 'a'), jsx('i', { className: 'p b' }, 'b'), jsx('i', { className: 'shine' }, 's')],
    cinematic: [jsx('i', { className: 'bokeh' }, 'k'), jsx('i', { className: 'c c1' }, '1'), jsx('i', { className: 'c c2' }, '2'), jsx('i', { className: 'c c3' }, '3'), jsx('i', { className: 'lb t' }, 't'), jsx('i', { className: 'lb b' }, 'b')],
    pixel: [jsx('i', { className: 'stars' }, 's'), jsx('i', { className: 'ground' }, 'g'), jsx('i', { className: 'hero' }, 'h'), jsx('i', { className: 'hp' }, 'p')],
    terminal: [jsxs('div', { className: 'tx', children: [jsx('div', { children: '$ /showreel terminal' }), jsx('div', { className: 'ok', children: '✓ 41 tests passed' }), jsxs('div', { children: ['> rendering', jsx('b', { className: 'cur' })] })] }, 't'), jsx('i', { className: 'scan' }, 's')],
    blueprint: [jsx('svg', { viewBox: '0 0 160 90', 'aria-hidden': true, children: [
      jsx('rect', { x: 46, y: 18, width: 68, height: 46, rx: 4 }, 'r'),
      jsx('circle', { cx: 80, cy: 41, r: 11 }, 'c'),
      jsx('path', { d: 'M46 74 H114 M46 70 V78 M114 70 V78 M124 18 V64 M120 18 H128 M120 64 H128' }, 'd'),
      jsx('path', { className: 'arc', d: 'M30 60 Q 40 20 70 14' }, 'a')
    ] }, 'svg')],
    comic: [jsx('i', { className: 'panel' }, 'p'), jsx('b', { className: 'burst', children: 'POW!' }, 'b')],
    ink: [jsx('svg', { viewBox: '0 0 160 90', 'aria-hidden': true, children: [
      jsx('path', { className: 'enso', d: 'M98 22 C 70 8 44 26 46 48 C 48 70 82 78 100 62 C 112 50 110 36 104 30' }, 'e'),
      jsx('rect', { className: 'seal', x: 118, y: 58, width: 12, height: 14, rx: 1.5 }, 's')
    ] }, 'svg')],
    nature: [jsx('svg', { viewBox: '0 0 160 90', preserveAspectRatio: 'none', 'aria-hidden': true, children: [
      jsx('circle', { className: 'sun', cx: 112, cy: 36, r: 10 }, 's'),
      jsx('path', { className: 'h1', d: 'M0 58 Q 30 40 62 52 T 120 46 T 160 50 V90 H0Z' }, 'a'),
      jsx('path', { className: 'h2', d: 'M0 70 Q 40 58 80 68 T 160 64 V90 H0Z' }, 'b')
    ] }, 'svg'), jsx('i', { className: 'petal p1' }, '1'), jsx('i', { className: 'petal p2' }, '2'), jsx('i', { className: 'petal p3' }, '3')],
    other: [jsx('b', { className: 'word', children: name || id }, 'w')]
  }
  return jsx('div', { className: cx('srl-ph', `srl-ph-${kind}`), style, 'aria-hidden': true, children: parts[kind] })
}

function StylePreview({ style }) {
  const [failed, setFailed] = useState(false)
  const lazy = style.has_preview && !style.preview_url && !failed
  const q = useApi(qk('preview', style.id), `/styles/${enc(style.id)}/preview`, { enabled: lazy, staleTime: Infinity })
  const url = style.preview_url || (q.data && q.data.url) || ''
  const kind = style.preview_url ? 'image' : (q.data && q.data.kind) || style.preview_kind
  // The drawn placeholder stays underneath; the real preview fades in over it once it has a frame, so a
  // preview that is still decoding (or never does) is never an empty or broken box.
  const [shown, setShown] = useState(false)
  const media = url && !failed
    ? kind === 'video'
      ? jsx('video', { src: url, autoPlay: true, muted: true, loop: true, playsInline: true, 'data-shown': shown ? '1' : undefined, onLoadedData: () => setShown(true), onError: () => setFailed(true) }, 'm')
      : jsx('img', { src: url, alt: '', loading: 'lazy', 'data-shown': shown ? '1' : undefined, onLoad: () => setShown(true), onError: () => setFailed(true) }, 'm')
    : null
  return jsxs(Fragment, { children: [jsx(StylePlaceholder, { id: style.id, name: style.name }, 'ph'), media] })
}

function StyleCard({ style, selected, onSelect }) {
  return jsxs('button', {
    type: 'button',
    className: 'srl-card',
    'aria-pressed': selected,
    onClick: () => onSelect(style.id),
    children: [
      jsxs('div', { className: 'srl-card-media', children: [jsx(StylePreview, { style }), selected ? jsx('span', { className: 'srl-card-check', children: jsx(Icon, { name: 'check' }) }) : null] }),
      jsxs('div', {
        className: 'srl-card-meta',
        children: [
          jsxs('div', { className: 'srl-card-name', children: [style.name || style.id, style.ready === false ? jsx('span', { className: 'srl-soon', children: 'soon' }) : null] }),
          jsx('div', { className: 'srl-card-blurb', children: style.ready === false ? `${style.blurb || ''} (renders as Launch for now)` : style.blurb })
        ]
      })
    ]
  })
}

// ── Make ───────────────────────────────────────────────────────────────────────────────────────────
const DEFAULT_PREFS = { mode: 'product', style: 'launch', seconds: '60', aspect: '16:9', voice: true, effort: 'standard' }

function loadPrefs() {
  const p = storageGet('make', null)
  return { ...DEFAULT_PREFS, ...(p && typeof p === 'object' ? p : {}) }
}

function optionsFrom(prefs, direction) {
  const aspects = prefs.aspect === 'both' ? ['16:9', '9:16'] : [prefs.aspect]
  return {
    mode: prefs.mode, style: prefs.style, seconds: Number(prefs.seconds) || 60, aspects, voice: Boolean(prefs.voice),
    effort: prefs.effort, direction: String(direction || '').trim(),
    explicit: ['mode', 'style', 'seconds', 'aspects', 'voice'].concat(String(direction || '').trim() ? ['effort'] : [])
  }
}

/** Start a film for a chat; resolves the new job, or null (the user was told why). */
async function startFilm(sid, options) {
  if (!sid) {
    notify('warning', 'Open a chat first: Showreel films the chat you are looking at.')
    return null
  }
  try {
    const job = await api('/jobs', { method: 'POST', body: { session_id: sid, options } })
    selectJob(sid, job.id)
    invalidate('jobs')
    invalidate('active')
    return job
  } catch (e) {
    if (e.status === 409 && e.body && e.body.job) {
      selectJob(sid, e.body.job.id)
      requestTab('live')
      notify('info', 'A showreel is already rendering for this chat.')
    } else {
      notify('error', `Could not start the showreel: ${e.message}`)
    }
    return null
  }
}

function MakeView({ sid, jobs, backendDown, onStarted }) {
  const [prefs, setPrefs] = useState(loadPrefs)
  const [direction, setDirection] = useState(() => String(storageGet('direction', '') || ''))
  const [busy, setBusy] = useState(false)
  const ui = useAtomValue($ui)
  const stylesQ = useApi(qk('styles'), '/styles', { staleTime: 300000 })
  const styles = (stylesQ.data && stylesQ.data.styles && stylesQ.data.styles.length ? stylesQ.data.styles : FALLBACK_STYLES)
  const running = (jobs || []).find(isRunning)
  const directed = direction.trim().length > 0

  useEffect(() => {
    if (!ui.prefill) return
    setDirection(d => (d.trim() ? `${d.trim()} ${ui.prefill}` : ui.prefill))
    patchUi({ prefill: '' })
  }, [ui.prefill])

  const set = patch => {
    setPrefs(p => {
      const next = { ...p, ...patch }
      storageSet('make', next)
      return next
    })
  }
  const setDir = v => {
    setDirection(v)
    storageSet('direction', v)
  }
  const make = async () => {
    setBusy(true)
    const job = await startFilm(sid, optionsFrom(prefs, direction))
    setBusy(false)
    if (job) onStarted(job)
  }
  const chosen = styles.find(s => s.id === prefs.style) || styles[0]
  const summary = [modeLabel(prefs.mode), chosen ? chosen.name : prefs.style, `${prefs.seconds} s`,
    prefs.aspect === 'both' ? '16:9 + 9:16' : prefs.aspect, prefs.voice ? 'narrated' : 'captions only'].join(' · ')
  let blocker = ''
  if (backendDown) blocker = 'The Showreel backend is off.'
  else if (!sid) blocker = 'Open a chat first: Showreel films the chat you are looking at.'
  else if (running) blocker = 'A showreel is rendering for this chat.'

  return jsxs('div', {
    className: 'srl-make',
    children: [
      jsxs('div', {
        className: 'srl-make-main',
        children: [
          jsx(Section, {
            label: 'What kind of film',
            children: jsxs('div', { className: 'srl-stack', children: [
              jsx(Seg, { label: 'Mode', options: MODES, value: prefs.mode, onChange: mode => set({ mode }) }),
              jsx('div', { className: 'srl-hint', children: (MODES.find(m => m.id === prefs.mode) || MODES[0]).hint })
            ] })
          }),
          jsx(Section, {
            label: 'Style',
            aside: stylesQ.isLoading ? 'loading…' : null,
            children: jsx('div', { className: 'srl-gallery', role: 'list', children: styles.map(s =>
              jsx('div', { role: 'listitem', children: jsx(StyleCard, { style: s, selected: s.id === prefs.style, onSelect: style => set({ style }) }) }, s.id)) })
          })
        ]
      }),
      jsxs('div', {
        className: 'srl-make-side',
        children: [
          jsx(Section, {
            label: 'Format',
            children: jsxs('div', { className: 'srl-form', children: [
              jsxs('div', { className: 'srl-row', children: [jsx('span', { children: 'Length' }), jsx(Seg, { label: 'Length', options: LENGTHS, value: String(prefs.seconds), onChange: seconds => set({ seconds }) })] }),
              jsxs('div', { className: 'srl-row', children: [jsx('span', { children: 'Aspect' }), jsx(Seg, { label: 'Aspect', options: ASPECTS, value: prefs.aspect, onChange: aspect => set({ aspect }) })] }),
              jsxs('div', { className: 'srl-row', children: [jsx('span', { children: 'Narration' }), jsx(Toggle, { label: 'Narration', checked: Boolean(prefs.voice), onChange: voice => set({ voice }) })] }),
              jsxs('div', { className: cx('srl-row', !directed && 'is-dim'), children: [jsx('span', { children: 'Effort' }), jsx(Seg, { label: 'Director effort', options: EFFORTS, value: prefs.effort, onChange: effort => set({ effort }) })] }),
              jsx('div', { className: 'srl-hint', children: directed ? EFFORT_HINT[prefs.effort] : 'Effort applies to Directed films (write a direction below).' })
            ] })
          }),
          jsx(Section, {
            label: 'Direction',
            aside: directed ? jsx('span', { className: 'srl-pill', 'data-tone': 'accent', children: 'Directed film' }) : 'optional',
            children: jsxs('div', { className: 'srl-stack', children: [
              jsx(TextArea, {
                value: direction,
                rows: 4,
                maxLength: 2000,
                placeholder: 'Describe the film you want, in your own words. For example: pixel but transition into a different style mid way through, goal is to sell the product.',
                'aria-label': 'Direction',
                onChange: e => setDir(e.target.value)
              }),
              directed
                ? jsx('div', { className: 'srl-hint', children: 'The Director writes a treatment, codes the scenes it needs, renders keyframes, has a critic score them and revises before the final render. You can watch it work in Live.' })
                : jsx('div', { className: 'srl-examples', children: DIRECTION_EXAMPLES.map(x => jsx('button', { type: 'button', className: 'srl-example', onClick: () => setDir(x), children: x }, x)) })
            ] })
          }),
          jsxs('div', { className: 'srl-make-go', children: [
            jsx('div', { className: 'srl-summary', children: summary }),
            jsx(Btn, {
              variant: 'default', size: 'lg', icon: directed ? 'sparkle' : 'device-camera-video', busy, disabled: Boolean(blocker),
              onClick: make, children: directed ? 'Direct this film' : 'Make showreel'
            }),
            blocker ? jsx('div', { className: 'srl-hint srl-blocker', children: blocker }) : null,
            running ? jsx('button', { type: 'button', className: 'srl-link', onClick: () => requestTab('live'), children: 'Watch the running one in Live' }) : null
          ] })
        ]
      })
    ]
  })
}

// ── Live ───────────────────────────────────────────────────────────────────────────────────────────
function stageLabel(stage, job) {
  const directed = isDirected(job)
  const voice = !(job && job.options && job.options.voice === false)
  return {
    queued: 'Waiting to start',
    reading: 'Reading the session',
    storyboard: directed ? 'The Director at work' : 'Writing the storyboard',
    voice: voice ? 'Recording narration' : 'Captions',
    layout: 'Laying out the scenes',
    render: 'Rendering frames',
    mix: 'Mixing music and voice',
    qa: 'Quality checks'
  }[stage] || stage
}

function StageList({ job }) {
  const at = STAGES.indexOf(job.stage)
  const finished = job.stage === 'done'
  const stopped = job.stage === 'failed' || job.stage === 'cancelled'
  const times = job.stages || {}
  // a failed/cancelled job stopped in the last stage that has a time
  const lastTimed = STAGES.reduce((k, s, i) => (times[s] != null ? i : k), -1)
  return jsx('ol', {
    className: 'srl-stages',
    children: STAGES.map((s, i) => {
      let st = 'todo'
      if (finished || (at >= 0 && i < at) || (stopped && i < lastTimed)) st = 'done'
      else if (!stopped && i === at) st = 'active'
      else if (stopped && i === lastTimed) st = job.stage === 'failed' ? 'failed' : 'stopped'
      const t = times[s]
      return jsxs('li', {
        'data-st': st,
        children: [
          jsx('span', { className: 'srl-mark', 'aria-label': st, children: st === 'active' ? jsx(Spinner, {}) : null }),
          jsxs('span', { className: 'srl-stage-name', children: [stageLabel(s, job), st === 'active' && job.stage_pct ? jsx('i', { className: 'srl-mini', children: jsx('b', { style: { width: pctText(job.stage_pct) } }) }) : null] }),
          jsx('span', { className: 'srl-stage-time', children: t != null && st !== 'todo' ? fmtDur(t) : '' })
        ]
      }, s)
    })
  })
}

function LiveView({ job, sid, now, onTab }) {
  const [cancelling, setCancelling] = useState(false)
  if (!job) {
    return jsx(Empty, { icon: 'device-camera-video', title: 'Nothing is rendering', children: jsxs('span', { children: ['Start a film in ', jsx('button', { type: 'button', className: 'srl-link', onClick: () => onTab('make'), children: 'Make' }), '.'] }) })
  }
  const running = isRunning(job)
  const updated = Number(job.updated || 0) * 1000
  const eta = job.eta_s != null && running ? Math.max(0, job.eta_s - Math.max(0, (now - updated) / 1000)) : null
  const started = Number(job.started || job.created || 0) * 1000
  const elapsed = started ? ((job.finished ? job.finished * 1000 : now) - started) / 1000 : 0
  const opts = job.options || {}
  const cancel = async () => {
    setCancelling(true)
    try {
      await api(`/jobs/${job.id}/cancel`, { method: 'POST' })
      notify('info', 'Stopping the showreel…')
      invalidate('job', job.id)
    } catch (e) {
      notify('error', `Could not cancel: ${e.message}`)
    }
    setCancelling(false)
  }
  const again = async () => {
    const next = await startFilm(sid || job.session_id, { ...opts, notes: '' })
    if (next) onTab('live')
  }
  const err = job.error && typeof job.error === 'object' ? job.error : job.error ? { message: String(job.error) } : null
  const copyDetails = async () => {
    const ok = await copyText(JSON.stringify({ id: job.id, error: err, log: (job.log || []).slice(-12) }, null, 1))
    notify(ok ? 'success' : 'error', ok ? 'Error details copied' : 'Could not reach the clipboard')
  }
  const note = running ? job.note || (job.stage === 'queued' ? 'Starting…' : '') : ''

  return jsxs('div', {
    className: 'srl-live',
    children: [
      jsxs('div', {
        className: 'srl-live-main',
        children: [
          jsxs('div', { className: 'srl-jobhead', children: [
            jsx('div', { className: 'srl-jobtitle', children: job.title || (isDirected(job) ? 'Directed film' : 'Showreel') }),
            jsx('div', { className: 'srl-jobmeta', children: [isDirected(job) ? 'Directed' : modeLabel(opts.mode), opts.style, opts.seconds ? `${opts.seconds} s` : '', (opts.aspects || []).join(' + '), opts.voice === false ? 'captions only' : 'narrated'].filter(Boolean).join(' · ') })
          ] }),
          jsxs('div', { className: 'srl-progress-block', 'data-st': job.stage, children: [
            jsxs('div', { className: 'srl-progress-top', children: [
              jsx('b', { className: 'srl-pct', children: job.stage === 'done' ? 'Done' : job.stage === 'failed' ? 'Failed' : job.stage === 'cancelled' ? 'Cancelled' : pctText(job.pct) }),
              jsx('span', { className: 'srl-eta', children: running ? fmtEta(eta) : elapsed ? `took ${fmtDur(elapsed)}` : '' })
            ] }),
            jsx('div', { className: 'srl-progress', 'data-live': running || undefined, role: 'progressbar', 'aria-valuemin': 0, 'aria-valuemax': 100, 'aria-valuenow': Math.round((Number(job.pct) || 0) * 100), children: jsx('i', { style: { width: job.stage === 'done' ? '100%' : pctText(job.pct) } }) }),
            note ? jsx('div', { className: 'srl-note', children: note }) : null
          ] }),
          jsx(StageList, { job }),
          running ? jsxs('div', { className: 'srl-actions', children: [
            jsx(Btn, { variant: 'outline', icon: 'debug-stop', busy: cancelling, onClick: cancel, children: 'Cancel' }),
            jsx('span', { className: 'srl-hint', children: elapsed ? `running for ${fmtDur(elapsed)}` : '' })
          ] }) : null,
          job.stage === 'done' ? jsx('div', { className: 'srl-actions', children: jsx(Btn, { variant: 'default', icon: 'play', onClick: () => onTab('result'), children: 'Watch the film' }) }) : null,
          err && job.stage === 'failed' ? jsx(Alert, { tone: 'error', children: jsxs('div', { className: 'srl-stack', children: [
            jsx('b', { children: err.message || 'The render failed.' }),
            err.hint ? jsx('span', { children: err.hint }) : null,
            err.code ? jsx('code', { children: err.code }) : null,
            jsxs('div', { className: 'srl-actions', children: [
              jsx(Btn, { variant: 'secondary', icon: 'refresh', onClick: again, children: 'Try again' }),
              jsx(Btn, { variant: 'ghost', icon: 'copy', onClick: copyDetails, children: 'Copy details' })
            ] })
          ] }) }) : null,
          job.stage === 'cancelled' ? jsx(Alert, { tone: 'info', children: jsxs('div', { className: 'srl-actions', children: [jsx('span', { children: 'Cancelled.' }), jsx(Btn, { variant: 'secondary', icon: 'refresh', onClick: again, children: 'Make it again' })] }) }) : null,
          (job.warnings || []).length ? jsx(Section, { label: 'Notes from the render', children: jsx('ul', { className: 'srl-warnings', children: job.warnings.slice(-8).map((w, i) => jsx('li', { children: w }, i)) }) }) : null,
          !isDirected(job) && (job.log || []).length ? jsx(ActivityLog, { log: job.log }) : null
        ]
      }),
      isDirected(job) ? jsx(DirectorPanel, { job, now }) : null
    ]
  })
}

function ActivityLog({ log }) {
  const [open, setOpen] = useState(false)
  const rows = log.slice(-(open ? 30 : 5))
  return jsx(Section, {
    label: 'Activity',
    aside: jsx('button', { type: 'button', className: 'srl-link', onClick: () => setOpen(!open), children: open ? 'less' : 'more' }),
    children: jsx('ul', { className: 'srl-activity', children: rows.map((e, i) => jsx('li', { 'data-level': e.level, children: e.msg }, `${e.t}-${i}`)) })
  })
}

// ── the Director, live ─────────────────────────────────────────────────────────────────────────────
const EMPTY_DLOG = { entries: [], versions: [], coding: [], treatment: null, usage: null, result: null, bar: 8, rubric: [], loaded: false, error: '' }

/** Incremental Director log: polls `?since=` every 2 s while the job runs, one last read when it ends. */
function useDirectorLog(jobId, live) {
  const ref = useRef({ id: null, next: 0, data: EMPTY_DLOG })
  const [, bump] = useState(0)
  if (ref.current.id !== jobId) ref.current = { id: jobId, next: 0, data: EMPTY_DLOG }
  useEffect(() => {
    if (!jobId || !CTX) return undefined
    let alive = true
    let stop = null
    const tick = async () => {
      const s = ref.current
      if (s.id !== jobId) return
      try {
        const r = await api(`/jobs/${jobId}/director-log?since=${s.next}`)
        if (!alive || ref.current.id !== jobId) return
        const entries = s.data.entries.concat(r.entries || []).slice(-2000)
        ref.current = { id: jobId, next: r.next ?? s.next, data: { ...r, entries, loaded: true, error: '' } }
      } catch (e) {
        if (!alive) return
        ref.current = { ...s, data: { ...s.data, loaded: true, error: e.message } }
      }
      bump(n => n + 1)
      if (alive && live) stop = CTX.setTimeout(tick, 2000)
    }
    tick()
    return () => {
      alive = false
      if (stop) stop()
    }
  }, [jobId, live])
  return ref.current.data
}

function railState(entries, running) {
  const seen = new Map()
  entries.forEach((e, i) => {
    const id = RAIL_OF[e.step] || e.step
    if (RAIL.some(r => r.id === id)) seen.set(id, i)
  })
  const last = [...seen.entries()].sort((a, b) => b[1] - a[1])[0]
  const finished = seen.has('final')
  return RAIL.map(r => ({ ...r, st: finished ? (seen.has(r.id) ? 'done' : 'skip') : !seen.has(r.id) ? 'todo' : running && last && last[0] === r.id ? 'active' : 'done' }))
}

function DirectorPanel({ job, now }) {
  const running = isRunning(job)
  const d = useDirectorLog(job.id, running)
  const [details, setDetails] = useState(false)
  const rail = railState(d.entries, running)
  const latest = d.versions.length ? d.versions[d.versions.length - 1] : null
  const scored = d.versions.filter(v => v.score)
  const direction = d.direction || (job.options && job.options.direction) || ''

  return jsxs('div', {
    className: 'srl-dir',
    children: [
      jsxs('div', { className: 'srl-dir-head', children: [
        jsxs('div', { className: 'srl-dir-title', children: [running ? jsx('i', { className: 'srl-live-dot', 'aria-hidden': true }) : null, 'Watch the Director work'] }),
        d.usage && d.usage.calls ? jsx('span', { className: 'srl-hint', children: `${d.usage.calls} model call${d.usage.calls === 1 ? '' : 's'} · ${fmtTokens(d.usage.input_tokens)} in · ${fmtTokens(d.usage.output_tokens)} out` }) : null
      ] }),
      direction ? jsx('blockquote', { className: 'srl-quote', children: direction }) : null,
      jsx('ol', { className: 'srl-rail', children: rail.map(r => jsx('li', { 'data-st': r.st, children: r.label }, r.id)) }),
      !d.loaded ? jsx('div', { className: 'srl-hint', children: 'Connecting to the Director…' }) : null,
      d.error ? jsx(Alert, { tone: 'warn', children: `The Director's log is not readable right now: ${d.error}` }) : null,
      d.loaded && !d.available && running ? jsx('div', { className: 'srl-hint', children: 'The Director starts once the session is read.' }) : null,
      d.treatment ? jsx(TreatmentCard, { t: d.treatment, seconds: (job.options && job.options.seconds) || 0 }) : null,
      (latest && latest.scenes.length) || d.coding.length ? jsx(ScenesBeingCoded, { jobId: job.id, version: latest, coding: d.coding, running }) : null,
      scored.length ? jsx(Section, { label: 'Critic', aside: `bar ${d.bar}/10 on every score`, children: jsx('div', { className: 'srl-rounds', children: scored.map(v => jsx(CriticRound, { v, bar: d.bar, rubric: d.rubric, best: d.best }, v.n)) }) }) : null,
      d.versions.some(v => v.sheets.length) ? jsx(ContactSheets, { jobId: job.id, versions: d.versions }) : null,
      d.result && d.result.library_saved && d.result.library_saved.length ? jsx(Alert, { tone: 'info', children: `Saved to your library: ${d.result.library_saved.join(', ')}` }) : null,
      jsx(DirectorFeed, { entries: d.entries, details, setDetails, running })
    ]
  })
}

function Act({ a, i, total, count }) {
  const share = (Number(a.duration) || total / count) / total
  return withTip(a.world || null, jsxs('div', {
    className: 'srl-act', style: { flexGrow: Math.max(0.5, share * 10), '--rot': String((i * 67) % 360) },
    children: [jsx('b', { children: a.name }), jsx('span', { children: [a.style, a.duration ? `${a.duration} s` : ''].filter(Boolean).join(' · ') })]
  }))
}

function TreatmentCard({ t, seconds }) {
  const total = t.acts.reduce((a, x) => a + (Number(x.duration) || 0), 0) || seconds || 1
  return jsxs('div', {
    className: 'srl-treat',
    children: [
      jsx('div', { className: 'srl-treat-kicker', children: 'Treatment' }),
      jsx('div', { className: 'srl-treat-title', children: t.title || 'Untitled' }),
      t.logline ? jsx('p', { className: 'srl-treat-log', children: t.logline }) : null,
      t.acts.length ? jsx('div', { className: 'srl-acts', children: t.acts.map((a, i) => jsx(Act, { a, i, total, count: t.acts.length }, i)) }) : null,
      t.signature_moment ? jsxs('div', { className: 'srl-treat-sig', children: [jsx('span', { children: 'Signature moment' }), t.signature_moment] }) : null,
      t.requirements.length ? jsx('div', { className: 'srl-chips', children: t.requirements.map((r, i) => jsx('span', { className: 'srl-chip-s', children: r }, i)) }) : null
    ]
  })
}

function ScenesBeingCoded({ jobId, version, coding, running }) {
  const [peek, setPeek] = useState(null)
  const scenes = (version && version.scenes) || []
  const code = useApi(qk('scene', jobId, peek && peek.v, peek && peek.name), peek ? `/jobs/${jobId}/director/scene?v=${peek.v}&name=${enc(peek.name)}` : '', { enabled: Boolean(peek), staleTime: Infinity })
  return jsx(Section, {
    label: 'Scenes the Director is coding',
    aside: version ? `version ${version.n}` : null,
    children: jsxs('div', { className: 'srl-stack', children: [
      jsx('div', { className: 'srl-chips', children: [
        ...scenes.map(s => jsx('button', {
          type: 'button', className: 'srl-scene-chip', 'data-st': 'done', 'aria-pressed': Boolean(peek && peek.name === s.name),
          onClick: () => setPeek(peek && peek.name === s.name ? null : { v: version.n, name: s.name }),
          children: [jsx(Icon, { name: 'code' }, 'i'), jsx('span', { children: s.name }, 'n'), jsx('em', { children: `${s.lines} lines` }, 'l')]
        }, `s-${s.name}`)),
        ...coding.map(name => jsx('span', { className: 'srl-scene-chip', 'data-st': running ? 'active' : 'todo', children: [running ? jsx(Spinner, {}, 'sp') : null, jsx('span', { children: name }, 'n'), jsx('em', { children: running ? 'coding…' : 'not used' }, 'l')] }, `c-${name}`))
      ] }),
      peek ? jsx('pre', { className: 'srl-code', 'aria-label': `${peek.name} scene code`, children: code.isLoading ? 'loading…' : code.error ? `Could not read the scene: ${code.error.message}` : (code.data && code.data.code) || '' }) : null
    ] })
  })
}

function CriticRound({ v, bar, rubric, best }) {
  const s = v.score
  const keys = rubric && rubric.length ? rubric : Object.keys(s.scores || {})
  return jsxs('div', {
    className: 'srl-round', 'data-pass': s.passed ? 'yes' : 'no',
    children: [
      jsxs('div', { className: 'srl-round-head', children: [
        jsx('b', { children: `Round ${s.round || v.n} · v${v.n}` }),
        jsx('span', { className: 'srl-round-mean', children: `${Number(s.mean || 0).toFixed(1)} avg · min ${s.min}` }),
        s.passed ? jsx('span', { className: 'srl-pill', 'data-tone': 'ok', children: 'passes the bar' }) : s.verdict ? jsx('span', { className: 'srl-pill', children: s.verdict }) : null,
        best === v.n ? jsx('span', { className: 'srl-pill', 'data-tone': 'accent', children: 'final' }) : null
      ] }),
      jsx('div', { className: 'srl-rubric', children: keys.map(k => {
        const val = Number((s.scores || {})[k]) || 0
        const tone = val >= bar ? 'ok' : val >= bar - 2 ? 'mid' : 'low'
        return jsxs('div', { className: 'srl-rub', children: [
          jsx('span', { className: 'srl-rub-k', children: RUBRIC_LABEL[k] || k }),
          jsxs('span', { className: 'srl-rub-track', children: [jsx('i', { 'data-tone': tone, style: { width: `${Math.min(100, val * 10)}%` } }), jsx('em', { style: { left: `${bar * 10}%` } })] }),
          jsx('span', { className: 'srl-rub-v', children: val ? val.toFixed(val % 1 ? 1 : 0) : '–' })
        ] }, k)
      }) }),
      s.product_share != null ? jsx('div', { className: 'srl-hint', children: `Product visible in ${pctText(s.product_share)} of keyframes${s.product_hero != null ? `, framed as the hero in ${pctText(s.product_hero)}` : ''}.` }) : null,
      v.changes && v.changes.length ? jsx('details', { className: 'srl-changes', children: [jsx('summary', { children: `What v${v.n} changed (${v.changes.length})` }, 's'), jsx('ul', { children: v.changes.map((c, i) => jsx('li', { children: c }, i)) }, 'u')] }) : null
    ]
  })
}

function SheetImage({ jobId, v, name, w, onOpen, open }) {
  const q = useApi(qk('dimg', jobId, v, name, w), `/jobs/${jobId}/director/image?v=${v}&name=${enc(name)}&w=${w}`, { staleTime: Infinity })
  const url = q.data && q.data.url
  return jsx('button', {
    type: 'button', className: cx('srl-sheet', open && 'is-open'), onClick: onOpen, 'aria-label': `Contact sheet ${name} of version ${v}`,
    children: url ? jsx('img', { src: url, alt: '' }) : jsx('span', { className: 'srl-sheet-wait', children: q.error ? 'unavailable' : jsx(Spinner, {}) })
  })
}

function ContactSheets({ jobId, versions }) {
  const [open, setOpen] = useState(null)
  return jsx(Section, {
    label: 'Keyframes the critic saw',
    children: jsxs('div', { className: 'srl-stack', children: [
      jsx('div', { className: 'srl-sheets', children: versions.flatMap(v => v.sheets.map(name => jsxs('figure', { children: [
        jsx(SheetImage, { jobId, v: v.n, name, w: 480, open: open && open.v === v.n && open.name === name, onOpen: () => setOpen(open && open.v === v.n && open.name === name ? null : { v: v.n, name }) }),
        jsx('figcaption', { children: `v${v.n} · ${name.replace('.jpg', '')} · ${v.keyframes} keyframes` })
      ] }, `${v.n}-${name}`))) }),
      open ? jsx('div', { className: 'srl-sheet-big', children: jsx(SheetImage, { jobId, v: open.v, name: open.name, w: 1600, open: true, onOpen: () => setOpen(null) }) }) : null
    ] })
  })
}

function DirectorFeed({ entries, details, setDetails, running }) {
  const box = useRef(null)
  const stick = useRef(true)
  const shown = entries.filter(e => details || e.level !== 'debug')
  useEffect(() => {
    const el = box.current
    if (el && stick.current) el.scrollTop = el.scrollHeight
  }, [shown.length])
  return jsx(Section, {
    label: 'Live log',
    aside: jsx('button', { type: 'button', className: 'srl-link', onClick: () => setDetails(!details), children: details ? 'hide details' : 'show details' }),
    children: jsx('ol', {
      className: 'srl-feed', ref: box, 'aria-live': running ? 'polite' : undefined,
      onScroll: e => { const el = e.currentTarget; stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 24 },
      children: shown.length
        ? shown.map(e => jsxs('li', { 'data-level': e.level, children: [
            jsx('time', { children: clock(e.t) }),
            jsx('span', { className: 'srl-step', 'data-step': RAIL_OF[e.step] || e.step, children: e.step }),
            jsx('span', { className: 'srl-msg', children: e.msg })
          ] }, e.i))
        : jsx('li', { className: 'srl-hint', children: running ? 'Waiting for the first word from the Director…' : 'No log for this film.' })
    })
  })
}

// ── Storyboard ─────────────────────────────────────────────────────────────────────────────────────
function keyed(sb) {
  return ((sb && sb.scenes) || []).map((s, i) => ({ ...s, _k: `k${i}`, _orig: i, _drop: false }))
}

function StoryboardView({ job, sid, onTab }) {
  const directed = isDirected(job)
  if (!job) return jsx(Empty, { icon: 'list-ordered', title: 'No film yet', children: 'Make a showreel first; its storyboard shows up here for editing.' })
  if (directed) return jsx(DirectedShots, { job })
  return jsx(StoryboardEditor, { job, sid, onTab }, job.id)
}

function DirectedShots({ job }) {
  const d = useDirectorLog(job.id, false)
  const best = d.versions.find(v => v.n === d.best) || d.versions[d.versions.length - 1]
  return jsxs('div', { className: 'srl-stack', children: [
    jsx(Alert, { tone: 'info', children: 'Directed films are written by the Director as code, not as a storyboard. Change one with Revise on the Result tab; the Director keeps what works and fixes what you name.' }),
    best && best.shots.length ? jsx(Section, { label: `Shots (version ${best.n})`, children: jsx('ol', { className: 'srl-shots', children: best.shots.map(s => jsxs('li', { children: [
      jsx('time', { children: `${clock(s.t0)}–${clock(s.t1)}` }), jsx('b', { children: s.id }), jsx('code', { children: s.scene })
    ] }, s.id)) }) }) : jsx('div', { className: 'srl-hint', children: isRunning(job) ? 'The shot list appears once the Director has written the film script.' : 'No shot list was saved for this film.' })
  ] })
}

function StoryboardEditor({ job, sid, onTab }) {
  const sbQ = useApi(qk('storyboard', job.id), `/jobs/${job.id}/storyboard`, { enabled: Boolean(job.storyboard) || job.stage === 'done', refetchInterval: false })
  const thumbsQ = useApi(qk('thumbs', job.id), `/jobs/${job.id}/thumbs`, { enabled: ['render', 'mix', 'qa', 'done'].includes(job.stage), staleTime: job.stage === 'done' ? Infinity : 15000 })
  const base = sbQ.data && sbQ.data.storyboard
  const [scenes, setScenes] = useState(null)
  const [head, setHead] = useState({ title: '', tagline: '' })
  const [dirty, setDirty] = useState(false)
  const [busy, setBusy] = useState('')
  const [drag, setDrag] = useState(null)
  const dragFrom = useRef(null)      // read by the drop handler: drag events can outrun a re-render
  const [over, setOver] = useState(null)
  const [aspect, setAspect] = useState(() => ((job.options && job.options.aspects) || ['16:9']).length > 1 ? 'both' : ((job.options && job.options.aspects) || ['16:9'])[0])

  useEffect(() => {
    if (base && !dirty) {
      setScenes(keyed(base))
      setHead({ title: base.title || '', tagline: base.tagline || '' })
    }
  }, [base])

  if (!job.storyboard && !base) {
    return isRunning(job)
      ? jsx(Empty, { icon: 'list-ordered', title: 'Writing the storyboard…', children: 'It appears here once the story stage finishes. You can edit it and re-render without another model call.' })
      : jsx(Empty, { icon: 'list-ordered', title: 'No storyboard', children: 'This film stopped before its storyboard was written.' })
  }
  if (sbQ.error) return jsx(Alert, { tone: 'error', children: `Could not load the storyboard: ${sbQ.error.message}` })
  if (!scenes) return jsx('div', { className: 'srl-hint', children: 'Loading the storyboard…' })

  const thumbs = (thumbsQ.data && thumbsQ.data.thumbs) || []
  const kept = scenes.filter(s => !s._drop)
  const change = next => { setScenes(next); setDirty(true) }
  const edit = (k, patch) => change(scenes.map(s => (s._k === k ? { ...s, ...patch } : s)))
  const move = (from, to) => {
    if (to < 0 || to >= scenes.length || from === to) return
    const next = scenes.slice()
    const [it] = next.splice(from, 1)
    next.splice(to, 0, it)
    change(next)
  }
  const payload = () => ({
    ...base,
    title: head.title,
    tagline: head.tagline,
    scenes: kept.map(({ _k, _orig, _drop, ...s }) => s)
  })
  const save = async () => {
    setBusy('save')
    try {
      await api(`/jobs/${job.id}/storyboard`, { method: 'PUT', body: { storyboard: payload() } })
      setDirty(false)
      invalidate('storyboard', job.id)
      notify('success', 'Storyboard saved. Re-render to see it.')
      setBusy('')
      return true
    } catch (e) {
      notify('error', `Could not save: ${e.message}`)
      setBusy('')
      return false
    }
  }
  const rerender = async () => {
    if (dirty && !(await save())) return
    setBusy('render')
    try {
      const next = await api(`/jobs/${job.id}/rerender`, { method: 'POST', body: { aspects: aspect === 'both' ? ['16:9', '9:16'] : [aspect] } })
      selectJob(sid || job.session_id, next.id)
      invalidate('jobs')
      onTab('live')
    } catch (e) {
      notify('error', `Could not re-render: ${e.message}`)
    }
    setBusy('')
  }
  const reset = () => {
    setScenes(keyed(base))
    setHead({ title: base.title || '', tagline: base.tagline || '' })
    setDirty(false)
  }

  return jsxs('div', {
    className: 'srl-board',
    children: [
      jsxs('div', { className: 'srl-board-head', children: [
        jsxs('label', { className: 'srl-field', children: [jsx('span', { children: 'Title' }), jsx(TextInput, { value: head.title, maxLength: 60, onChange: e => { setHead({ ...head, title: e.target.value }); setDirty(true) } })] }),
        jsxs('label', { className: 'srl-field', children: [jsx('span', { children: 'Tagline' }), jsx(TextInput, { value: head.tagline, maxLength: 90, onChange: e => { setHead({ ...head, tagline: e.target.value }); setDirty(true) } })] })
      ] }),
      jsx('div', { className: 'srl-hint', children: `${kept.length} of ${scenes.length} scenes · drag to reorder · edits re-render without a model call (narration is recorded again)${sbQ.data && sbQ.data.edited ? ' · showing your saved edit' : ''}` }),
      jsx('ol', {
        className: 'srl-sb-list',
        children: scenes.map((s, i) => jsx(SceneCard, {
          s, i, thumb: thumbs[s._orig] || '', dragging: drag === i, over: over === i && drag !== null && drag !== i,
          onEdit: patch => edit(s._k, patch),
          onMove: d => move(i, i + d),
          onDragStart: () => { dragFrom.current = i; setDrag(i) },
          onDragEnd: () => { dragFrom.current = null; setDrag(null); setOver(null) },
          onDragOver: () => setOver(i),
          onDrop: () => { if (dragFrom.current !== null) move(dragFrom.current, i); dragFrom.current = null; setDrag(null); setOver(null) },
          last: i === scenes.length - 1
        }, s._k))
      }),
      jsxs('div', { className: 'srl-board-foot', children: [
        jsx(Seg, { label: 'Aspect for the re-render', options: ASPECTS, value: aspect, onChange: setAspect }),
        jsx(Btn, { variant: 'secondary', icon: 'save', busy: busy === 'save', disabled: !dirty || !kept.length, onClick: save, children: 'Save' }),
        jsx(Btn, { variant: 'default', icon: 'play', busy: busy === 'render', disabled: !kept.length || isRunning(job), onClick: rerender, tip: isRunning(job) ? 'Wait for this render to finish' : null, children: 'Re-render' }),
        dirty ? jsx(Btn, { variant: 'ghost', icon: 'discard', onClick: reset, children: 'Discard edits' }) : null
      ] })
    ]
  })
}

function SceneCard({ s, i, thumb, dragging, over, onEdit, onMove, onDragStart, onDragEnd, onDragOver, onDrop, last }) {
  const vo = String(s.vo || '')
  const n = words(vo)
  const labelWords = words(s.label)
  const [badThumb, setBadThumb] = useState('')
  const showThumb = thumb && badThumb !== thumb
  return jsxs('li', {
    className: 'srl-sb-card', 'data-drag': dragging ? 'self' : over ? 'over' : undefined, 'data-dropped': s._drop || undefined,
    draggable: true,
    onDragStart: e => { try { e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', String(i)) } catch (err) { /* jsdom / old engines */ } onDragStart() },
    onDragEnd,
    onDragOver: e => { e.preventDefault(); onDragOver() },
    onDrop: e => { e.preventDefault(); onDrop() },
    children: [
      jsxs('div', { className: 'srl-sb-grip', children: [
        jsx('span', { className: 'srl-sb-n', children: i + 1 }),
        jsx('button', { type: 'button', className: 'srl-icon-btn', 'aria-label': `Move scene ${i + 1} up`, disabled: i === 0, onClick: () => onMove(-1), children: jsx(Icon, { name: 'arrow-up' }) }),
        jsx('button', { type: 'button', className: 'srl-icon-btn', 'aria-label': `Move scene ${i + 1} down`, disabled: last, onClick: () => onMove(1), children: jsx(Icon, { name: 'arrow-down' }) })
      ] }),
      jsx('div', { className: 'srl-sb-thumb', children: showThumb ? jsx('img', { src: thumb, alt: `Scene ${i + 1}`, onError: () => setBadThumb(thumb) }) : jsx('span', { children: s.type }) }),
      jsxs('div', { className: 'srl-sb-body', children: [
        jsxs('div', { className: 'srl-sb-top', children: [
          jsx('span', { className: 'srl-type', children: s.type }),
          jsx(TextInput, { value: s.label || '', placeholder: 'On-screen label', maxLength: 48, 'aria-label': `Scene ${i + 1} label`, disabled: s._drop, onChange: e => onEdit({ label: e.target.value }) }),
          jsx('button', { type: 'button', className: 'srl-icon-btn', 'aria-label': s._drop ? `Keep scene ${i + 1}` : `Drop scene ${i + 1}`, 'aria-pressed': s._drop, onClick: () => onEdit({ _drop: !s._drop }), children: jsx(Icon, { name: s._drop ? 'discard' : 'trash' }) })
        ] }),
        jsx(TextArea, { value: vo, rows: 2, placeholder: 'Narration (leave empty for a silent scene)', 'aria-label': `Scene ${i + 1} narration`, disabled: s._drop, onChange: e => onEdit({ vo: e.target.value }) }),
        jsxs('div', { className: 'srl-sb-meta', children: [
          jsx('span', { 'data-warn': n > 28 || undefined, children: `${n} word${n === 1 ? '' : 's'}${n > 28 ? ' · long: about 28 fit one scene' : ''}` }),
          labelWords > 6 ? jsx('span', { 'data-warn': true, children: 'label over 6 words' }) : null,
          (s.refs || []).length ? jsx('span', { className: 'srl-refs', children: `evidence ${(s.refs || []).slice(0, 4).join(', ')}${s.refs.length > 4 ? '…' : ''}` }) : null
        ] })
      ] })
    ]
  })
}

// ── Result ─────────────────────────────────────────────────────────────────────────────────────────
function outputsOf(job) {
  const out = { ...(job.outputs || {}), ...(job.delivered || {}) }
  return Object.keys(out).sort().map(a => ({ aspect: a, path: out[a] })).filter(o => o.path)
}

function Player({ path }) {
  if (!sdk.MessageTextContent) {
    return jsx(Alert, { tone: 'info', children: `This Hermes Desktop has no built-in player for plugins. The film is at ${path}` })
  }
  return jsx('div', { className: 'srl-player', children: jsx(sdk.MessageTextContent, { text: mediaLine(path) }) })
}

function ResultView({ job, sid, onTab }) {
  const [aspect, setAspect] = useState(null)
  const [notes, setNotes] = useState('')
  const [busy, setBusy] = useState('')
  const [sheetOpen, setSheetOpen] = useState(false)
  const done = job && job.stage === 'done'
  const postQ = useApi(qk('post', job && job.id), job ? `/jobs/${job.id}/post-text` : '', { enabled: Boolean(done), staleTime: 60000 })
  const thumbsQ = useApi(qk('thumbs', job && job.id), job ? `/jobs/${job.id}/thumbs` : '', { enabled: Boolean(done), staleTime: Infinity })
  if (!job) return jsx(Empty, { icon: 'play-circle', title: 'No film yet', children: 'Your finished showreel plays here.' })
  if (!done) {
    return isRunning(job)
      ? jsx(Empty, { icon: 'play-circle', title: `Still rendering (${pctText(job.pct)})`, children: jsx('button', { type: 'button', className: 'srl-link', onClick: () => onTab('live'), children: 'Watch it in Live' }) })
      : jsx(Empty, { icon: 'play-circle', title: job.stage === 'cancelled' ? 'This film was cancelled' : 'This film did not finish', children: jsx('button', { type: 'button', className: 'srl-link', onClick: () => onTab('live'), children: 'See what happened' }) })
  }
  const outs = outputsOf(job)
  const current = outs.find(o => o.aspect === aspect) || outs[0]
  const directed = isDirected(job)
  const has = new Set(outs.map(o => o.aspect))
  const other = has.has('16:9') && has.has('9:16') ? null : has.has('9:16') ? '16:9' : '9:16'
  const renderOther = async () => {
    setBusy('aspect')
    try {
      const next = await api(`/jobs/${job.id}/rerender`, { method: 'POST', body: { aspects: [other] } })
      selectJob(sid || job.session_id, next.id)
      invalidate('jobs')
      onTab('live')
    } catch (e) {
      notify('error', e.message)
    }
    setBusy('')
  }
  const revise = async () => {
    setBusy('revise')
    try {
      const next = await api(`/jobs/${job.id}/revise`, { method: 'POST', body: { notes } })
      selectJob(sid || job.session_id, next.id)
      setNotes('')
      invalidate('jobs')
      onTab('live')
    } catch (e) {
      notify('error', `Could not start the revision: ${e.message}`)
    }
    setBusy('')
  }
  const copyPost = async () => {
    const text = postQ.data && postQ.data.text
    if (!text) return notify('warning', 'The post text is not ready yet.')
    const ok = await copyText(text)
    notify(ok ? 'success' : 'error', ok ? 'Post text copied' : 'Could not reach the clipboard')
  }
  const qaWarn = (job.warnings || []).length
  return jsxs('div', {
    className: 'srl-result',
    children: [
      jsxs('div', { className: 'srl-result-main', children: [
        jsxs('div', { className: 'srl-jobhead', children: [
          jsx('div', { className: 'srl-jobtitle', children: job.title || 'Showreel' }),
          jsx('div', { className: 'srl-jobmeta', children: [directed ? 'Directed' : modeLabel((job.options || {}).mode), (job.options || {}).style, job.duration_s ? fmtDur(job.duration_s) : '', job.wall_s ? `made in ${fmtDur(job.wall_s)}` : '', qaWarn ? `${qaWarn} note${qaWarn === 1 ? '' : 's'}` : ''].filter(Boolean).join(' · ') })
        ] }),
        outs.length > 1 ? jsx(Seg, { label: 'Aspect', options: outs.map(o => ({ id: o.aspect, label: o.aspect })), value: current.aspect, onChange: setAspect }) : null,
        current ? jsx(Player, { path: current.path }, current.path) : jsx(Alert, { tone: 'warn', children: 'The job finished but no video file is recorded.' }),
        current ? jsxs('div', { className: 'srl-actions', children: [
          jsx(Btn, { variant: 'secondary', icon: 'folder-opened', onClick: () => reveal(current.path), children: 'Reveal file' }),
          other ? jsx(Btn, {
            variant: 'secondary', icon: other === '9:16' ? 'device-mobile' : 'screen-full', busy: busy === 'aspect', disabled: directed, onClick: renderOther,
            tip: directed ? 'A Directed film renders one aspect per run: ask for it with Revise ("make a 9:16 version").' : 'Same storyboard, no model call',
            children: `Render ${other}`
          }) : null,
          jsx(Btn, { variant: 'secondary', icon: 'copy', disabled: !postQ.data, onClick: copyPost, children: 'Copy post text' })
        ] }) : null,
        postQ.data ? jsx('pre', { className: 'srl-post', children: postQ.data.text }) : null
      ] }),
      jsxs('div', { className: 'srl-result-side', children: [
        jsx(Section, {
          label: directed ? 'Direct another pass' : 'Revise',
          children: jsxs('div', { className: 'srl-stack', children: [
            jsx(TextArea, { value: notes, rows: 3, maxLength: 2000, 'aria-label': 'Revision notes', placeholder: directed ? 'What should the Director change? For example: bigger car in the second act, slower transition, end on the price.' : 'What should change? For example: open on the dashboard, less code, mention the offline mode.', onChange: e => setNotes(e.target.value) }),
            jsxs('div', { className: 'srl-actions', children: [
              jsx(Btn, { variant: 'default', icon: 'sparkle', busy: busy === 'revise', disabled: !notes.trim(), onClick: revise, children: directed ? 'Direct again' : 'Revise' }),
              jsx('span', { className: 'srl-hint', children: directed ? 'The Director keeps what works and fixes what you name.' : 'A new storyboard with your notes, same style and length.' })
            ] })
          ] })
        }),
        thumbsQ.data && thumbsQ.data.contact_sheet ? jsx(Section, {
          label: 'Contact sheet',
          children: jsx('button', { type: 'button', className: cx('srl-sheet', sheetOpen && 'is-open'), onClick: () => setSheetOpen(!sheetOpen), 'aria-label': 'Contact sheet', children: jsx('img', { src: thumbsQ.data.contact_sheet, alt: 'One frame per scene' }) })
        }) : null,
        !directed ? jsx('button', { type: 'button', className: 'srl-link', onClick: () => onTab('board'), children: 'Edit the storyboard' }) : null
      ] })
    ]
  })
}

// ── Library ────────────────────────────────────────────────────────────────────────────────────────
function LibraryView({ onTab }) {
  const q = useApi(qk('library'), '/library', { staleTime: 30000 })
  const items = (q.data && q.data.items) || []
  if (q.isLoading) return jsx('div', { className: 'srl-hint', children: 'Loading your library…' })
  if (q.error) return jsx(Alert, { tone: 'error', children: `Could not read the library: ${q.error.message}` })
  const use = item => {
    patchUi({ prefill: `Use my ${item.name} ${item.kind} (${item.id}).` })
    onTab('make')
  }
  return jsxs('div', { className: 'srl-stack', children: [
    jsxs('div', { className: 'srl-library-head', children: [
      jsx('div', { className: 'srl-hint', children: 'Worlds and scenes the Director invented for your films. Ask for one by name in a direction, for example "use my flower-field world".' }),
      q.data && q.data.dir ? jsx(Btn, { variant: 'ghost', icon: 'folder-opened', onClick: () => reveal(q.data.dir), children: 'Open folder' }) : null
    ] }),
    items.length
      ? jsx('div', { className: 'srl-gallery srl-lib', role: 'list', children: items.map(item => jsxs('article', { role: 'listitem', className: 'srl-card srl-lib-card', children: [
          jsx('div', { className: 'srl-card-media', children: item.thumb ? jsx('img', { src: item.thumb, alt: '' }) : jsx(StylePlaceholder, { id: item.kind === 'world' ? 'nature' : 'other', name: item.name }) }),
          jsxs('div', { className: 'srl-card-meta', children: [
            jsxs('div', { className: 'srl-card-name', children: [item.name, jsx('span', { className: 'srl-soon', children: item.kind }), item.score ? jsx('span', { className: 'srl-score', children: item.score.toFixed(1) }) : null] }),
            jsx('div', { className: 'srl-card-blurb', children: item.describe || item.direction }),
            item.params && item.params.length ? jsx('div', { className: 'srl-params', children: item.params.slice(0, 6).join(' · ') }) : null,
            jsxs('div', { className: 'srl-actions', children: [
              jsx(Btn, { variant: 'secondary', size: 'xs', icon: 'add', onClick: () => use(item), children: 'Use in a film' }),
              jsx(Btn, { variant: 'ghost', size: 'xs', icon: 'folder-opened', onClick: () => reveal(item.path), label: `Reveal ${item.name}` })
            ] })
          ] })
        ] }, item.id)) })
      : jsx(Empty, { icon: 'library', title: 'Your library is empty', children: 'When a Directed film invents a world or a scene (a pixel boss fight, an anime flower field), it is saved here with a thumbnail so later films can reuse it.' })
  ] })
}

// ── the studio (pane + page) ───────────────────────────────────────────────────────────────────────
function JobPicker({ jobs, value, onChange, now }) {
  if (!jobs.length) return null
  const label = j => `${j.title || (isDirected(j) ? 'Directed film' : 'Showreel')} · ${j.stage === 'done' ? 'done' : TERMINAL.has(j.stage) ? j.stage : pctText(j.pct)} · ${fmtAgo(j.created, now)}`
  return jsx('select', {
    className: 'srl-picker', value: value || '', 'aria-label': 'Film', onChange: e => onChange(e.target.value),
    children: jobs.map(j => jsx('option', { value: j.id, children: label(j) }, j.id))
  })
}

function Studio({ variant }) {
  const sid = useSessionId()
  const ui = useAtomValue($ui)
  const [tab, setTabState] = useState(() => {
    const t = storageGet(`tab.${variant}`, 'make')
    return TABS.some(x => x.id === t) ? t : 'make'
  })
  const setTab = t => {
    setTabState(t)
    storageSet(`tab.${variant}`, t)
  }
  const health = useApi(qk('health'), '/health', { staleTime: 30000, refetchInterval: (a, b) => (dataOf(a, b) ? 120000 : 15000) })
  const backendDown = Boolean(health.error)
  const jobsQ = useApi(qk('jobs', sid), sid ? `/jobs?session_id=${enc(sid)}&limit=12` : '', {
    enabled: Boolean(sid) && !backendDown,
    refetchInterval: (a, b) => ((((dataOf(a, b) || {}).jobs) || []).some(isRunning) ? 3000 : 20000)
  })
  const jobs = (jobsQ.data && jobsQ.data.jobs) || []
  const picked = ui.selected[sid || '_']
  const selectedId = picked || (jobs[0] && jobs[0].id) || null
  const listed = jobs.find(j => j.id === selectedId)
  const jobQ = useApi(qk('job', selectedId), selectedId ? `/jobs/${selectedId}` : '', {
    enabled: Boolean(selectedId) && !backendDown,
    refetchInterval: (a, b) => (isRunning(dataOf(a, b) || listed) ? 1500 : false)
  })
  const job = jobQ.data || listed || null
  const running = isRunning(job)
  const now = useNow(1000, running)

  // A request from the palette, the status chip or the library moves the studio to the tab asked for; a
  // film that just finished opens on Result. In one commit the finish is the newer news, so it runs last.
  const handled = useRef(null)
  useEffect(() => {
    const r = ui.tabRequest
    if (r && handled.current !== r.n && Date.now() - r.at < 2500) {
      handled.current = r.n
      setTab(r.tab)
    }
  }, [ui.tabRequest])
  const prev = useRef({ id: null, stage: null })
  useEffect(() => {
    const p = prev.current
    if (job && p.id === job.id && p.stage && !TERMINAL.has(p.stage) && job.stage === 'done') setTab('result')
    prev.current = { id: job ? job.id : null, stage: job ? job.stage : null }
    observe(job)
  }, [job && job.id, job && job.stage])

  const badge = id => {
    if (id === 'live' && running) return jsx('span', { className: 'srl-tab-badge', children: pctText(job.pct) })
    if (id === 'result' && job && job.stage === 'done') return jsx('i', { className: 'srl-tab-dot', 'aria-label': 'ready' })
    return null
  }
  let body
  if (tab === 'make') body = jsx(MakeView, { sid, jobs, backendDown, onStarted: j => { selectJob(sid, j.id); setTab('live') } })
  else if (tab === 'live') body = jsx(LiveView, { job, sid, now, onTab: setTab })
  else if (tab === 'board') body = jsx(StoryboardView, { job, sid, onTab: setTab })
  else if (tab === 'result') body = jsx(ResultView, { job, sid, onTab: setTab }, job ? job.id : 'none')
  else body = jsx(LibraryView, { onTab: setTab })

  return jsxs('div', {
    className: cx('srl', `srl-${variant}`),
    children: [
      jsx('style', { children: CSS }),
      jsxs('header', { className: 'srl-head', children: [
        jsxs('div', { className: 'srl-brand', children: [jsx(Icon, { name: 'device-camera-video' }), jsx('span', { children: 'Showreel' })] }),
        jsx(JobPicker, { jobs, value: selectedId, now, onChange: id => selectJob(sid, id) })
      ] }),
      jsx('nav', { className: 'srl-tabs', role: 'tablist', 'aria-label': 'Showreel', children: TABS.map(t => jsxs('button', {
        type: 'button', role: 'tab', className: 'srl-tab', 'aria-selected': tab === t.id, onClick: () => setTab(t.id),
        children: [jsx(Icon, { name: t.icon }), jsx('span', { children: t.label }), badge(t.id)]
      }, t.id)) }),
      jsxs('div', { className: 'srl-body', role: 'tabpanel', children: [
        backendDown ? jsx(Alert, { tone: 'warn', children: jsxs('div', { className: 'srl-stack', children: [
          jsx('b', { children: 'The Showreel backend is not running.' }),
          jsx('span', { children: 'Enable the showreel plugin for the agent too (Capabilities → Plugins, or `hermes plugins enable showreel`), then restart Hermes. The pane needs it to read sessions and render.' })
        ] }) }) : null,
        jsx('div', { className: 'srl-view', children: body })
      ] })
    ]
  })
}

// ── status-bar chip ────────────────────────────────────────────────────────────────────────────────
function StatusChip() {
  const q = useApi(qk('active'), '/jobs/active', {
    refetchInterval: (a, b) => {
      const d = dataOf(a, b)
      if (!d) return 60000
      return (d.jobs || []).some(isRunning) ? 2500 : 15000
    }
  })
  const jobs = (q.data && q.data.jobs) || []
  const sid = useSessionId()
  const mine = j => j.session_id === sid
  const runningJobs = jobs.filter(isRunning)
  const live = runningJobs.find(mine) || runningJobs[0]
  const ready = !live && (jobs.find(j => j.stage === 'done' && mine(j)) || jobs.find(j => j.stage === 'done'))
  useEffect(() => {
    jobs.forEach(observe)
  }, [jobs.map(j => `${j.id}:${j.stage}`).join(',')])
  const job = live || ready
  if (!job) return null
  const open = () => {
    selectJob(job.session_id, job.id)
    requestTab(live ? 'live' : 'result')
    navigate(ROUTE)
  }
  const label = live ? `${job.title || 'Showreel'}: ${stageLabel(job.stage, job)} ${pctText(job.pct)}${job.eta_s ? ` · ${fmtEta(job.eta_s)}` : ''}` : `${job.title || 'Your showreel'} is ready`
  return jsxs('span', { className: 'srl-chipwrap', children: [
    jsx('style', { children: CHIP_CSS }),
    withTip(label, jsxs('button', {
      type: 'button', className: 'srl-chip', 'data-st': live ? 'running' : 'done', onClick: open, 'aria-label': label,
      children: [
        live ? jsx('i', { className: 'srl-chip-spin', 'aria-hidden': true }) : jsx(Icon, { name: 'pass-filled' }),
        jsx('span', { children: live ? `Showreel ${pctText(job.pct)}${runningJobs.length > 1 ? ` +${runningJobs.length - 1}` : ''}` : 'Showreel ready' }),
        live ? jsx('i', { className: 'srl-chip-bar', children: jsx('b', { style: { width: pctText(job.pct) } }) }) : null
      ]
    }))
  ] })
}

// ── tool media card (showreel_render / showreel_status results in the transcript) ──────────────────
function resultObject(result) {
  if (result && typeof result === 'object') return result
  try {
    const o = JSON.parse(String(result || ''))
    return o && typeof o === 'object' ? o : {}
  } catch (e) {
    return {}
  }
}

function ReelCard(props) {
  const { file, fallback } = props
  if (!file || file.kind !== 'video') return fallback
  const r = resultObject(props.result)
  const jobId = typeof r.job_id === 'string' ? r.job_id : ''
  const meta = [r.style, r.duration_s ? fmtDur(r.duration_s) : '', r.aspect || ''].filter(Boolean).join(' · ')
  const open = () => {
    if (jobId) {
      selectJob(r.session_id || (sdk.host && sdk.host.state && sdk.host.state.focusedStoredSessionId && sdk.host.state.focusedStoredSessionId.get()), jobId)
      requestTab('result')
    }
    navigate(ROUTE)
  }
  const copyPost = async () => {
    try {
      const p = await api(`/jobs/${jobId}/post-text`)
      notify((await copyText(p.text)) ? 'success' : 'error', 'Post text copied')
    } catch (e) {
      notify('error', `No post text: ${e.message}`)
    }
  }
  return jsxs('figure', {
    className: 'srl-reel',
    children: [
      jsx('style', { children: CARD_CSS }),
      jsxs('figcaption', { className: 'srl-reel-head', children: [
        jsx(Icon, { name: 'device-camera-video' }),
        jsx('b', { children: r.title || file.name || 'Showreel' }),
        meta ? jsx('span', { children: meta }) : null
      ] }),
      fallback,
      jsxs('div', { className: 'srl-reel-actions', children: [
        jsx(Btn, { variant: 'ghost', size: 'xs', icon: 'folder-opened', onClick: () => reveal(file.path), children: 'Reveal' }),
        jsx(Btn, { variant: 'ghost', size: 'xs', icon: 'device-camera-video', onClick: open, children: 'Open in Showreel' }),
        jobId ? jsx(Btn, { variant: 'ghost', size: 'xs', icon: 'copy', onClick: copyPost, children: 'Copy post text' }) : null
      ] })
    ]
  })
}

// ── palette ────────────────────────────────────────────────────────────────────────────────────────
async function quickMake(mode) {
  const sid = sdk.host && sdk.host.state && sdk.host.state.focusedStoredSessionId ? sdk.host.state.focusedStoredSessionId.get() : null
  const prefs = { ...loadPrefs(), mode }
  const job = await startFilm(sid, optionsFrom(prefs, ''))
  if (job) {
    requestTab('live')
    notify('success', `Showreel started: ${modeLabel(mode).toLowerCase()} in ${prefs.style}, ${prefs.seconds} s. Progress is in the status bar.`)
  }
}

function paletteEntries() {
  const make = (id, label, mode, keywords) => ({ id, area: sdk.PALETTE_AREA, data: { id: `${ID}.${id}`, label, keywords, run: () => { quickMake(mode) } } })
  return [
    make('trailer', 'Showreel: make a trailer of this chat', 'product', ['video', 'trailer', 'promo', 'showreel', 'film']),
    make('lore', 'Showreel: make the lore (making-of) of this chat', 'making_of', ['lore', 'making of', 'behind the scenes', 'bts', 'video']),
    make('speedrun', 'Showreel: make a speedrun of this chat', 'speedrun', ['speedrun', 'any%', 'timer', 'video']),
    { id: 'open', area: sdk.PALETTE_AREA, data: { id: `${ID}.open`, label: 'Showreel: open the studio', keywords: ['showreel', 'video', 'studio', 'library'], run: () => navigate(ROUTE) } }
  ]
}

// ── styles (theme variables only; scoped under .srl / .srl-chip / .srl-reel) ─────────────────────────
const CSS = `
.srl{--srl-line:var(--ui-stroke-tertiary,color-mix(in srgb,currentColor 14%,transparent));--srl-soft:color-mix(in srgb,var(--ui-text-primary) 5%,transparent);--srl-mono:var(--dt-font-mono,ui-monospace,monospace);
 display:flex;flex-direction:column;height:100%;min-height:0;color:var(--ui-text-primary);font-size:12.5px;line-height:1.45}
.srl-page{max-width:1280px;margin:0 auto;width:100%}
.srl-head{display:flex;align-items:center;gap:10px;padding:10px 12px 6px;min-width:0}
.srl-page .srl-head{padding:18px 20px 8px}
.srl-brand{display:flex;align-items:center;gap:7px;font-weight:600;font-size:13px;letter-spacing:.01em;flex:none}
.srl-page .srl-brand{font-size:16px}
.srl-brand .codicon{color:var(--ui-accent)}
.srl-picker{margin-left:auto;min-width:0;max-width:62%;flex:0 1 auto;font:inherit;font-size:11.5px;color:var(--ui-text-secondary);background:transparent;border:0;box-shadow:inset 0 0 0 1px var(--srl-line);border-radius:4px;padding:3px 6px;text-overflow:ellipsis}
.srl-picker:focus-visible{outline:2px solid var(--ui-accent);outline-offset:1px}
.srl-tabs{display:flex;gap:2px;padding:0 8px;border-bottom:1px solid var(--srl-line);overflow-x:auto;scrollbar-width:none;flex:none}
.srl-page .srl-tabs{padding:0 16px}
.srl-tab{appearance:none;border:0;background:transparent;color:var(--ui-text-secondary);padding:7px 8px 8px;font:inherit;font-size:12px;border-bottom:2px solid transparent;margin-bottom:-1px;cursor:pointer;white-space:nowrap;display:inline-flex;gap:5px;align-items:center}
.srl-tab .codicon{font-size:13px;opacity:.8}
.srl-tab:hover{color:var(--ui-text-primary)}
.srl-tab[aria-selected=true]{color:var(--ui-text-primary);border-bottom-color:var(--ui-accent)}
.srl-tab:focus-visible{outline:2px solid var(--ui-accent);outline-offset:-2px}
.srl-tab-badge{font-size:10.5px;font-variant-numeric:tabular-nums;padding:0 5px;border-radius:8px;background:color-mix(in srgb,var(--ui-accent) 18%,transparent);color:var(--ui-text-primary)}
.srl-tab-dot{width:6px;height:6px;border-radius:50%;background:var(--ui-accent)}
.srl-body{flex:1;min-height:0;overflow:auto;padding:12px;container-type:inline-size}
.srl-page .srl-body{padding:18px 20px 28px}
.srl-view{display:flex;flex-direction:column;gap:14px}
.srl-section{display:flex;flex-direction:column;gap:7px}
.srl-label{display:flex;align-items:baseline;justify-content:space-between;gap:8px;font-size:10.5px;text-transform:uppercase;letter-spacing:.09em;color:var(--ui-text-tertiary);font-weight:600}
.srl-label-aside{text-transform:none;letter-spacing:0;font-weight:400;font-size:11px}
.srl-stack{display:flex;flex-direction:column;gap:8px;min-width:0}
.srl-hint{color:var(--ui-text-tertiary);font-size:11.5px}
.srl-link{appearance:none;border:0;background:none;padding:0;font:inherit;color:var(--ui-accent);cursor:pointer;text-decoration:underline;text-underline-offset:3px;text-decoration-color:color-mix(in srgb,var(--ui-accent) 40%,transparent)}
.srl-link:hover{text-decoration-color:currentColor}
.srl-actions{display:flex;flex-wrap:wrap;align-items:center;gap:6px}
.srl-tipwrap{display:inline-flex}
.srl-segwrap{display:inline-flex;max-width:100%;overflow-x:auto}
.srl-seg{display:inline-flex;gap:2px;padding:2px;border-radius:4px;background:var(--srl-soft)}
.srl-seg-opt{appearance:none;border:0;background:transparent;color:var(--ui-text-secondary);font:inherit;font-size:12px;padding:3px 9px;border-radius:3px;cursor:pointer}
.srl-seg-opt[aria-checked=true]{background:var(--ui-bg-card,var(--dt-background));color:var(--ui-text-primary);box-shadow:0 0 0 1px var(--srl-line)}
.srl-input{font:inherit;color:inherit;background:transparent;border:0;box-shadow:inset 0 0 0 1px var(--srl-line);border-radius:4px;padding:5px 7px;width:100%}
.srl-btn{display:inline-flex;align-items:center;gap:6px;font:inherit;font-size:12px;padding:5px 10px;border-radius:3px;border:0;cursor:pointer;color:var(--ui-text-primary);background:var(--srl-soft)}
.srl-btn-default{background:var(--ui-accent);color:var(--dt-background)}
.srl-btn:disabled{opacity:.5;cursor:default}
.srl-pill{font-size:10.5px;padding:1px 7px;border-radius:9px;background:var(--srl-soft);color:var(--ui-text-secondary);white-space:nowrap;text-transform:none;letter-spacing:0;font-weight:500}
.srl-pill[data-tone=accent]{background:color-mix(in srgb,var(--ui-accent) 20%,transparent);color:var(--ui-text-primary)}
.srl-pill[data-tone=ok]{background:color-mix(in srgb,var(--ui-green,var(--ui-accent)) 18%,transparent);color:var(--ui-text-primary)}
.srl-alert{border-radius:6px;padding:9px 11px;font-size:12px;box-shadow:inset 3px 0 0 var(--ui-yellow,var(--ui-accent));background:color-mix(in srgb,var(--ui-yellow,var(--ui-accent)) 7%,transparent)}
.srl-alert[data-tone=error]{box-shadow:inset 3px 0 0 var(--ui-red,var(--ui-accent));background:color-mix(in srgb,var(--ui-red,var(--ui-accent)) 7%,transparent)}
.srl-alert[data-tone=info]{box-shadow:inset 3px 0 0 var(--ui-accent);background:color-mix(in srgb,var(--ui-accent) 6%,transparent)}
.srl-alert code{font-family:var(--srl-mono);font-size:11px;color:var(--ui-text-tertiary)}
.srl-empty{display:flex;flex-direction:column;align-items:center;text-align:center;gap:6px;padding:36px 16px;color:var(--ui-text-secondary)}
.srl-empty-icon{font-size:22px;color:var(--ui-text-quaternary,var(--ui-text-tertiary))}
.srl-empty-icon .codicon{font-size:26px}
.srl-empty-title{font-weight:600;color:var(--ui-text-primary)}
.srl-empty-body{max-width:340px;font-size:12px;color:var(--ui-text-tertiary)}
.srl-spin{display:inline-block;width:11px;height:11px;border-radius:50%;border:1.6px solid color-mix(in srgb,var(--ui-accent) 25%,transparent);border-top-color:var(--ui-accent);animation:srl-rot .8s linear infinite;flex:none}
@keyframes srl-rot{to{transform:rotate(360deg)}}

/* Make */
.srl-make{display:grid;gap:16px;grid-template-columns:minmax(0,1fr)}
.srl-make-main,.srl-make-side{display:flex;flex-direction:column;gap:16px;min-width:0}
@container (min-width:760px){.srl-make{grid-template-columns:minmax(0,1.55fr) minmax(280px,1fr);align-items:start}.srl-make-side{position:sticky;top:0}}
.srl-gallery{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:9px;align-items:stretch}
@container (min-width:760px){.srl-gallery{grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:12px}}
.srl-card{position:relative;display:flex;flex-direction:column;width:100%;height:100%;justify-content:flex-start;border-radius:8px;overflow:hidden;background:var(--srl-soft);box-shadow:inset 0 0 0 1px var(--srl-line);cursor:pointer;text-align:left;padding:0;border:0;color:inherit;font:inherit;transition:box-shadow .15s,transform .15s}
button.srl-card:hover{transform:translateY(-1px);box-shadow:inset 0 0 0 1px var(--ui-stroke-secondary,var(--srl-line)),0 6px 16px -10px color-mix(in srgb,var(--dt-background) 80%,transparent)}
.srl-card[aria-pressed=true]{box-shadow:inset 0 0 0 2px var(--ui-accent)}
.srl-card:focus-visible{outline:2px solid var(--ui-accent);outline-offset:2px}
.srl-card-media{position:relative;aspect-ratio:16/9;overflow:hidden;background:color-mix(in srgb,var(--ui-text-primary) 6%,transparent)}
.srl-card-media img,.srl-card-media video{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;display:block;z-index:1}
.srl-gallery .srl-card-media img,.srl-gallery .srl-card-media video{opacity:0;transition:opacity .3s}
.srl-gallery .srl-card-media [data-shown]{opacity:1}
.srl-lib .srl-card-media img{opacity:1}
.srl-card-check{position:absolute;right:6px;top:6px;width:18px;height:18px;border-radius:50%;display:grid;place-items:center;background:var(--ui-accent);color:var(--dt-background);font-size:11px;z-index:2}
.srl-card-meta{padding:7px 9px 9px;display:flex;flex-direction:column;gap:3px;min-width:0;flex:1 1 auto}
.srl-card-name{display:flex;align-items:center;gap:6px;font-weight:600;font-size:12.5px}
.srl-card-blurb{color:var(--ui-text-tertiary);font-size:11.5px;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.srl-soon{font-size:9.5px;font-weight:500;text-transform:uppercase;letter-spacing:.08em;color:var(--ui-text-tertiary);padding:0 5px;border-radius:7px;box-shadow:inset 0 0 0 1px var(--srl-line)}
.srl-form{display:flex;flex-direction:column;gap:9px}
.srl-row{display:flex;align-items:center;justify-content:space-between;gap:10px;min-width:0}
.srl-row>span:first-child{color:var(--ui-text-secondary);flex:none}
.srl-row.is-dim{opacity:.55}
.srl-examples{display:flex;flex-direction:column;gap:4px}
.srl-example{appearance:none;border:0;background:transparent;text-align:left;font:inherit;font-size:11.5px;color:var(--ui-text-tertiary);padding:3px 6px;border-radius:4px;cursor:pointer;font-style:italic}
.srl-example::before{content:"“"}
.srl-example::after{content:"”"}
.srl-example:hover{background:var(--srl-soft);color:var(--ui-text-secondary)}
.srl-make-go{display:flex;flex-direction:column;align-items:stretch;gap:8px;padding:12px;border-radius:8px;background:color-mix(in srgb,var(--ui-accent) 6%,transparent);box-shadow:inset 0 0 0 1px color-mix(in srgb,var(--ui-accent) 22%,transparent)}
.srl-make-go button{justify-content:center}
.srl-make-go .srl-tipwrap{display:flex}
.srl-make-go .srl-tipwrap>button{flex:1}
.srl-summary{font-size:11.5px;color:var(--ui-text-secondary);text-align:center}

/* placeholders: drawn previews from the theme accent (a hue turn per style) */
.srl-ph{position:absolute;inset:0;overflow:hidden;--tone:oklch(from var(--ui-accent) clamp(.5,l,.72) max(c,.09) calc(h + var(--rot,0)));--ink:var(--ui-text-primary);--ground:var(--dt-background)}
.srl-ph i,.srl-ph b{position:absolute;display:block}
.srl-ph-launch{background:radial-gradient(90% 75% at 50% 115%,color-mix(in srgb,var(--tone) 42%,transparent),transparent 70%),color-mix(in srgb,var(--ink) 7%,var(--ground))}
.srl-ph-launch .p{width:42%;height:48%;border-radius:5px;background:color-mix(in srgb,var(--ink) 86%,var(--ground));box-shadow:0 12px 16px -10px color-mix(in srgb,var(--ground) 80%,transparent);transform:perspective(260px) rotateX(16deg) rotateY(-16deg)}
.srl-ph-launch .p::before{content:"";position:absolute;left:10%;top:15%;width:46%;height:10%;border-radius:2px;background:var(--tone)}
.srl-ph-launch .p::after{content:"";position:absolute;left:10%;right:12%;top:38%;height:42%;background:repeating-linear-gradient(color-mix(in srgb,var(--ground) 35%,transparent) 0 3px,transparent 3px 8px)}
.srl-ph-launch .p.a{left:11%;top:20%;animation:srl-float 5s ease-in-out infinite}
.srl-ph-launch .p.b{right:9%;top:30%;width:36%;height:42%;animation:srl-float 5s ease-in-out -2.5s infinite;transform:perspective(260px) rotateX(16deg) rotateY(18deg)}
.srl-ph-launch .shine{inset:0;background:linear-gradient(105deg,transparent 40%,color-mix(in srgb,var(--ink) 14%,transparent) 50%,transparent 60%);background-size:250% 100%;animation:srl-sweep 4.5s ease-in-out infinite}
@keyframes srl-float{0%,100%{translate:0 0}50%{translate:0 -7%}}
@keyframes srl-sweep{0%{background-position:120% 0}60%,100%{background-position:-120% 0}}
.srl-ph-cinematic{background:radial-gradient(55% 60% at 68% 42%,color-mix(in srgb,var(--tone) 30%,transparent),transparent 70%),color-mix(in srgb,var(--ground) 88%,var(--tone))}
.srl-ph-cinematic .bokeh{inset:0;background:radial-gradient(circle at 18% 30%,color-mix(in srgb,var(--tone) 50%,transparent) 0 3px,transparent 4px),radial-gradient(circle at 82% 70%,color-mix(in srgb,var(--tone) 40%,transparent) 0 5px,transparent 6px),radial-gradient(circle at 60% 18%,color-mix(in srgb,var(--ink) 30%,transparent) 0 2px,transparent 3px);filter:blur(1px);animation:srl-drift 9s ease-in-out infinite alternate}
.srl-ph-cinematic .c{width:30%;height:40%;top:30%;border-radius:3px;background:linear-gradient(160deg,color-mix(in srgb,var(--ink) 70%,var(--tone)),color-mix(in srgb,var(--tone) 60%,var(--ground)));box-shadow:0 0 14px color-mix(in srgb,var(--tone) 45%,transparent)}
.srl-ph-cinematic .c1{left:8%;transform:perspective(200px) rotateY(32deg) scale(.82);filter:blur(1.2px);opacity:.7}
.srl-ph-cinematic .c2{left:35%;transform:perspective(200px) rotateY(-8deg);animation:srl-push 6s ease-in-out infinite}
.srl-ph-cinematic .c3{right:6%;transform:perspective(200px) rotateY(-34deg) scale(.86);filter:blur(.8px);opacity:.8}
.srl-ph-cinematic .lb{left:0;right:0;height:11%;background:var(--ground)}
.srl-ph-cinematic .lb.t{top:0}.srl-ph-cinematic .lb.b{bottom:0}
@keyframes srl-drift{to{transform:translate(-4%,3%)}}
@keyframes srl-push{0%,100%{scale:1}50%{scale:1.07}}
.srl-ph-pixel{image-rendering:pixelated;background:linear-gradient(to bottom,color-mix(in srgb,var(--tone) 45%,var(--ground)) 0 34%,color-mix(in srgb,var(--tone) 32%,var(--ground)) 34% 50%,color-mix(in srgb,var(--tone) 20%,var(--ground)) 50% 64%,transparent 64%)}
.srl-ph-pixel .stars{inset:0 0 40% 0;background:radial-gradient(circle,var(--ink) 0 1px,transparent 1.5px) 0 0/23px 17px;opacity:.5;animation:srl-blink 1.6s steps(2) infinite}
.srl-ph-pixel .ground{left:0;right:0;bottom:0;height:36%;background:repeating-linear-gradient(90deg,color-mix(in srgb,var(--ink) 30%,var(--ground)) 0 8px,color-mix(in srgb,var(--ink) 18%,var(--ground)) 8px 16px);box-shadow:inset 0 4px 0 color-mix(in srgb,var(--tone) 70%,var(--ink));animation:srl-scroll 1.2s steps(4) infinite}
.srl-ph-pixel .hero{left:40%;bottom:36%;width:4px;height:4px;color:var(--tone);background:currentColor;box-shadow:4px 0,8px 0,12px 0,16px 0,-4px 4px,0 4px,4px 4px var(--ink),8px 4px var(--ink),12px 4px,16px 4px,20px 4px,-4px 8px,0 8px,4px 8px,8px 8px,12px 8px,16px 8px,20px 8px,0 12px var(--ink),16px 12px var(--ink);scale:1.4;transform-origin:bottom left;animation:srl-hop .6s steps(2) infinite}
.srl-ph-pixel .hp{left:7%;top:9%;width:30%;height:7px;box-shadow:0 0 0 2px var(--ink);background:linear-gradient(90deg,var(--tone) 0 var(--hp,70%),color-mix(in srgb,var(--ground) 60%,transparent) var(--hp,70%));animation:srl-hp 3s steps(6) infinite}
@keyframes srl-blink{50%{opacity:.25}}
@keyframes srl-scroll{to{background-position:-16px 0}}
@keyframes srl-hop{50%{translate:0 -4px}}
@keyframes srl-hp{0%{--hp:90%;filter:none}50%{filter:brightness(1.3)}100%{--hp:30%}}
.srl-ph-terminal{background:color-mix(in srgb,var(--ground) 86%,var(--tone));font-family:var(--srl-mono);color:var(--tone);text-shadow:0 0 6px color-mix(in srgb,var(--tone) 55%,transparent)}
.srl-ph-terminal .tx{position:absolute;left:9%;top:16%;right:6%;font-size:10.5px;line-height:1.55;white-space:nowrap}
.srl-ph-terminal .ok{color:color-mix(in srgb,var(--tone) 60%,var(--ink))}
.srl-ph-terminal .cur{position:static;display:inline-block;width:.6em;height:1em;margin-left:3px;vertical-align:-.15em;background:currentColor;animation:srl-blink 1s steps(1) infinite}
.srl-ph-terminal .tx>div:last-child{overflow:hidden;width:0;animation:srl-type 3.2s steps(14) infinite}
.srl-ph-terminal .scan{inset:0;background:repeating-linear-gradient(transparent 0 2px,color-mix(in srgb,var(--ground) 30%,transparent) 2px 3px);box-shadow:inset 0 0 26px color-mix(in srgb,var(--ground) 80%,transparent)}
@keyframes srl-type{0%{width:0}55%,100%{width:14ch}}
.srl-ph-blueprint{background-color:color-mix(in srgb,var(--tone) 34%,var(--ground));background-image:linear-gradient(color-mix(in srgb,var(--ink) 14%,transparent) 1px,transparent 1px),linear-gradient(90deg,color-mix(in srgb,var(--ink) 14%,transparent) 1px,transparent 1px);background-size:12px 12px}
.srl-ph svg{position:absolute;inset:0;width:100%;height:100%}
.srl-ph-blueprint svg *{fill:none;stroke:color-mix(in srgb,var(--ink) 85%,transparent);stroke-width:1.2;stroke-dasharray:260;stroke-dashoffset:260;animation:srl-draw 4.5s ease-in-out infinite}
.srl-ph-blueprint svg .arc{stroke-dasharray:3 3;stroke-dashoffset:0;animation:none;opacity:.6}
@keyframes srl-draw{0%{stroke-dashoffset:260}55%,85%{stroke-dashoffset:0}100%{stroke-dashoffset:-260}}
.srl-ph-comic{background:radial-gradient(color-mix(in srgb,var(--tone) 55%,transparent) 1.3px,transparent 1.8px) 0 0/7px 7px,color-mix(in srgb,var(--tone) 16%,var(--ink))}
.srl-ph-comic .panel{inset:7%;box-shadow:0 0 0 3px var(--ground);clip-path:polygon(0 0,100% 0,100% 100%,0 100%,0 0,48% 0,40% 100%,44% 100%,52% 0)}
.srl-ph-comic .burst{left:50%;top:50%;translate:-50% -50%;width:52%;aspect-ratio:1.5;display:grid;place-items:center;font:italic 900 15px/1 var(--dt-font-sans,system-ui);letter-spacing:.04em;color:var(--ground);background:var(--tone);clip-path:polygon(50% 0,61% 22%,86% 8%,76% 34%,100% 42%,78% 56%,94% 82%,66% 72%,56% 100%,46% 76%,20% 94%,28% 66%,0 58%,22% 44%,6% 18%,34% 26%);animation:srl-pop 2.4s cubic-bezier(.3,1.6,.5,1) infinite}
@keyframes srl-pop{0%{scale:.4;rotate:-12deg}18%,80%{scale:1;rotate:-4deg}100%{scale:.4;rotate:-12deg}}
.srl-ph-ink{background:radial-gradient(120% 90% at 30% 20%,color-mix(in srgb,var(--ink) 92%,var(--tone)),color-mix(in srgb,var(--ink) 78%,var(--ground)))}
.srl-ph-ink .enso{fill:none;stroke:var(--ground);stroke-width:7;stroke-linecap:round;stroke-dasharray:240;stroke-dashoffset:240;animation:srl-draw 5s cubic-bezier(.6,0,.3,1) infinite;opacity:.88}
.srl-ph-ink .seal{fill:var(--ui-red,var(--tone))}
.srl-ph-nature{background:linear-gradient(to bottom,color-mix(in srgb,var(--tone) 50%,var(--ground)),color-mix(in srgb,oklch(from var(--tone) l c calc(h + 60)) 45%,var(--ground)) 62%)}
.srl-ph-nature .sun{fill:color-mix(in srgb,var(--ink) 80%,var(--tone));filter:blur(.6px)}
.srl-ph-nature .h1{fill:color-mix(in srgb,var(--tone) 45%,var(--ground))}
.srl-ph-nature .h2{fill:color-mix(in srgb,oklch(from var(--tone) l c calc(h + 140)) 50%,var(--ground))}
.srl-ph-nature .petal{width:5px;height:3px;border-radius:50%;background:color-mix(in srgb,var(--ink) 80%,var(--tone));animation:srl-petal 6s linear infinite}
.srl-ph-nature .p1{left:10%;top:10%}.srl-ph-nature .p2{left:45%;top:-5%;animation-delay:-2s}.srl-ph-nature .p3{left:75%;top:5%;animation-delay:-4s}
@keyframes srl-petal{to{translate:-40px 90px;rotate:260deg}}
.srl-ph-other{background:linear-gradient(135deg,color-mix(in srgb,var(--tone) 40%,var(--ground)),color-mix(in srgb,var(--tone) 12%,var(--ground)));display:grid;place-items:center}
.srl-ph-other .word{position:static;font-weight:700;font-size:15px;letter-spacing:.04em;color:color-mix(in srgb,var(--ink) 85%,transparent);text-transform:capitalize}

/* Live */
.srl-live,.srl-result{display:grid;gap:18px;grid-template-columns:minmax(0,1fr)}
@container (min-width:860px){.srl-live:has(.srl-dir){grid-template-columns:minmax(260px,.8fr) minmax(0,1.4fr);align-items:start}.srl-result{grid-template-columns:minmax(0,1.5fr) minmax(260px,1fr);align-items:start}}
.srl-live-main,.srl-result-main,.srl-result-side{display:flex;flex-direction:column;gap:12px;min-width:0}
.srl-jobhead{display:flex;flex-direction:column;gap:2px}
.srl-jobtitle{font-size:15px;font-weight:650;letter-spacing:-.005em}
.srl-page .srl-jobtitle{font-size:19px}
.srl-jobmeta{color:var(--ui-text-tertiary);font-size:11.5px}
.srl-progress-block{display:flex;flex-direction:column;gap:5px}
.srl-progress-top{display:flex;align-items:baseline;justify-content:space-between;gap:8px}
.srl-pct{font-size:22px;font-weight:650;font-variant-numeric:tabular-nums;letter-spacing:-.01em}
.srl-eta{color:var(--ui-text-secondary);font-size:12px;font-variant-numeric:tabular-nums}
.srl-progress{position:relative;height:6px;border-radius:3px;background:color-mix(in srgb,var(--ui-text-primary) 10%,transparent);overflow:hidden}
.srl-progress>i{display:block;height:100%;border-radius:inherit;background:var(--ui-accent);transition:width .5s ease}
.srl-progress[data-live]::after{content:"";position:absolute;inset:0;background:linear-gradient(90deg,transparent,color-mix(in srgb,var(--ui-text-primary) 22%,transparent),transparent);background-size:40% 100%;background-repeat:no-repeat;animation:srl-sheen 1.8s linear infinite}
[data-st=failed] .srl-progress>i{background:var(--ui-red,var(--ui-accent))}
[data-st=cancelled] .srl-progress>i{background:var(--ui-text-tertiary)}
@keyframes srl-sheen{from{background-position:-40% 0}to{background-position:140% 0}}
.srl-note{color:var(--ui-text-secondary);font-size:12px}
.srl-stages{list-style:none;margin:0;padding:0;display:flex;flex-direction:column}
.srl-stages li{display:grid;grid-template-columns:16px minmax(0,1fr) auto;gap:9px;align-items:center;padding:5px 0;color:var(--ui-text-tertiary)}
.srl-stages li[data-st=done],.srl-stages li[data-st=active]{color:var(--ui-text-primary)}
.srl-stages li[data-st=active] .srl-stage-name{font-weight:600}
.srl-mark{width:14px;height:14px;border-radius:50%;display:grid;place-items:center;box-shadow:inset 0 0 0 1.5px var(--srl-line)}
[data-st=done]>.srl-mark{background:var(--ui-accent);box-shadow:none}
[data-st=done]>.srl-mark::after{content:"";width:6px;height:3px;border:solid var(--dt-background);border-width:0 0 1.6px 1.6px;rotate:-45deg;translate:0 -1px}
[data-st=active]>.srl-mark{box-shadow:none}
[data-st=failed]>.srl-mark{background:var(--ui-red,var(--ui-accent));box-shadow:none}
[data-st=stopped]>.srl-mark{background:var(--ui-text-tertiary);box-shadow:none}
.srl-stage-name{display:flex;align-items:center;gap:8px;min-width:0}
.srl-mini{position:relative;display:inline-block;width:52px;height:3px;border-radius:2px;background:color-mix(in srgb,var(--ui-text-primary) 10%,transparent);overflow:hidden}
.srl-mini>b{display:block;height:100%;background:var(--ui-accent);transition:width .4s}
.srl-stage-time{font-size:11px;color:var(--ui-text-tertiary);font-variant-numeric:tabular-nums}
.srl-warnings,.srl-activity{margin:0;padding-left:16px;color:var(--ui-text-secondary);font-size:11.5px;display:flex;flex-direction:column;gap:3px}
.srl-activity{list-style:none;padding:0;font-family:var(--srl-mono);font-size:11px}
.srl-activity li[data-level=warn]{color:var(--ui-text-primary)}
.srl-activity li[data-level=error]{color:var(--ui-text-primary);box-shadow:inset 2px 0 0 var(--ui-red,var(--ui-accent));padding-left:6px}

/* the Director */
.srl-dir{display:flex;flex-direction:column;gap:14px;min-width:0;padding:12px;border-radius:10px;background:color-mix(in srgb,var(--ui-accent) 4%,transparent);box-shadow:inset 0 0 0 1px color-mix(in srgb,var(--ui-accent) 18%,transparent)}
.srl-dir-head{display:flex;align-items:baseline;justify-content:space-between;gap:10px;flex-wrap:wrap}
.srl-dir-title{display:flex;align-items:center;gap:8px;font-weight:650;font-size:13.5px}
.srl-live-dot{width:8px;height:8px;border-radius:50%;background:var(--ui-red,var(--ui-accent));box-shadow:0 0 0 0 color-mix(in srgb,var(--ui-red,var(--ui-accent)) 50%,transparent);animation:srl-pulse 1.6s ease-out infinite}
@keyframes srl-pulse{70%{box-shadow:0 0 0 7px transparent}100%{box-shadow:0 0 0 0 transparent}}
.srl-quote{margin:0;padding:6px 10px;border-left:2px solid var(--ui-accent);font-style:italic;color:var(--ui-text-secondary);font-size:12.5px}
.srl-rail{list-style:none;margin:0;padding:0;display:flex;flex-wrap:wrap;gap:4px}
.srl-rail li{font-size:11px;padding:2px 8px;border-radius:10px;color:var(--ui-text-tertiary);box-shadow:inset 0 0 0 1px var(--srl-line);white-space:nowrap}
.srl-rail li[data-st=done]{color:var(--ui-text-primary);background:color-mix(in srgb,var(--ui-accent) 14%,transparent);box-shadow:none}
.srl-rail li[data-st=active]{color:var(--dt-background);background:var(--ui-accent);box-shadow:none;animation:srl-glow 1.8s ease-in-out infinite}
.srl-rail li[data-st=skip]{opacity:.45}
@keyframes srl-glow{50%{box-shadow:0 0 10px color-mix(in srgb,var(--ui-accent) 60%,transparent)}}
.srl-treat{display:flex;flex-direction:column;gap:6px;padding:12px;border-radius:8px;background:var(--ui-bg-card,var(--srl-soft));box-shadow:inset 0 0 0 1px var(--srl-line)}
.srl-treat-kicker{font-size:10px;text-transform:uppercase;letter-spacing:.12em;color:var(--ui-text-tertiary)}
.srl-treat-title{font-size:16px;font-weight:650;letter-spacing:-.01em}
.srl-treat-log{margin:0;color:var(--ui-text-secondary);font-style:italic}
.srl-acts{display:flex;gap:3px;margin-top:4px}
.srl-act{flex:1 1 0;min-width:0;display:flex;flex-direction:column;gap:1px;padding:6px 8px;border-radius:4px;background:color-mix(in srgb,oklch(from var(--ui-accent) l c calc(h + var(--rot,0))) 20%,transparent);box-shadow:inset 0 2px 0 oklch(from var(--ui-accent) l c calc(h + var(--rot,0)))}
.srl-act b{font-size:11.5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.srl-act span{font-size:10.5px;color:var(--ui-text-tertiary);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.srl-acts .srl-tipwrap{flex:1 1 0;min-width:0;display:flex}
.srl-treat-sig{font-size:12px;color:var(--ui-text-secondary)}
.srl-treat-sig span{display:block;font-size:10px;text-transform:uppercase;letter-spacing:.1em;color:var(--ui-text-tertiary)}
.srl-chips{display:flex;flex-wrap:wrap;gap:5px}
.srl-chip-s{font-size:11px;padding:1px 7px;border-radius:9px;box-shadow:inset 0 0 0 1px var(--srl-line);color:var(--ui-text-secondary)}
.srl-scene-chip{appearance:none;border:0;font:inherit;display:inline-flex;align-items:center;gap:6px;font-size:11.5px;padding:4px 9px;border-radius:5px;background:var(--srl-soft);color:var(--ui-text-primary);box-shadow:inset 0 0 0 1px var(--srl-line);cursor:pointer}
.srl-scene-chip em{font-style:normal;color:var(--ui-text-tertiary);font-size:10.5px}
.srl-scene-chip[data-st=active]{cursor:default;background:color-mix(in srgb,var(--ui-accent) 10%,transparent)}
.srl-scene-chip[data-st=todo]{cursor:default;opacity:.6}
.srl-scene-chip[aria-pressed=true]{box-shadow:inset 0 0 0 1.5px var(--ui-accent)}
.srl-code{margin:0;max-height:300px;overflow:auto;padding:10px;border-radius:6px;font:11px/1.5 var(--srl-mono);background:color-mix(in srgb,var(--dt-background) 70%,var(--ui-text-primary) 4%);box-shadow:inset 0 0 0 1px var(--srl-line);white-space:pre;tab-size:2}
.srl-rounds{display:flex;flex-direction:column;gap:10px}
.srl-round{display:flex;flex-direction:column;gap:6px;padding:10px;border-radius:8px;background:var(--ui-bg-card,var(--srl-soft));box-shadow:inset 0 0 0 1px var(--srl-line)}
.srl-round[data-pass=yes]{box-shadow:inset 0 0 0 1px color-mix(in srgb,var(--ui-green,var(--ui-accent)) 50%,transparent)}
.srl-round-head{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.srl-round-mean{color:var(--ui-text-secondary);font-variant-numeric:tabular-nums;font-size:12px}
.srl-rubric{display:flex;flex-direction:column;gap:4px}
.srl-rub{display:grid;grid-template-columns:minmax(92px,auto) minmax(0,1fr) 26px;gap:8px;align-items:center;font-size:11.5px}
.srl-rub-k{color:var(--ui-text-secondary);white-space:nowrap}
.srl-rub-track{position:relative;height:6px;border-radius:3px;background:color-mix(in srgb,var(--ui-text-primary) 9%,transparent)}
.srl-rub-track i{position:absolute;left:0;top:0;bottom:0;border-radius:3px;background:var(--ui-red,var(--ui-accent));transition:width .6s cubic-bezier(.2,.8,.2,1)}
.srl-rub-track i[data-tone=mid]{background:var(--ui-yellow,var(--ui-accent))}
.srl-rub-track i[data-tone=ok]{background:var(--ui-green,var(--ui-accent))}
.srl-rub-track em{position:absolute;top:-3px;bottom:-3px;width:1.5px;background:var(--ui-text-secondary);opacity:.7}
.srl-rub-v{text-align:right;font-variant-numeric:tabular-nums;color:var(--ui-text-primary)}
.srl-changes{font-size:11.5px;color:var(--ui-text-secondary)}
.srl-changes summary{cursor:pointer;color:var(--ui-text-tertiary)}
.srl-changes ul{margin:6px 0 0;padding-left:16px;display:flex;flex-direction:column;gap:3px}
.srl-sheets{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:8px}
.srl-sheets figure{margin:0;display:flex;flex-direction:column;gap:3px}
.srl-sheets figcaption{font-size:10.5px;color:var(--ui-text-tertiary)}
.srl-sheet{appearance:none;border:0;padding:0;cursor:zoom-in;border-radius:5px;overflow:hidden;background:var(--srl-soft);box-shadow:inset 0 0 0 1px var(--srl-line);aspect-ratio:16/10;display:grid;place-items:center;width:100%}
.srl-sheet img{width:100%;height:100%;object-fit:cover;display:block}
.srl-sheet.is-open{box-shadow:inset 0 0 0 2px var(--ui-accent)}
.srl-sheet-big .srl-sheet{aspect-ratio:auto;cursor:zoom-out}
.srl-sheet-big .srl-sheet img{height:auto;object-fit:contain}
.srl-sheet-wait{color:var(--ui-text-tertiary);font-size:11px}
.srl-feed{list-style:none;margin:0;padding:6px 0;max-height:320px;overflow:auto;display:flex;flex-direction:column;gap:1px;border-radius:6px;background:color-mix(in srgb,var(--dt-background) 60%,transparent);box-shadow:inset 0 0 0 1px var(--srl-line);font-size:11.5px}
.srl-feed li{display:grid;grid-template-columns:38px auto minmax(0,1fr);gap:8px;padding:3px 10px;align-items:baseline}
.srl-feed li.srl-hint{display:block}
.srl-feed li:last-child{animation:srl-in .35s ease-out}
.srl-feed time{font:10.5px var(--srl-mono);color:var(--ui-text-tertiary);font-variant-numeric:tabular-nums}
.srl-feed li[data-level=debug]{opacity:.6}
.srl-feed li[data-level=warning] .srl-msg,.srl-feed li[data-level=error] .srl-msg{color:var(--ui-text-primary)}
.srl-feed li[data-level=error]{box-shadow:inset 2px 0 0 var(--ui-red,var(--ui-accent))}
.srl-step{font-size:10px;text-transform:uppercase;letter-spacing:.07em;padding:0 6px;border-radius:7px;background:var(--srl-soft);color:var(--ui-text-secondary);white-space:nowrap}
.srl-step[data-step=critic]{background:color-mix(in srgb,var(--ui-yellow,var(--ui-accent)) 18%,transparent)}
.srl-step[data-step=scenes],.srl-step[data-step=dryrun]{background:color-mix(in srgb,var(--ui-accent) 16%,transparent)}
.srl-step[data-step=final]{background:color-mix(in srgb,var(--ui-green,var(--ui-accent)) 18%,transparent)}
.srl-msg{color:var(--ui-text-secondary);overflow-wrap:anywhere}
@keyframes srl-in{from{opacity:0;translate:0 4px}}

/* Storyboard */
.srl-board{display:flex;flex-direction:column;gap:10px}
.srl-board-head{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1.4fr);gap:8px}
.srl-field{display:flex;flex-direction:column;gap:3px;font-size:11px;color:var(--ui-text-tertiary)}
.srl-sb-list{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:7px}
.srl-sb-card{display:grid;grid-template-columns:28px 120px minmax(0,1fr);gap:9px;padding:8px;border-radius:8px;background:var(--srl-soft);box-shadow:inset 0 0 0 1px var(--srl-line);transition:box-shadow .12s,opacity .12s}
.srl-sb-card[data-drag=self]{opacity:.45}
.srl-sb-card[data-drag=over]{box-shadow:inset 0 0 0 1px var(--srl-line),0 -3px 0 var(--ui-accent)}
.srl-sb-card[data-dropped] .srl-sb-thumb,.srl-sb-card[data-dropped] .srl-sb-body{opacity:.4}
.srl-sb-card[data-dropped] .srl-type{text-decoration:line-through}
.srl-sb-grip{display:flex;flex-direction:column;align-items:center;gap:2px;cursor:grab}
.srl-sb-n{font-weight:650;font-variant-numeric:tabular-nums;color:var(--ui-text-secondary);font-size:12px;padding:2px 0}
.srl-icon-btn{appearance:none;border:0;background:transparent;color:var(--ui-text-tertiary);width:22px;height:22px;border-radius:4px;display:grid;place-items:center;cursor:pointer;flex:none}
.srl-icon-btn:hover:not(:disabled){background:var(--srl-soft);color:var(--ui-text-primary)}
.srl-icon-btn:disabled{opacity:.3;cursor:default}
.srl-icon-btn[aria-pressed=true]{color:var(--ui-accent)}
.srl-sb-thumb{border-radius:5px;overflow:hidden;aspect-ratio:16/9;background:color-mix(in srgb,var(--ui-text-primary) 7%,transparent);display:grid;place-items:center;font-size:10px;color:var(--ui-text-tertiary);letter-spacing:.08em}
.srl-sb-thumb img{width:100%;height:100%;object-fit:cover;display:block}
.srl-sb-body{display:flex;flex-direction:column;gap:5px;min-width:0}
.srl-sb-top{display:flex;align-items:center;gap:6px;min-width:0}
.srl-type{font-size:10px;font-weight:650;text-transform:uppercase;letter-spacing:.08em;padding:2px 6px;border-radius:4px;background:color-mix(in srgb,var(--ui-accent) 15%,transparent);flex:none}
.srl-sb-meta{display:flex;flex-wrap:wrap;gap:4px 10px;font-size:10.5px;color:var(--ui-text-tertiary)}
.srl-sb-meta [data-warn]{color:var(--ui-text-primary);box-shadow:inset 0 -1.5px 0 var(--ui-yellow,var(--ui-accent))}
.srl-refs{font-family:var(--srl-mono)}
.srl-board-foot{position:sticky;bottom:-12px;display:flex;flex-wrap:wrap;align-items:center;gap:6px;padding:9px 0;background:linear-gradient(transparent,var(--dt-background) 30%)}
@container (max-width:460px){.srl-sb-card{grid-template-columns:24px 88px minmax(0,1fr);gap:7px 8px}.srl-sb-grip{grid-column:1;grid-row:1/4}.srl-sb-thumb{grid-column:2;grid-row:1;align-self:start}.srl-sb-body{display:contents}.srl-sb-top{grid-column:3;grid-row:1;align-self:center}.srl-sb-body>:not(.srl-sb-top){grid-column:2/4}.srl-board-head{grid-template-columns:1fr}}
.srl-shots{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:4px}
.srl-shots li{display:grid;grid-template-columns:76px minmax(0,auto) minmax(0,1fr);gap:8px;align-items:baseline;font-size:12px}
.srl-shots time{font:11px var(--srl-mono);color:var(--ui-text-tertiary)}
.srl-shots code{font:11px var(--srl-mono);color:var(--ui-text-secondary);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}

/* Result */
.srl-player{border-radius:8px;overflow:hidden;min-height:60px}
.srl-player video{max-width:100%;max-height:70vh}
.srl-post{margin:0;white-space:pre-wrap;font:12px/1.5 var(--dt-font-sans,system-ui);padding:10px 12px;border-radius:6px;background:var(--srl-soft);box-shadow:inset 0 0 0 1px var(--srl-line);color:var(--ui-text-secondary)}

/* Library */
.srl-library-head{display:flex;align-items:flex-start;justify-content:space-between;gap:10px}
.srl-lib-card{cursor:default}
.srl-lib-card .srl-actions{margin-top:4px}
.srl-score{margin-left:auto;font-size:11px;font-variant-numeric:tabular-nums;color:var(--ui-text-secondary)}
.srl-params{font:10.5px var(--srl-mono);color:var(--ui-text-tertiary);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}

@media (prefers-reduced-motion:reduce){.srl *,.srl *::before,.srl *::after{animation:none!important;transition:none!important}}
`

const CHIP_CSS = `
.srl-chipwrap{display:inline-flex;align-items:center}
.srl-chip{display:inline-flex;align-items:center;gap:6px;height:20px;padding:0 7px;border:0;border-radius:3px;background:transparent;color:var(--ui-text-secondary);font:inherit;font-size:11.5px;font-variant-numeric:tabular-nums;white-space:nowrap;cursor:pointer}
.srl-chip:hover{background:color-mix(in srgb,var(--ui-accent) 14%,transparent);color:var(--ui-text-primary)}
.srl-chip:focus-visible{outline:2px solid var(--ui-accent);outline-offset:1px}
.srl-chip[data-st=done] .codicon{color:var(--ui-accent)}
.srl-chip-spin{display:inline-block;width:10px;height:10px;border-radius:50%;border:1.5px solid color-mix(in srgb,var(--ui-accent) 25%,transparent);border-top-color:var(--ui-accent);animation:srl-chip-rot .8s linear infinite}
.srl-chip-bar{display:inline-block;width:40px;height:4px;border-radius:2px;background:color-mix(in srgb,var(--ui-text-primary) 12%,transparent);overflow:hidden}
.srl-chip-bar>b{display:block;height:100%;background:var(--ui-accent);transition:width .4s}
@keyframes srl-chip-rot{to{transform:rotate(360deg)}}
@media (prefers-reduced-motion:reduce){.srl-chip-spin{animation:none}.srl-chip-bar>b{transition:none}}
`

const CARD_CSS = `
.srl-reel{margin:0;max-width:640px;border-radius:10px;overflow:hidden;box-shadow:inset 0 0 0 1px var(--ui-stroke-tertiary,color-mix(in srgb,currentColor 14%,transparent));background:color-mix(in srgb,var(--ui-accent) 3%,transparent)}
.srl-reel-head{display:flex;align-items:center;gap:7px;padding:8px 11px;font-size:12.5px}
.srl-reel-head .codicon{color:var(--ui-accent)}
.srl-reel-head span{color:var(--ui-text-tertiary);font-size:11.5px;margin-left:auto}
.srl-reel-actions{display:flex;flex-wrap:wrap;gap:4px;padding:6px 8px}
`

// ── registration ───────────────────────────────────────────────────────────────────────────────────
export default {
  id: ID,
  name: 'Showreel',
  register(ctx) {
    const missing = ['host', 'useQuery', 'queryClient'].filter(name => sdk[name] == null)
    if (missing.length) {
      throw new Error(`Showreel needs a newer Hermes Desktop: the plugin SDK has no ${missing.join(', ')}.`)
    }
    CTX = ctx
    ctx.onDispose(() => {
      CTX = null
      notified.clear()
      seenRunning.clear()
      throttles.clear()
    })
    const items = [
      { id: 'pane', area: sdk.PANES_AREA || 'panes', title: 'Showreel', data: { placement: 'right', width: '400px' }, render: () => jsx(Studio, { variant: 'pane' }) }
    ]
    if (sdk.ROUTES_AREA) items.push({ id: 'page', area: sdk.ROUTES_AREA, data: { path: ROUTE }, render: () => jsx(Studio, { variant: 'page' }) })
    if (sdk.SIDEBAR_NAV_AREA) items.push({ id: 'nav', area: sdk.SIDEBAR_NAV_AREA, data: { path: ROUTE, label: 'Showreel', codicon: 'device-camera-video' } })
    if (sdk.PALETTE_AREA) items.push(...paletteEntries())
    if (sdk.STATUSBAR_AREAS && sdk.STATUSBAR_AREAS.right) items.push({ id: 'progress', area: sdk.STATUSBAR_AREAS.right, order: 130, render: () => jsx(StatusChip, {}) })
    // Hermes >= 0.22.6: draw our own card around the core player for videos our tools produced.
    if (typeof sdk.TOOL_MEDIA_RENDERER_AREA === 'string') {
      items.push({ id: 'reel-card', area: sdk.TOOL_MEDIA_RENDERER_AREA, data: { tools: ['showreel_render', 'showreel_status'], render: props => jsx(ReelCard, props) } })
    }
    if (typeof ctx.registerMany === 'function') ctx.registerMany(items)
    else items.forEach(item => ctx.register(item))
    ctx.onEvent(PROGRESS_EVENT, onProgress)
  }
}
