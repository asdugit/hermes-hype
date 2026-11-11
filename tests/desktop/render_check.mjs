/**
 * Showreel desktop/plugin.js rendered in jsdom with the real React 19 and React Query 5, a stub SDK and a
 * fake plugin backend, then driven like a user.
 *
 * Run: cd tests/desktop && npm install && node render_check.mjs        (exit 0 = every check passed)
 *
 * Locks
 *   1  registration: pane (right), page route + sidebar entry, 4 palette commands, status chip, progress
 *      event; the tool-media card only where the host exports the area
 *   2  no chat focused: Make explains why and the button is disabled
 *   3  Make: gallery (inline image preview, lazy video preview, drawn placeholder), mode/length/aspect/
 *      narration/effort/Direction -> POST /jobs with exactly those options; the studio moves to Live
 *   4  Live (Quick): stage list, percent, ETA, Cancel; a progress event updates it; finishing switches to
 *      Result and posts one native notification; an old failure does not notify on open
 *   5  Live (Directed): "watch the Director work": treatment, acts, scenes being coded (+ code peek),
 *      critic rubric, contact sheets, live log read incrementally with ?since=
 *   6  Storyboard: edit narration, drop, move, drag; Save PUTs the edited storyboard (no helper keys);
 *      Re-render POSTs /rerender and opens Live
 *   7  Result: core player with a MEDIA: line (backticks for a path with spaces), Reveal, Render other
 *      aspect, Copy post text, Revise; a Directed film cannot re-render another aspect
 *   8  Library: cards; "Use in a film" fills the Direction box on Make; empty state
 *   9  backend off: a banner says how to turn it on
 *  10  palette command starts a speedrun of the focused chat
 *  11  status chip: running percent; click opens the studio on that job
 *  12  tool-media card wraps the core player for videos, passes anything else through
 */
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { JSDOM } from 'jsdom'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const SRC = process.argv[2] || path.join(HERE, '..', '..', 'desktop', 'plugin.js')
const OUT = path.join(HERE, '.out')
mkdirSync(OUT, { recursive: true })

writeFileSync(path.join(OUT, 'sdk-stub.mjs'), `
import { QueryClient, QueryClientProvider, useQuery as rqUseQuery } from '@tanstack/react-query'
import { cloneElement, isValidElement, useSyncExternalStore } from 'react'
import { jsx } from 'react/jsx-runtime'

export const queryClient = new QueryClient({ defaultOptions: { queries: { retryDelay: 5 } } })
export { QueryClientProvider }
export const useQuery = rqUseQuery
export function atom(v) {
  const subs = new Set()
  return { get: () => v, set: n => { v = n; subs.forEach(f => f(v)) }, listen: f => { subs.add(f); return () => subs.delete(f) } }
}
export function useValue(a) { return useSyncExternalStore(a.listen, a.get) }
export const calls = { notify: [], navigate: [] }
export const host = {
  state: { focusedStoredSessionId: atom('s1'), activeSessionId: atom('rt-1') },
  notify: n => { calls.notify.push(n) },
  navigate: p => { calls.navigate.push(p) }
}
export const PANES_AREA = 'panes'
export const ROUTES_AREA = 'routes'
export const SIDEBAR_NAV_AREA = 'sidebar.nav'
export const PALETTE_AREA = 'palette'
export const STATUSBAR_AREAS = { left: 'statusBar.left', right: 'statusBar.right' }
export let TOOL_MEDIA_RENDERER_AREA = 'transcript.toolMedia'
export function setToolMediaArea(v) { TOOL_MEDIA_RENDERER_AREA = v }
export function Button({ children, onClick, disabled, variant, size, loading, ...rest }) {
  return jsx('button', { ...rest, 'data-variant': variant, disabled, onClick, children })
}
export function SegmentedControl({ options, value, onChange, disabled }) {
  return jsx('div', { 'data-seg': '1', children: options.map(o => jsx('button', { type: 'button', 'data-seg-opt': o.id, 'aria-pressed': o.id === value, disabled, onClick: () => onChange(o.id), children: o.label }, o.id)) })
}
export function Switch({ checked, onCheckedChange, ...rest }) {
  return jsx('button', { ...rest, type: 'button', role: 'switch', 'aria-checked': Boolean(checked), onClick: () => onCheckedChange(!checked) })
}
export function Textarea(props) { return jsx('textarea', props) }
export function Input(props) { return jsx('input', props) }
export function Codicon({ name }) { return jsx('i', { className: 'codicon codicon-' + name }) }
export function Tip({ label, children }) {
  return isValidElement(children) ? cloneElement(children, { 'data-tip': typeof label === 'string' ? label : 'tip' }) : children
}
export function MessageTextContent({ text }) { return jsx('div', { 'data-media': text }) }
`)
const pluginSrc = readFileSync(SRC, 'utf8').replace("'@hermes/plugin-sdk'", "'./sdk-stub.mjs'")
writeFileSync(path.join(OUT, 'plugin-under-test.mjs'), pluginSrc)

const dom = new JSDOM('<!doctype html><html><body></body></html>', { pretendToBeVisual: true, url: 'http://localhost/' })
globalThis.window = dom.window
globalThis.document = dom.window.document
Object.defineProperty(globalThis, 'navigator', { value: dom.window.navigator, configurable: true })
globalThis.IS_REACT_ACT_ENVIRONMENT = false

const stub = await import(pathToFileURL(path.join(OUT, 'sdk-stub.mjs')).href)
const plugin = (await import(pathToFileURL(path.join(OUT, 'plugin-under-test.mjs')).href)).default
const { createRoot } = await import('react-dom/client')
const { jsx } = await import('react/jsx-runtime')

// ── harness ──────────────────────────────────────────────────────────────────────────────────────
let failures = 0
const check = (ok, what) => {
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${what}`)
  if (!ok) failures++
}
const sleep = ms => new Promise(r => setTimeout(r, ms))
async function waitFor(fn, what, ms = 4000) {
  const t0 = Date.now()
  while (Date.now() - t0 < ms) {
    try {
      if (fn()) return true
    } catch (e) { /* not there yet */ }
    await sleep(15)
  }
  check(false, `timed out: ${what}`)
  return false
}
const W = dom.window
const click = el => el.dispatchEvent(new W.MouseEvent('click', { bubbles: true, cancelable: true }))
function typeInto(el, value) {
  const proto = el.tagName === 'TEXTAREA' ? W.HTMLTextAreaElement.prototype : W.HTMLInputElement.prototype
  Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, value)
  el.dispatchEvent(new W.Event('input', { bubbles: true }))
}
const fire = (el, type) => el.dispatchEvent(new W.Event(type, { bubbles: true, cancelable: true }))
const $ = (root, sel) => root.querySelector(sel)
const $$ = (root, sel) => [...root.querySelectorAll(sel)]
const byText = (root, sel, text) => $$(root, sel).find(el => el.textContent.trim() === text || el.textContent.includes(text))
const tabSelected = (root, label) => byText(root, '[role=tab]', label)?.getAttribute('aria-selected') === 'true'

/** Old tab requests expire after a few seconds; scenarios that follow each other quickly click their tab. */
async function openTab(v, label) {
  await sleep(30)
  if (!tabSelected(v.div, label)) click(byText(v.div, '[role=tab]', label))
  await sleep(20)
}


/** SR_SNAPSHOT_DIR=<dir>: write the rendered markup of key screens for the screenshot harness (snapshot.py). */
const SNAP = process.env.SR_SNAPSHOT_DIR || ''
function snap(name, v, variant = 'pane') {
  if (!SNAP) return
  mkdirSync(SNAP, { recursive: true })
  writeFileSync(path.join(SNAP, `${variant}-${name}.html`), v.div.innerHTML)
}
const pageRoute = () => registered.find(c => c.area === 'routes')

async function mount(element) {
  const div = document.createElement('div')
  document.body.appendChild(div)
  const root = createRoot(div)
  root.render(jsx(stub.QueryClientProvider, { client: stub.queryClient, children: element }))
  await sleep(20)
  return { div, unmount: async () => { root.unmount(); div.remove(); await sleep(5) } }
}

// ── fake backend ─────────────────────────────────────────────────────────────────────────────────
const httpError = (status, body) => Object.assign(new Error(`${status}: ${JSON.stringify(body)}`), { statusCode: status })
const RUBRIC = ['product_clarity', 'composition', 'beauty_craft', 'story_clarity', 'legibility', 'style_coherence', 'transition_quality']
const S = {
  down: false,
  jobs: {},
  bySession: {},
  library: { dir: 'C:/data/library', items: [] },
  dlogCalls: [],
  nextId: 100
}
const STYLES = [
  { id: 'launch', name: 'Launch', blurb: 'Premium product-launch motion graphics', ready: true, has_preview: false, preview_kind: '', preview_url: '' },
  { id: 'cinematic', name: 'Cinematic', blurb: 'Cards in dark 3D space', ready: true, has_preview: true, preview_kind: 'video', preview_url: '' },
  { id: 'pixel', name: 'Pixel', blurb: '16-bit arcade', ready: true, has_preview: true, preview_kind: 'image', preview_url: 'data:image/png;base64,iVBORw0KGgo=' },
  { id: 'terminal', name: 'Terminal', blurb: 'Phosphor CRT', ready: false, has_preview: false, preview_kind: '', preview_url: '' }
]
function addJob(job) {
  S.jobs[job.id] = job
  ;(S.bySession[job.session_id] ||= []).unshift(job.id)
  return job
}
function newJob(sid, options, extra = {}) {
  const id = `20261106-1200${String(S.nextId++).padStart(2, '0')}-beef`
  return addJob({ id, session_id: sid, stage: 'queued', pct: 0, options, kind: options.direction ? 'directed' : 'quick', created: Date.now() / 1000, updated: Date.now() / 1000, log: [], warnings: [], ...extra })
}
const DIR = {
  first: {
    available: true, directed: true, direction: 'pixel but transition into a different style mid way through, goal is to sell the product', since: 0, next: 5,
    entries: [
      { i: 0, t: 0, step: 'setup', level: 'info', msg: 'Director ready (standard: 2 critique rounds)' },
      { i: 1, t: 72, step: 'treatment', level: 'info', msg: 'Treatment: A 16-bit red car levels up into the real thing' },
      { i: 2, t: 214, step: 'scenes', level: 'info', msg: 'Coding scene boss-fight' },
      { i: 3, t: 214, step: 'scenes', level: 'info', msg: 'Coding scene petal-bloom' },
      { i: 4, t: 770, step: 'critic', level: 'info', msg: 'Critic round 1: reviewing 27 keyframes on 1 sheet(s)', sheets: [{ v: 1, name: 'contact-1.jpg' }] }
    ],
    treatment: { title: 'Red Car: Press Start', logline: 'A 16-bit red car tears through a pixel night race, then levels up.', signature_moment: 'The pixels burst into petals.', cta: 'Own it', acts: [{ name: 'Act 1: Press Start', style: 'pixel', duration: 20, world: 'night highway' }, { name: 'Act 2: Bloom', style: 'nature', duration: 25, world: 'flower field' }], requirements: ['pixel', 'sell the product'] },
    versions: [{ n: 1, scenes: [{ name: 'boss-fight', lines: 120, bytes: 4000 }], sheets: ['contact-1.jpg'], keyframes: 27, keyframe_names: [], score: { scores: Object.fromEntries(RUBRIC.map((k, i) => [k, [6, 5, 5, 6, 4, 5, 9][i]])), mean: 5.71, min: 4, verdict: 'revise', round: 1, product_share: 1, product_hero: 0.78 }, shots: [{ id: 'hook', t0: 0, t1: 3.3, scene: 'kit:pixel/HOOK' }], title: 'Red Car', changes: [] }],
    best: null, latest: 1, coding: ['petal-bloom'], usage: { calls: 3, ok: 3, input_tokens: 120000, output_tokens: 9000, seconds: 300 }, result: null, bar: 8, rubric: RUBRIC
  },
  more: { entries: [{ i: 5, t: 817, step: 'critic', level: 'info', msg: 'Critic round 1: 5.7 -> fixing 8 issue(s)' }], next: 6 }
}

function server(method, url, body) {
  const [p, qs] = url.split('?')
  const q = Object.fromEntries(new URLSearchParams(qs || ''))
  if (S.down) throw httpError(404, { detail: 'Not Found' })
  if (p === '/health') return { ok: true, api: 2 }
  if (p === '/styles') return { styles: STYLES }
  if (p === '/styles/cinematic/preview') return { id: 'cinematic', kind: 'video', mime: 'video/mp4', url: 'data:video/mp4;base64,AAAAGGZ0eXA=' }
  if (p === '/library') return S.library
  if (p === '/jobs/active') return { jobs: Object.values(S.jobs).filter(j => !['done', 'failed', 'cancelled'].includes(j.stage)).map(j => ({ ...j, log: undefined })) }
  if (p === '/jobs' && method === 'GET') return { jobs: (S.bySession[q.session_id] || []).map(id => S.jobs[id]) }
  if (p === '/jobs' && method === 'POST') {
    const sid = body.session_id
    const busy = (S.bySession[sid] || []).map(id => S.jobs[id]).find(j => !['done', 'failed', 'cancelled'].includes(j.stage))
    if (busy) throw httpError(409, { error: 'a showreel is already rendering for this session', job: busy })
    return newJob(sid, body.options)
  }
  const m = p.match(/^\/jobs\/([\w-]+)(\/.*)?$/)
  if (m) {
    const job = S.jobs[m[1]]
    if (!job) throw httpError(404, { error: 'not found' })
    const sub = m[2] || ''
    if (!sub) return job
    if (sub === '/cancel') { job.cancelRequested = true; return { ok: true, id: job.id } }
    if (sub === '/storyboard' && method === 'GET') return { id: job.id, storyboard: job.edit || job.storyboard, edited: Boolean(job.edit), source: 'llm' }
    if (sub === '/storyboard' && method === 'PUT') { job.edit = body.storyboard; return { ok: true } }
    if (sub === '/thumbs') return { thumbs: ['data:image/jpeg;base64,AAA1', 'data:image/jpeg;base64,AAA2', ''], contact_sheet: 'data:image/png;base64,SHEET' }
    if (sub === '/rerender') {
      if (job.kind === 'directed') throw httpError(409, { error: 'a Directed film has no storyboard to re-render', directed: true })
      return newJob(job.session_id, { ...job.options, aspects: body.aspects }, { parent: job.id })
    }
    if (sub === '/revise') return newJob(job.session_id, { ...job.options, notes: body.notes }, { parent: job.id })
    if (sub === '/post-text') return { id: job.id, text: `${job.title}: made with /showreel\n\n#HermesAgent #Showreel` }
    if (sub === '/director-log') {
      S.dlogCalls.push(Number(q.since || 0))
      return Number(q.since || 0) === 0 ? DIR.first : { ...DIR.first, ...DIR.more }
    }
    if (sub === '/director/image') return { url: 'data:image/jpeg;base64,/9j/SHEET', w: Number(q.w), h: 270 }
    if (sub === '/director/scene') return { v: 1, name: q.name, code: "sr.defineScene('custom:boss-fight', {})", lines: 1, truncated: false }
  }
  throw httpError(404, { detail: 'Not Found' })
}

// ── fake ctx ─────────────────────────────────────────────────────────────────────────────────────
const registered = []
const listeners = new Map()
const rest = []
const revealed = []
const clip = []
const osNotes = []
const kept = new Map()
const disposers = []
function makeCtx(into) {
  return {
    source: 'plugin:showreel',
    register: c => { into.push(c); return () => {} },
    registerMany: cs => { cs.forEach(c => into.push(c)); return () => {} },
    rest: async (p, opts = {}) => {
      const call = { m: opts.method || 'GET', p, body: opts.body }
      rest.push(call)
      await sleep(1)
      return JSON.parse(JSON.stringify(server(call.m, p, opts.body)))
    },
    onEvent: (type, fn) => { listeners.set(type, fn); return () => listeners.delete(type) },
    onDispose: fn => { disposers.push(fn) },
    setTimeout: (fn, ms) => { const h = setTimeout(fn, ms); return () => clearTimeout(h) },
    setInterval: (fn, ms) => { const h = setInterval(fn, ms); return () => clearInterval(h) },
    addEventListener: () => () => {},
    os: {
      revealPath: async p => { revealed.push(p); return true },
      writeClipboard: async t => { clip.push(t); return true },
      notify: n => { osNotes.push(n) }
    },
    storage: { get: (k, d) => (kept.has(k) ? kept.get(k) : d), set: (k, v) => { kept.set(k, v) }, remove: k => { kept.delete(k) } }
  }
}
const calls = (m, p) => rest.filter(c => c.m === m && (typeof p === 'string' ? c.p === p : p.test(c.p)))
const focus = sid => stub.host.state.focusedStoredSessionId.set(sid)

// ── 1 registration ───────────────────────────────────────────────────────────────────────────────
{
  const old = []
  stub.setToolMediaArea(undefined)
  plugin.register(makeCtx(old))
  check(!old.some(c => c.area === 'transcript.toolMedia'), '1 an older host without TOOL_MEDIA_RENDERER_AREA gets no tool card and no error')
  disposers.splice(0).forEach(f => f())
  stub.setToolMediaArea('transcript.toolMedia')
}
plugin.register(makeCtx(registered))
const reg = area => registered.filter(c => c.area === area)
const pane = reg('panes')[0]
check(plugin.id === 'showreel' && pane && pane.title === 'Showreel' && pane.data.placement === 'right', '1 a right-side pane titled Showreel')
check(reg('routes')[0]?.data.path === '/showreel' && reg('sidebar.nav')[0]?.data.label === 'Showreel' && reg('sidebar.nav')[0]?.data.codicon, '1 a /showreel page with a sidebar entry')
const palette = reg('palette').map(c => c.data)
check(palette.length === 4 && ['trailer', 'lore', 'speedrun', 'open'].every(k => palette.some(p => p.id === `showreel.${k}`)) && palette.some(p => p.label === 'Showreel: make a trailer of this chat'), '1 four palette commands (trailer, lore, speedrun, open)')
check(reg('statusBar.right').length === 1, '1 a status-bar chip')
const toolCard = reg('transcript.toolMedia')[0]
check(toolCard && toolCard.data.tools.includes('showreel_render') && toolCard.data.tools.includes('showreel_status'), '1 a tool-media card for showreel_render / showreel_status')
check(listeners.has('plugin.showreel.job.progress'), '1 listens to plugin.showreel.job.progress')

// ── 2 no chat ────────────────────────────────────────────────────────────────────────────────────
{
  focus(null)
  kept.set('tab.pane', 'make')
  const v = await mount(pane.render())
  await waitFor(() => v.div.textContent.includes('Open a chat first'), '2 no-chat hint')
  const btn = byText(v.div, 'button', 'Make showreel')
  check(Boolean(btn && btn.disabled), '2 with no chat focused Make is disabled and says why')
  await v.unmount()
}

// ── 3 Make ───────────────────────────────────────────────────────────────────────────────────────
{
  focus('s-make')
  kept.set('tab.pane', 'make')
  const v = await mount(pane.render())
  await waitFor(() => $$(v.div, '.srl-card').length === 4, '3 four style cards')
  check($(v.div, '.srl-card img')?.getAttribute('src').startsWith('data:image/png'), '3 an inline image preview')
  await waitFor(() => $(v.div, '.srl-card video')?.getAttribute('src')?.startsWith('data:video/mp4'), '3 a lazy video preview')
  check(calls('GET', '/styles/cinematic/preview').length === 1, '3 the video preview is fetched once, on its own')
  const terminal = $$(v.div, '.srl-card').find(c => c.textContent.includes('Terminal'))
  check(Boolean(terminal && $(terminal, '.srl-ph-terminal') && terminal.textContent.includes('soon')), '3 a style without a preview shows its drawn placeholder (and is marked soon)')
  click(byText(v.div, '.srl-card', 'Pixel'))
  await waitFor(() => byText(v.div, '.srl-card', 'Pixel').getAttribute('aria-pressed') === 'true', '3 picking a style')
  click($(v.div, '[data-seg-opt=speedrun]'))
  click($(v.div, '[data-seg-opt="30"]'))
  click($(v.div, '[data-seg-opt=both]'))
  click($(v.div, '[role=switch]'))
  await sleep(20)
  check(Boolean($(v.div, 'textarea[aria-label="Customize this preset"]')), '3 a picked preset offers "Customize this preset" by default')
  click($(v.div, '[data-seg-opt=roam]'))
  await waitFor(() => $(v.div, 'textarea[aria-label=Direction]'), '3 Free roam shows the Direction box')
  check(v.div.textContent.includes('Effort applies to Directed films'), '3 effort is explained as Directed-only while the Direction box is empty')
  typeInto($(v.div, 'textarea[aria-label=Direction]'), 'pixel but transition into a different style mid way through, goal is to sell the product')
  await waitFor(() => byText(v.div, 'button', 'Direct this film'), '3 a direction turns the button into "Direct this film"')
  click($(v.div, '[data-seg-opt=quick]'))
  await sleep(20)
  snap('make', v)
  if (SNAP) { const pg = await mount(pageRoute().render()); await openTab(pg, 'Make'); await sleep(150); snap('make', pg, 'page'); await pg.unmount() }
  click(byText(v.div, 'button', 'Direct this film'))
  await waitFor(() => calls('POST', '/jobs').length === 1, '3 POST /jobs')
  const sent = calls('POST', '/jobs')[0].body
  check(sent.session_id === 's-make', '3 the film is made of the focused chat')
  const o = sent.options
  check(o.mode === 'speedrun' && o.style === 'pixel' && o.seconds === 30 && JSON.stringify(o.aspects) === '["16:9","9:16"]' && o.voice === false && o.effort === 'quick' && o.direction.startsWith('pixel but transition'), `3 options sent as picked: ${JSON.stringify(o)}`)
  await waitFor(() => tabSelected(v.div, 'Live'), '3 the studio moves to Live')
  check(JSON.parse(JSON.stringify(kept.get('make'))).style === 'pixel', '3 choices are remembered (ctx.storage)')
  check(!('customize' in sent), '3 a Free roam film sends no customization')
  await v.unmount()
}

// ── 3b Make: customize a preset (free text + knobs -> POST /jobs customize) ───────────────────────────
{
  focus('s-cust')
  kept.set('tab.pane', 'make')
  const v = await mount(pane.render())
  await waitFor(() => $$(v.div, '.srl-card').length === 4, '3b style cards')
  click(byText(v.div, '.srl-card', 'Launch'))
  click($(v.div, '[data-seg-opt=preset]'))
  await waitFor(() => $(v.div, 'textarea[aria-label="Customize this preset"]'), '3b back on the preset: the Customize box')
  check(Boolean($(v.div, 'input[type=color][aria-label="Accent colour"]') && $(v.div, 'select[aria-label=Music]') && $(v.div, 'select[aria-label=Font]') && $(v.div, 'select[aria-label="Narration voice"]')), '3b the knobs row: accent, energy, music, font, voice')
  typeInto($(v.div, 'textarea[aria-label="Customize this preset"]'), 'pink and playful with a punchier ending')
  click($(v.div, '[data-seg-opt=high]'))
  const music = $(v.div, 'select[aria-label=Music]')
  Object.getOwnPropertyDescriptor(W.HTMLSelectElement.prototype, 'value').set.call(music, 'playful')
  fire(music, 'change')
  typeInto($(v.div, 'input[type=color][aria-label="Accent colour"]'), '#ff4fa3')
  await waitFor(() => byText(v.div, 'button', 'Make customized showreel'), '3b the button says "Make customized showreel"')
  check(v.div.textContent.includes('customized'), '3b the summary says customized')
  const before = calls('POST', '/jobs').length
  click(byText(v.div, 'button', 'Make customized showreel'))
  await waitFor(() => calls('POST', '/jobs').length === before + 1, '3b POST /jobs')
  const body = calls('POST', '/jobs')[before].body
  check(body.options.style === 'launch' && body.options.direction === '', `3b the preset stays a Quick film: ${JSON.stringify(body.options)}`)
  check(body.customize && body.customize.text === 'pink and playful with a punchier ending' && body.customize.knobs.energy === 'high' && body.customize.knobs.music === 'playful' && body.customize.knobs.accent === '#ff4fa3', `3b customize sent: ${JSON.stringify(body.customize)}`)
  await v.unmount()
}

// ── 4 Live (Quick) ───────────────────────────────────────────────────────────────────────────────
{
  focus('s-live')
  const now = Date.now() / 1000
  const old = addJob({ id: '20261101-000000-0001', session_id: 's-live', stage: 'failed', pct: 0.3, options: {}, kind: 'quick', created: now - 9000, error: { code: 'x', message: 'old failure' }, log: [], warnings: [] })
  const job = addJob({ id: '20261106-130000-aaaa', session_id: 's-live', title: 'Tiny Todo', stage: 'render', stage_pct: 0.5, pct: 0.42, eta_s: 150, created: now - 60, started: now - 60, updated: now, kind: 'quick', options: { mode: 'product', style: 'pixel', seconds: 30, aspects: ['16:9'], voice: true }, stages: { reading: 0.4, storyboard: 20, voice: 3, layout: 4 }, log: [{ t: now, level: 'info', msg: 'stage render' }], warnings: ['narration failed for 1 of 6 lines'] })
  kept.set('tab.pane', 'live')
  const v = await mount(pane.render())
  await waitFor(() => $(v.div, '.srl-pct')?.textContent === '42%', '4 percent shown')
  const st = $$(v.div, '.srl-stages li').map(li => li.getAttribute('data-st'))
  check(st.join(',') === 'done,done,done,done,active,todo,todo', `4 stage list marks done / active / todo (${st})`)
  check($(v.div, '.srl-eta').textContent.includes('min left'), '4 an ETA is shown')
  check(v.div.textContent.includes('narration failed for 1 of 6 lines'), '4 warnings are listed')
  snap('live-quick', v)
  check(!stub.calls.notify.some(n => String(n.message).includes('old failure')), '4 an old failure is not announced when the studio opens')
  click(byText(v.div, 'button', 'Cancel'))
  await waitFor(() => calls('POST', `/jobs/${job.id}/cancel`).length === 1, '4 Cancel posts /cancel')
  Object.assign(job, { stage: 'mix', pct: 0.9, eta_s: 10 })
  listeners.get('plugin.showreel.job.progress')({ type: 'plugin.showreel.job.progress', payload: { id: job.id, session_id: 's-live', stage: 'mix', pct: 0.9, eta_s: 10, note: 'mixing music and voice' } })
  await waitFor(() => $(v.div, '.srl-pct')?.textContent === '90%', '4 a progress event moves the bar')
  // status chip while it runs
  const chip = await mount(reg('statusBar.right')[0].render())
  await waitFor(() => chip.div.textContent.includes('Showreel 90%'), '11 chip shows the running percent')
  snap('chip', chip, 'bar')
  click($(chip.div, 'button'))
  check(stub.calls.navigate.includes('/showreel'), '11 the chip opens the studio')
  Object.assign(job, { stage: 'done', pct: 1, finished: Date.now() / 1000, outputs: { '16:9': 'C:/videos/tiny.mp4' }, duration_s: 30.5 })
  listeners.get('plugin.showreel.job.progress')({ payload: { id: job.id, session_id: 's-live', stage: 'done', pct: 1 } })
  await waitFor(() => tabSelected(v.div, 'Result'), '4 a finished film opens on Result')
  check(osNotes.filter(n => n.title === 'Showreel ready').length === 1, '4 exactly one native "Showreel ready" notification')
  await chip.unmount()
  await v.unmount()
  delete S.jobs[old.id]
}

// ── 5 Live (Directed) ────────────────────────────────────────────────────────────────────────────
{
  focus('s-dir')
  const now = Date.now() / 1000
  const job = addJob({ id: '20261106-140000-dddd', session_id: 's-dir', stage: 'storyboard', pct: 0.2, created: now, updated: now, kind: 'directed', options: { direction: DIR.first.direction, effort: 'standard', style: 'pixel', seconds: 45, aspects: ['16:9'] }, log: [], warnings: [] })
  kept.set('tab.pane', 'live')
  const v = await mount(pane.render())
  await waitFor(() => v.div.textContent.includes('Watch the Director work'), '5 the Director panel')
  await waitFor(() => v.div.textContent.includes('Red Car: Press Start'), '5 the treatment')
  check($$(v.div, '.srl-act').length === 2, '5 the acts as a timeline')
  check(Boolean(byText(v.div, '.srl-scene-chip', 'boss-fight')?.textContent.includes('120 lines')), '5 a coded scene with its size')
  check(Boolean(byText(v.div, '.srl-scene-chip', 'petal-bloom')?.textContent.includes('coding')), '5 a scene still being coded')
  check($$(v.div, '.srl-rub').length === 7, '5 seven rubric scores')
  check($$(v.div, '.srl-rub-track i[data-tone=ok]').length === 1 && $$(v.div, '.srl-rub-track i[data-tone=low]').length >= 1, '5 scores are toned against the bar')
  check(v.div.textContent.includes('3 model calls') && v.div.textContent.includes('120k in'), '5 model usage so far')
  await waitFor(() => $(v.div, '.srl-sheet img')?.getAttribute('src').startsWith('data:image/jpeg'), '5 the contact sheet appears')
  check(calls('GET', /\/director\/image\?v=1&name=contact-1\.jpg&w=480$/).length >= 1 &&
    calls('GET', /\/director\/image\?v=1&name=contact-1\.jpg$/).length === 0, '5 the sheet is fetched downscaled')  // a refetch may repeat it (macOS CI)
  check(byText(v.div, '.srl-rail li', 'Critic')?.getAttribute('data-st') === 'active', '5 the step rail shows the critic at work')
  await waitFor(() => v.div.textContent.includes('fixing 8 issue(s)'), '5 the live log gets the next line', 5000)
  check(S.dlogCalls[0] === 0 && S.dlogCalls.includes(5), `5 the log is read incrementally (${S.dlogCalls.slice(0, 4)})`)
  check($$(v.div, '.srl-feed li').length === 6, '5 no line is shown twice')
  snap('live-directed', v)
  if (SNAP) { const pg = await mount(pageRoute().render()); await openTab(pg, 'Live'); await sleep(400); snap('live-directed', pg, 'page'); await pg.unmount() }
  click(byText(v.div, '.srl-scene-chip', 'boss-fight'))
  await waitFor(() => $(v.div, '.srl-code')?.textContent.includes('defineScene'), '5 the code peek shows the scene')
  job.stage = 'failed'
  await v.unmount()
}

// ── 6 Storyboard ─────────────────────────────────────────────────────────────────────────────────
{
  focus('s-sb')
  const sb = { title: 'Tiny Todo', tagline: 'Todos fast', accent_hint: '', scenes: [
    { type: 'HOOK', refs: ['e1'], vo: 'One', label: 'Hook' },
    { type: 'DIFF', refs: ['e2', 'e3'], vo: 'Two words', label: 'The fix' },
    { type: 'END', refs: [], vo: 'Three', label: 'End' }
  ], end: { cta: 'Try it' } }
  const job = addJob({ id: '20261106-150000-5b5b', session_id: 's-sb', title: 'Tiny Todo', stage: 'done', pct: 1, created: Date.now() / 1000, kind: 'quick', options: { style: 'launch', seconds: 30, aspects: ['16:9'] }, storyboard: sb, outputs: { '16:9': 'C:/v/a.mp4' }, log: [], warnings: [] })
  kept.set('tab.pane', 'board')
  const v = await mount(pane.render())
  await openTab(v, 'Storyboard')
  await waitFor(() => $$(v.div, '.srl-sb-card').length === 3, '6 three scene cards')
  await waitFor(() => $$(v.div, '.srl-sb-thumb img').length === 2, '6 thumbnails from the last render')
  typeInto($(v.div, 'textarea[aria-label="Scene 2 narration"]'), 'Two words, edited now')
  await sleep(10)
  click($(v.div, 'button[aria-label="Drop scene 3"]'))
  await sleep(10)
  click($(v.div, 'button[aria-label="Move scene 2 up"]'))
  await waitFor(() => $$(v.div, '.srl-type')[0].textContent === 'DIFF', '6 move up')
  check($$(v.div, '.srl-sb-card')[2].hasAttribute('data-dropped'), '6 a dropped scene stays visible, struck through')
  const cards = () => $$(v.div, '.srl-sb-card')
  fire(cards()[1], 'dragstart')
  fire(cards()[0], 'dragover')
  fire(cards()[0], 'drop')
  await waitFor(() => $$(v.div, '.srl-type')[0].textContent === 'HOOK', '6 drag and drop reorders')
  click($(v.div, 'button[aria-label="Move scene 2 up"]'))
  await waitFor(() => $$(v.div, '.srl-type')[0].textContent === 'DIFF', '6 move back up')
  snap('storyboard', v)
  click(byText(v.div, 'button', 'Save'))
  await waitFor(() => calls('PUT', `/jobs/${job.id}/storyboard`).length === 1, '6 Save PUTs the storyboard')
  const put = calls('PUT', `/jobs/${job.id}/storyboard`)[0].body.storyboard
  check(put.scenes.length === 2 && put.scenes[0].type === 'DIFF' && put.scenes[0].vo === 'Two words, edited now' && put.scenes[1].type === 'HOOK', '6 the edit keeps order, text and drops')
  check(put.title === 'Tiny Todo' && put.end.cta === 'Try it' && !JSON.stringify(put).includes('_k') && !JSON.stringify(put).includes('_drop'), '6 other fields survive and no helper keys leak')
  click(byText(v.div, 'button', 'Re-render'))
  await waitFor(() => calls('POST', `/jobs/${job.id}/rerender`).length === 1, '6 Re-render posts /rerender')
  check(JSON.stringify(calls('POST', `/jobs/${job.id}/rerender`)[0].body.aspects) === '["16:9"]', '6 with the chosen aspect')
  await waitFor(() => tabSelected(v.div, 'Live'), '6 and opens Live')
  await v.unmount()
}

// ── 7 Result ─────────────────────────────────────────────────────────────────────────────────────
{
  focus('s-res')
  const job = addJob({ id: '20261106-160000-7e7e', session_id: 's-res', title: 'Tiny Todo', stage: 'done', pct: 1, created: Date.now() / 1000, kind: 'quick', duration_s: 31.2, wall_s: 182, options: { mode: 'product', style: 'pixel', seconds: 30, aspects: ['16:9'] }, storyboard: { scenes: [] }, outputs: { '16:9': 'C:/job/final.mp4' }, delivered: { '16:9': 'C:/Users/Some One/videos/Tiny Todo 16x9.mp4' }, log: [], warnings: [] })
  kept.set('tab.pane', 'result')
  const v = await mount(pane.render())
  await openTab(v, 'Result')
  await waitFor(() => $(v.div, '[data-media]'), '7 the core player')
  check($(v.div, '[data-media]').getAttribute('data-media') === 'MEDIA:`C:/Users/Some One/videos/Tiny Todo 16x9.mp4`', '7 the delivered copy plays, its spaced path in backticks')
  click(byText(v.div, 'button', 'Reveal file'))
  await waitFor(() => revealed.includes('C:/Users/Some One/videos/Tiny Todo 16x9.mp4'), '7 Reveal file')
  await waitFor(() => $(v.div, '.srl-post')?.textContent.includes('#HermesAgent'), '7 the post text is shown')
  snap('result', v)
  click(byText(v.div, 'button', 'Copy post text'))
  await waitFor(() => clip.some(t => t.includes('#HermesAgent')), '7 Copy post text')
  click(byText(v.div, 'button', 'Render 9:16'))
  await waitFor(() => calls('POST', `/jobs/${job.id}/rerender`).length === 1, '7 Render the other aspect')
  check(JSON.stringify(calls('POST', `/jobs/${job.id}/rerender`)[0].body) === '{"aspects":["9:16"]}', '7 as 9:16')
  await waitFor(() => tabSelected(v.div, 'Live'), '7 the re-render opens Live')
  // back to the finished film: revise it
  const sel = v.div.querySelector('select.srl-picker')
  sel.value = job.id
  fire(sel, 'change')
  click(byText(v.div, '[role=tab]', 'Result'))
  await waitFor(() => $(v.div, 'textarea[aria-label="Revision notes"]'), '7 the revise box')
  // the new re-render job is running; let it finish so revise is allowed
  Object.values(S.jobs).filter(j => j.session_id === 's-res' && j.id !== job.id).forEach(j => { j.stage = 'done' })
  typeInto($(v.div, 'textarea[aria-label="Revision notes"]'), 'open on the dashboard')
  await sleep(10)
  click(byText(v.div, 'button', 'Revise'))
  await waitFor(() => calls('POST', `/jobs/${job.id}/revise`).length === 1, '7 Revise posts /revise')
  check(calls('POST', `/jobs/${job.id}/revise`)[0].body.notes === 'open on the dashboard', '7 with the notes')
  await v.unmount()

  focus('s-res-d')
  addJob({ id: '20261106-170000-d1d1', session_id: 's-res-d', title: 'Red Car', stage: 'done', pct: 1, created: Date.now() / 1000, kind: 'directed', options: { direction: 'anime finale', aspects: ['16:9'] }, outputs: { '16:9': 'C:/v/red.mp4' }, log: [], warnings: [] })
  kept.set('tab.pane', 'result')
  const d = await mount(pane.render())
  await openTab(d, 'Result')
  await waitFor(() => byText(d.div, 'button', 'Render 9:16'), '7 directed result')
  check(byText(d.div, 'button', 'Render 9:16').disabled && d.div.textContent.includes('Direct another pass'), '7 a Directed film re-directs instead of re-rendering another aspect')
  await d.unmount()
}

// ── 8 Library ────────────────────────────────────────────────────────────────────────────────────
{
  focus('s-lib')
  S.library = { dir: 'C:/data/library', items: [{ id: 'lib:boss-battle', name: 'boss-battle', kind: 'scene', describe: 'A pixel boss fight', layer: '2d', tags: [], kits: [], created_job: 'j1', direction: '', score: 7, path: 'C:/data/library/boss-battle', modified: 1, thumb: 'data:image/jpeg;base64,AA', params: ['boss_name', 'menu'] }] }
  kept.set('tab.pane', 'library')
  const v = await mount(pane.render())
  await openTab(v, 'Library')
  await waitFor(() => byText(v.div, '.srl-lib-card', 'boss-battle'), '8 a library card')
  check($(v.div, '.srl-lib-card img')?.getAttribute('src').startsWith('data:image/jpeg') && v.div.textContent.includes('boss_name'), '8 with its thumbnail and parameters')
  snap('library', v)
  click(byText(v.div, 'button', 'Use in a film'))
  await waitFor(() => tabSelected(v.div, 'Make'), '8 "Use in a film" opens Make')
  await waitFor(() => $(v.div, 'textarea[aria-label=Direction]')?.value.includes('Use my boss-battle scene (lib:boss-battle).'), '8 and fills the Direction box')
  await v.unmount()
  S.library = { dir: 'C:/data/library', items: [] }
  stub.queryClient.removeQueries()
  kept.set('tab.pane', 'library')
  const e = await mount(pane.render())
  await openTab(e, 'Library')
  await waitFor(() => e.div.textContent.includes('Your library is empty'), '8 the empty library explains itself')
  await e.unmount()
}

// ── 9 backend off ────────────────────────────────────────────────────────────────────────────────
{
  stub.queryClient.removeQueries()
  S.down = true
  focus('s-down')
  kept.set('tab.pane', 'make')
  const v = await mount(pane.render())
  await openTab(v, 'Make')
  await waitFor(() => v.div.textContent.includes('The Showreel backend is not running'), '9 a banner when the backend is off')
  snap('backend-off', v)
  check($(v.div, '.srl-make-go button')?.disabled === true, '9 Make is disabled while it is off')
  await v.unmount()
  S.down = false
  stub.queryClient.removeQueries()
}

// ── 10 palette ───────────────────────────────────────────────────────────────────────────────────
{
  focus('s-pal')
  palette.find(p => p.id === 'showreel.speedrun').run()
  await waitFor(() => calls('POST', '/jobs').some(c => c.body.session_id === 's-pal'), '10 the palette starts a film')
  const o = calls('POST', '/jobs').find(c => c.body.session_id === 's-pal').body.options
  check(o.mode === 'speedrun' && o.direction === '', '10 a speedrun of the focused chat')
  await waitFor(() => stub.calls.notify.some(n => n.kind === 'success' && n.message.includes('speedrun')), '10 with a toast')
}

// ── 12 tool media card ───────────────────────────────────────────────────────────────────────────
{
  const fallback = jsx('video', { 'data-fallback': 'core' })
  const v = await mount(toolCard.data.render({ file: { kind: 'video', path: 'C:/v/x.mp4', name: 'x.mp4' }, result: JSON.stringify({ job_id: '20261106-160000-7e7e', title: 'Tiny Todo', style: 'pixel', duration_s: 31 }), args: {}, sessionId: 's-res', fallback }))
  snap('toolcard', v, 'card')
  check(Boolean($(v.div, 'video[data-fallback=core]')) && v.div.textContent.includes('Tiny Todo') && v.div.textContent.includes('pixel'), '12 a video gets the Showreel card around the core player')
  click(byText(v.div, 'button', 'Open in Showreel'))
  check(stub.calls.navigate.filter(p => p === '/showreel').length >= 2, '12 Open in Showreel')
  click(byText(v.div, 'button', 'Reveal'))
  await waitFor(() => revealed.includes('C:/v/x.mp4'), '12 Reveal')
  await v.unmount()
  const a = await mount(toolCard.data.render({ file: { kind: 'audio', path: 'C:/v/x.mp3' }, result: {}, fallback: jsx('audio', { 'data-fallback': 'core' }) }))
  check(Boolean($(a.div, 'audio[data-fallback=core]')) && !$(a.div, '.srl-reel'), '12 anything else keeps the core player')
  await a.unmount()
}

// ── done ─────────────────────────────────────────────────────────────────────────────────────────
disposers.splice(0).forEach(f => f())
stub.queryClient.clear()
console.log(failures ? `\n${failures} check(s) failed` : '\nall render checks passed')
process.exit(failures ? 1 : 0)
