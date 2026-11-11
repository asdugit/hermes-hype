"""Decide what Hype can capture of a product. Never starts servers, never runs commands.

Inputs are the :class:`~showreel_core.contracts.Product` draft (WP-B ``infer_product``, or an
agent-supplied brief) and the session events (``artifact`` events plus everything that mentions a
URL). The output :class:`TargetPlan` lists capture targets in priority order and every rejected
candidate with a reason code, so the pipeline can explain why something was not captured.

URL policy (by host class):

* ``loopback`` - 127.0.0.0/8, ::1, ``localhost``, ``*.localhost``; ``0.0.0.0`` is opened as 127.0.0.1.
  Always allowed.
* ``lan`` - private/link-local/ULA/CGNAT addresses, ``*.local|.lan|.home.arpa|.internal``, single-label
  names. Allowed only if the session itself used that host.
* ``public`` - only ``https``, only if the host appeared in the session AND the caller passed
  ``allow_network=True``.

A URL target must answer a short TCP connect + HTTP GET (status < 400 after at most three redirects
that stay inside the policy). Local HTML entry files are served read-only from their own folder;
folders that are too broad to expose (home, Desktop, a drive root) are staged as a copy of the page
plus the files it references.

Reason codes for skipped candidates: ``unsupported_scheme``, ``refused_public``, ``refused_lan``,
``refused_http``, ``unreachable``, ``http_error``, ``not_renderable``, ``not_found``,
``needs_build``, ``duplicate``, ``over_cap``, ``test_page`` (a page under a test/fixture/report folder while the
product has pages of its own: a film once showed a test fixture of colour blocks as the product).
"""
from __future__ import annotations

import concurrent.futures as cf
import http.client
import ipaddress
import re
import ssl
import sys
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal
from urllib.parse import unquote, urljoin, urlsplit

from ..contracts import Event, Product

TargetKind = Literal["url", "html", "image", "video", "pdf"]

URL_RE = re.compile(r"(?:https?|file)://[^\s\"'<>()\[\]{}`\\|^]+", re.I)
TITLE_RE = re.compile(r"<title[^>]*>\s*([^<]{1,160}?)\s*</title>", re.I)
# A page whose scripts need a compiler/bundler cannot be shown by a static file server.
NEEDS_BUILD_RE = re.compile(
    r"<script[^>]+src=[\"'][^\"']+\.(?:tsx?|jsx|vue|svelte)(?:\?[^\"']*)?[\"']|%PUBLIC_URL%|<%[=\-]?\s", re.I)
EXTERNAL_REF_RE = re.compile(r"<(?:script|link|img|iframe)\b[^>]*?(?:src|href)=[\"'](?:https?:)?//", re.I)
LOCAL_REF_RE = re.compile(r"\b(?:src|href|poster)=[\"']([^\"'#?]+)[\"']", re.I)
CSS_URL_RE = re.compile(r"url\(\s*[\"']?([^\"')#?]+)", re.I)

LAN_SUFFIXES = (".local", ".lan", ".home.arpa", ".internal", ".localdomain", ".intranet")
RENDERABLE_TYPES = ("text/html", "application/xhtml+xml", "text/plain", "application/json", "image/")
HTML_TYPES = ("text/html", "application/xhtml+xml")
MEDIA_KINDS = {"image": "image", "video": "video", "pdf": "pdf"}
UA = "Hype-capture/1 (local reachability probe)"

DEFAULT_CAPS = {"web": 2, "image": 4, "video": 2, "pdf": 1}
STAGE_MAX_FILES = 300
STAGE_MAX_BYTES = 64 * 1024 * 1024


# ------------------------------------------------------------------------------- URLs

@dataclass(frozen=True)
class ParsedURL:
    """A normalised http(s) URL plus its host class."""
    url: str
    scheme: str
    host: str          # lower case, IPv6 without brackets
    port: int
    path: str          # path + ?query + #fragment (fragments matter for hash-routed SPAs)
    host_class: str    # loopback | lan | public | invalid

    @property
    def netloc(self) -> str:
        h = f"[{self.host}]" if ":" in self.host else self.host
        default = 443 if self.scheme == "https" else 80
        return h if self.port == default else f"{h}:{self.port}"

    @property
    def origin(self) -> str:
        return f"{self.scheme}://{self.netloc}"

    @property
    def key(self) -> str:
        """Dedupe key: every loopback spelling of one port is the same server."""
        host = "loopback" if self.host_class == "loopback" else self.host
        path = self.path if self.path not in ("", "/") else "/"
        return f"{self.scheme}://{host}:{self.port}{path}"


def classify_host(host: str) -> str:
    """``loopback`` | ``lan`` | ``public`` | ``invalid`` for a host name or IP literal."""
    h = host.strip().strip("[]").lower().rstrip(".")
    if not h:
        return "invalid"
    if h == "localhost" or h.endswith(".localhost"):
        return "loopback"
    try:
        ip = ipaddress.ip_address(h)
    except ValueError:
        if not re.fullmatch(r"[a-z0-9\-_.]+", h):
            return "invalid"
        if h.endswith(LAN_SUFFIXES) or "." not in h:
            return "lan"
        return "public"
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    if ip.is_loopback or ip.is_unspecified:
        return "loopback"
    if ip.is_multicast or ip.is_reserved:
        return "invalid"
    return "public" if ip.is_global else "lan"


def parse_url(raw: str) -> ParsedURL | None:
    """Parse an http(s) URL; ``0.0.0.0``/``[::]`` become loopback addresses. None if unusable."""
    s = (raw or "").strip().rstrip(".,;:!?'\")]}>")
    try:
        sp = urlsplit(s)
        port = sp.port
    except ValueError:
        return None
    scheme = sp.scheme.lower()
    if scheme not in ("http", "https") or not sp.hostname:
        return None
    host = sp.hostname.lower()
    if host == "0.0.0.0":
        host = "127.0.0.1"
    elif host == "::":
        host = "::1"
    port = port or (443 if scheme == "https" else 80)
    path = sp.path or "/"
    if sp.query:
        path += "?" + sp.query
    if sp.fragment:
        path += "#" + sp.fragment
    netloc = f"[{host}]" if ":" in host else host
    if port != (443 if scheme == "https" else 80):
        netloc += f":{port}"
    return ParsedURL(f"{scheme}://{netloc}{path}", scheme, host, port, path, classify_host(host))


def file_url_to_path(url: str) -> Path | None:
    """``file:///C:/x/index.html`` or ``file:///home/x/index.html`` -> Path (None if not a file URL)."""
    if not url.lower().startswith("file://"):
        return None
    rest = unquote(url[7:].split("#", 1)[0].split("?", 1)[0])
    if rest.startswith("localhost/"):
        rest = rest[len("localhost"):]
    if re.match(r"^/[A-Za-z]:[/\\]", rest):
        rest = rest[1:]
    return Path(rest) if rest else None


def resolve_path(src: str) -> Path | None:
    """A transcript path spelling (``~/x``, ``C:\\x``, ``/c/x`` MSYS, ``file://``) -> absolute Path or None."""
    s = (src or "").strip().strip("`'\"")
    if not s:
        return None
    if s.lower().startswith("file://"):
        return file_url_to_path(s)
    if sys.platform == "win32" and re.match(r"^/[a-zA-Z]/", s):
        s = f"{s[1].upper()}:{s[2:]}"
    p = Path(s).expanduser()
    return p if p.is_absolute() else None


# ------------------------------------------------------------------------- session scan

def _strings(value: Any, out: list[str], budget: list[int]) -> None:
    if budget[0] <= 0:
        return
    if isinstance(value, str):
        out.append(value[:20000])
        budget[0] -= len(value)
    elif isinstance(value, dict):
        for v in value.values():
            _strings(v, out, budget)
    elif isinstance(value, (list, tuple)):
        for v in value:
            _strings(v, out, budget)


def session_urls(events: Iterable[Event]) -> dict[str, list[str]]:
    """Every http(s)/file URL mentioned anywhere in the events -> ids of the events mentioning it."""
    found: dict[str, list[str]] = {}
    for ev in events:
        if ev.kind == "product_capture":
            continue
        texts: list[str] = [ev.title or "", ev.summary or ""]
        _strings(ev.data, texts, [200_000])
        for text in texts:
            if "://" not in text:
                continue
            for m in URL_RE.finditer(text):
                u = m.group(0).rstrip(".,;:!?'\")]}>")
                ids = found.setdefault(u, [])
                if ev.id not in ids:
                    ids.append(ev.id)
    return found


def session_hosts(urls: Iterable[str]) -> set[str]:
    """Lower-case hosts (IPv6 without brackets) of the given URLs; ``0.0.0.0`` counts as 127.0.0.1."""
    hosts: set[str] = set()
    for u in urls:
        p = parse_url(u)
        if p is not None:
            hosts.add(p.host)
    return hosts


# ------------------------------------------------------------------------------ probing

@dataclass
class Probe:
    """Result of a reachability probe."""
    ok: bool
    status: int | None = None
    content_type: str = ""
    title: str = ""
    final_url: str = ""
    error: str = ""
    ms: float = 0.0


def probe_url(url: str, *, timeout_s: float = 1.5, max_redirects: int = 3,
              allow: Callable[[ParsedURL], bool] | None = None) -> Probe:
    """TCP connect + HTTP GET with short timeouts; follow redirects only while ``allow(url)`` holds.

    Never raises. Loopback/LAN https is probed without certificate checks (self-signed dev certs);
    public https is verified. Reads at most 64 KiB of an HTML body to find ``<title>``.
    """
    t0 = time.monotonic()
    cur = parse_url(url)
    if cur is None:
        return Probe(False, error="not an http(s) URL")
    for _ in range(max_redirects + 1):
        connect_host = "127.0.0.1" if cur.host.endswith(".localhost") else cur.host
        conn: http.client.HTTPConnection | None = None
        try:
            if cur.scheme == "https":
                ctx = ssl.create_default_context()
                if cur.host_class != "public":
                    ctx.check_hostname = False
                    ctx.verify_mode = ssl.CERT_NONE
                conn = http.client.HTTPSConnection(connect_host, cur.port, timeout=timeout_s, context=ctx)
            else:
                conn = http.client.HTTPConnection(connect_host, cur.port, timeout=timeout_s)
            conn.request("GET", cur.path.split("#", 1)[0] or "/",
                         headers={"Host": cur.netloc, "User-Agent": UA, "Connection": "close",
                                  "Accept": "text/html,application/xhtml+xml,*/*;q=0.8"})
            resp = conn.getresponse()
            ctype = (resp.getheader("Content-Type") or "").split(";", 1)[0].strip().lower()
            body = b""
            if resp.status < 300 and ctype in HTML_TYPES:
                body = resp.read(65536)
        except ConnectionRefusedError:
            return Probe(False, error="connection refused (nothing is listening)", ms=_ms(t0))
        except TimeoutError:
            return Probe(False, error=f"no answer within {timeout_s:.1f}s", ms=_ms(t0))
        except (OSError, http.client.HTTPException, ssl.SSLError, ValueError) as e:
            return Probe(False, error=f"{type(e).__name__}: {e}"[:200], ms=_ms(t0))
        finally:
            if conn is not None:
                conn.close()
        if resp.status in (301, 302, 303, 307, 308):
            loc = resp.getheader("Location") or ""
            nxt = parse_url(urljoin(cur.url, loc)) if loc else None
            if nxt is None or (allow is not None and not allow(nxt)):
                return Probe(False, resp.status, error=f"redirect to {loc[:120]!r} leaves the allowed hosts",
                             ms=_ms(t0))
            cur = nxt
            continue
        if resp.status >= 400:
            return Probe(False, resp.status, ctype, final_url=cur.url, error=f"HTTP {resp.status}", ms=_ms(t0))
        title = ""
        if body:
            m = TITLE_RE.search(body.decode("utf-8", "replace"))
            title = " ".join(m.group(1).split()) if m else ""
        return Probe(True, resp.status, ctype, title, cur.url, ms=_ms(t0))
    return Probe(False, error="too many redirects", ms=_ms(t0))


def _ms(t0: float) -> float:
    return round((time.monotonic() - t0) * 1000, 1)


# ------------------------------------------------------------------------------ targets

@dataclass
class CaptureTarget:
    """Something the capture stage can photograph."""
    kind: TargetKind
    source: str                    # URL or path as seen in the product/session
    why: str                       # product url | artifact (delivered) | artifact | entry file | file url
    priority: float = 0.0
    url: str = ""                  # url targets: what the browser opens (after redirects)
    origin: str = ""               # url targets: scheme://host:port
    host: str = ""
    host_class: str = ""
    path: str = ""                 # html/image/video/pdf: resolved local file
    serve_root: str = ""           # html/pdf: folder served read-only
    serve_rel: str = ""            # html/pdf: POSIX path of the file inside serve_root
    staged: bool = False           # serve a copy (page + referenced files): the folder is too broad
    stage_files: list[str] = field(default_factory=list)   # POSIX paths (relative to the page folder) to copy
    content_type: str = ""
    status: int | None = None
    title: str = ""
    event_ids: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    probe_ms: float = 0.0
    delivered: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Skipped:
    """A candidate we did not capture, with a machine-readable reason code."""
    source: str
    reason: str
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TargetPlan:
    """Targets in priority order (web first unless the product is media) + skipped candidates."""
    targets: list[CaptureTarget] = field(default_factory=list)
    skipped: list[Skipped] = field(default_factory=list)
    session_hosts: list[str] = field(default_factory=list)
    allow_network: bool = False
    probe_ms: float = 0.0

    def of(self, *kinds: str) -> list[CaptureTarget]:
        return [t for t in self.targets if t.kind in kinds]

    def to_dict(self) -> dict[str, Any]:
        return {"targets": [t.to_dict() for t in self.targets], "skipped": [s.to_dict() for s in self.skipped],
                "session_hosts": self.session_hosts, "allow_network": self.allow_network, "probe_ms": self.probe_ms}


def url_allowed(p: ParsedURL, *, seen_hosts: set[str], allow_network: bool) -> tuple[bool, str, str]:
    """Policy check for one URL -> (ok, reason code, detail)."""
    if p.host_class == "loopback":
        return True, "", ""
    if p.host_class == "lan":
        if p.host in seen_hosts:
            return True, "", ""
        return False, "refused_lan", f"LAN host {p.host} was not used in this session"
    if p.host_class == "public":
        if not allow_network:
            return False, "refused_public", "public URLs need allow_network=True"
        if p.scheme != "https":
            return False, "refused_http", "public URLs must be https"
        if p.host not in seen_hosts:
            return False, "refused_public", f"{p.host} did not appear in this session"
        return True, "", ""
    return False, "unsupported_scheme", f"host {p.host!r} is not usable"


def inspect_html(path: Path, limit: int = 512 * 1024) -> tuple[str, str, int]:
    """(title, needs-build reason or "", count of external references) for a local HTML file."""
    try:
        with open(path, "rb") as fh:
            text = fh.read(limit).decode("utf-8", "replace")
    except OSError:
        return "", "", 0
    m = TITLE_RE.search(text)
    title = " ".join(m.group(1).split()) if m else ""
    nb = NEEDS_BUILD_RE.search(text)
    reason = f"references {nb.group(0)[:80]!r} (needs a build step or dev server)" if nb else ""
    return title, reason, len(EXTERNAL_REF_RE.findall(text))


def referenced_files(page: Path, *, max_files: int = STAGE_MAX_FILES, max_bytes: int = STAGE_MAX_BYTES) -> list[str]:
    """Relative files a page references (src/href/poster + CSS ``url()``), inside the page's folder."""
    root = page.parent.resolve()
    out: list[str] = []
    total = 0
    queue = [page]
    seen: set[Path] = {page.resolve()}
    while queue and len(out) < max_files:
        cur = queue.pop(0)
        try:
            text = cur.read_text(encoding="utf-8", errors="replace")[:1_000_000]
        except OSError:
            continue
        refs = LOCAL_REF_RE.findall(text) + CSS_URL_RE.findall(text)
        for ref in refs:
            ref = unquote(ref.strip())
            if not ref or re.match(r"^[a-z][a-z0-9+.\-]*:", ref, re.I) or ref.startswith(("/", "\\", "//")):
                continue
            try:
                f = (cur.parent / ref).resolve()
                if f in seen or root not in f.parents or not f.is_file():
                    continue
                size = f.stat().st_size
            except (OSError, ValueError):
                continue
            seen.add(f)
            if total + size > max_bytes:
                continue
            total += size
            out.append(f.relative_to(root).as_posix())
            if f.suffix.lower() in (".css", ".html", ".htm"):
                queue.append(f)
    return out


def too_broad_to_serve(folder: Path) -> bool:
    """Home, a drive/file-system root, or a top-level personal folder: never expose those wholesale."""
    try:
        f = folder.resolve()
        home = Path.home().resolve()
    except OSError:
        return True
    if f == f.parent:
        return True
    personal = {home, home.parent, *(home / n for n in ("Desktop", "Downloads", "Documents", "Pictures", "Videos",
                                                        "Music", "OneDrive"))}
    return f in personal


def _artifact_paths(events: Sequence[Event], kinds: set[str]) -> list[tuple[Event, str]]:
    out = []
    for ev in events:
        if ev.kind == "artifact" and str(ev.data.get("kind") or "") in kinds:
            out.append((ev, str(ev.data.get("path") or "")))
    return out


def plan_targets(product: Product | None, events: Sequence[Event], *, allow_network: bool = False,
                 extra_urls: Sequence[str] = (), probe: bool = True, probe_timeout_s: float = 1.5,
                 caps: dict[str, int] | None = None) -> TargetPlan:
    """Build the capture plan. Never raises; never starts anything (it only probes URLs).

    URL candidates come from ``product.urls`` (+ ``extra_urls``, e.g. an agent brief); LAN and
    public hosts must also appear in the session events. HTML candidates are web artifacts,
    ``.html`` entry files and ``file://`` URLs. Media candidates are image/video/PDF artifacts.
    """
    t0 = time.monotonic()
    caps = {**DEFAULT_CAPS, **(caps or {})}
    product = product or Product()
    plan = TargetPlan(allow_network=allow_network)
    try:
        seen_urls = session_urls(events)
        seen = session_hosts(seen_urls)
        plan.session_hosts = sorted(seen)
        _plan_web(plan, product, events, seen_urls, seen, allow_network, extra_urls, probe, probe_timeout_s, caps)
        _plan_media(plan, events, caps)
    except Exception as e:  # pragma: no cover - defensive: the stage must never raise
        plan.skipped.append(Skipped("*", "internal", f"{type(e).__name__}: {e}"))
    media_first = (product.kind or "") == "media"
    order = {"url": 0, "html": 1, "video": 2, "image": 3, "pdf": 4}
    if media_first:
        order = {"video": 0, "image": 1, "url": 2, "html": 3, "pdf": 4}
    plan.targets.sort(key=lambda t: (order[t.kind], -t.priority))
    plan.probe_ms = _ms(t0)
    return plan


def _plan_web(plan: TargetPlan, product: Product, events: Sequence[Event], seen_urls: dict[str, list[str]],
              seen: set[str], allow_network: bool, extra_urls: Sequence[str], probe: bool,
              probe_timeout_s: float, caps: dict[str, int]) -> None:
    url_cands: list[tuple[str, str, float]] = []      # (raw, why, priority)
    html_cands: list[tuple[str, str, float, list[str], bool]] = []   # (path, why, prio, ids, delivered)
    for i, u in enumerate([*product.urls, *extra_urls]):
        why = "product url" if i < len(product.urls) else "brief url"
        if u.lower().startswith("file://"):
            html_cands.append((u, "file url", 0.75, seen_urls.get(u, []), False))
        else:
            url_cands.append((u, why, round(1.0 - 0.05 * i, 3)))
    for ev, path in _artifact_paths(events, {"web"}):
        if path:
            delivered = bool(ev.data.get("delivered"))
            html_cands.append((path, "artifact (delivered)" if delivered else "artifact", 0.8 if delivered else 0.7,
                               [ev.id], delivered))
    for path in product.entry_files:
        if path.lower().endswith((".html", ".htm")):
            html_cands.append((path, "entry file", 0.6, [], False))
    from ..story.onscreen import is_test_path   # lazy: the story package is not needed to plan media
    if any(not is_test_path(c[0]) for c in html_cands):
        for c in [c for c in html_cands if is_test_path(c[0])]:
            plan.skipped.append(Skipped(c[0], "test_page", "a test/fixture/report page; the product has its own"))
        html_cands = [c for c in html_cands if not is_test_path(c[0])]

    # ---- URLs: policy, dedupe, probe in parallel
    keyed: dict[str, tuple[ParsedURL, str, float]] = {}
    for raw, why, prio in url_cands:
        p = parse_url(raw)
        if p is None:
            plan.skipped.append(Skipped(raw, "unsupported_scheme", "not an http(s) URL"))
            continue
        ok, code, detail = url_allowed(p, seen_hosts=seen, allow_network=allow_network)
        if not ok:
            plan.skipped.append(Skipped(raw, code, detail))
            continue
        if p.key in keyed:
            plan.skipped.append(Skipped(raw, "duplicate", f"same server/page as {keyed[p.key][0].url}"))
            continue
        keyed[p.key] = (p, why, prio)

    def allow(p: ParsedURL) -> bool:
        return url_allowed(p, seen_hosts=seen, allow_network=allow_network)[0]

    probes: dict[str, Probe] = {}
    if keyed:
        if probe:
            with cf.ThreadPoolExecutor(max_workers=min(8, len(keyed)), thread_name_prefix="sr-probe") as ex:
                futs = {k: ex.submit(probe_url, p.url, timeout_s=probe_timeout_s, allow=allow)
                        for k, (p, _, _) in keyed.items()}
                for k, f in futs.items():
                    try:
                        probes[k] = f.result(timeout=probe_timeout_s * 10 + 5)
                    except Exception as e:  # pragma: no cover - defensive
                        probes[k] = Probe(False, error=f"{type(e).__name__}: {e}")
        else:
            probes = {k: Probe(True, final_url=p.url) for k, (p, _, _) in keyed.items()}
    web: list[CaptureTarget] = []
    final_keys: set[str] = set()
    for k, (p, why, prio) in keyed.items():
        pr = probes[k]
        if not pr.ok:
            code = "http_error" if pr.status else "unreachable"
            plan.skipped.append(Skipped(p.url, code, pr.error))
            continue
        if pr.content_type and not pr.content_type.startswith(RENDERABLE_TYPES):
            plan.skipped.append(Skipped(p.url, "not_renderable", f"content type {pr.content_type}"))
            continue
        final = parse_url(pr.final_url or p.url) or p
        if final.key in final_keys:
            plan.skipped.append(Skipped(p.url, "duplicate", f"redirects to {final.url}"))
            continue
        final_keys.add(final.key)
        ids = list(dict.fromkeys(i for u, ids in seen_urls.items() if (q := parse_url(u)) and q.key == p.key
                                 for i in ids))[:8]
        t = CaptureTarget("url", p.url, why, prio if pr.content_type in ("", *HTML_TYPES) else prio - 0.3,
                          url=final.url, origin=final.origin, host=final.host, host_class=final.host_class,
                          content_type=pr.content_type, status=pr.status, title=pr.title, event_ids=ids,
                          probe_ms=pr.ms)
        web.append(t)

    # ---- local HTML files
    seen_paths: set[str] = set()
    for raw, why, prio, ids, delivered in html_cands:
        path = resolve_path(raw)
        if path is None:
            plan.skipped.append(Skipped(raw, "not_found", "not an absolute local path"))
            continue
        try:
            exists = path.is_file()
            rp = path.resolve()
        except OSError:
            exists, rp = False, path
        key = str(rp).casefold() if sys.platform == "win32" else str(rp)
        if key in seen_paths:
            continue
        seen_paths.add(key)
        if not exists:
            plan.skipped.append(Skipped(raw, "not_found", "file does not exist (any more)"))
            continue
        title, needs_build, ext_refs = inspect_html(rp)
        if needs_build:
            plan.skipped.append(Skipped(raw, "needs_build", needs_build))
            continue
        t = CaptureTarget("html", raw, why, prio, path=str(rp), title=title, event_ids=ids, delivered=delivered)
        if too_broad_to_serve(rp.parent):
            t.staged = True
            t.serve_root = str(rp.parent)
            t.stage_files = referenced_files(rp)
            t.notes.append("folder too broad to serve: staging a copy of the page and the files it references")
        else:
            t.serve_root = str(rp.parent)
        t.serve_rel = rp.name
        if ext_refs and not plan.allow_network:
            t.notes.append(f"page references {ext_refs} external resource(s); they are blocked without "
                           "allow_network, so it may render unstyled")
        web.append(t)

    web.sort(key=lambda t: (t.kind != "url", -t.priority))
    for t in web[caps["web"]:]:
        plan.skipped.append(Skipped(t.source, "over_cap", f"more than {caps['web']} web targets"))
    plan.targets.extend(web[:caps["web"]])


def _plan_media(plan: TargetPlan, events: Sequence[Event], caps: dict[str, int]) -> None:
    seen_paths: set[str] = set()
    counts: dict[str, int] = {}
    cands = []
    for ev, raw in _artifact_paths(events, set(MEDIA_KINDS)):
        kind = MEDIA_KINDS[str(ev.data["kind"])]
        rank = ev.data.get("media_rank") or {}
        if rank.get("junk"):                    # a contact sheet / debug render (session.mediarank)
            plan.skipped.append(Skipped(raw or ev.id, "debug_media", ", ".join(rank.get("why") or [])[:80]))
            continue
        delivered = bool(ev.data.get("delivered"))
        prio = {"video": 0.75, "image": 0.7, "pdf": 0.5}[kind] + (0.1 if delivered else 0.0)
        if kind == "image" and rank:
            prio += 0.2 * (float(rank.get("score", 0.5)) - 0.5)     # the best-looking pictures first
        cands.append((prio, -ev.t, kind, raw, ev, delivered))
    cands.sort(key=lambda c: (-c[0], c[1]))
    for prio, _, kind, raw, ev, delivered in cands:
        path = resolve_path(raw)
        if path is None or not _is_file(path):
            alt = resolve_path(str(ev.data.get("preview_path") or ""))
            if kind == "image" and alt is not None and _is_file(alt):
                path = alt
            else:
                plan.skipped.append(Skipped(raw or ev.id, "not_found", "file does not exist (any more)"))
                continue
        key = str(path.resolve()).casefold()
        if key in seen_paths:
            continue
        seen_paths.add(key)
        if counts.get(kind, 0) >= caps.get(kind, 0):
            plan.skipped.append(Skipped(raw, "over_cap", f"more than {caps.get(kind, 0)} {kind} targets"))
            continue
        counts[kind] = counts.get(kind, 0) + 1
        t = CaptureTarget(kind, raw, "artifact (delivered)" if delivered else "artifact", round(prio, 3),
                          path=str(path.resolve()), title=str(ev.data.get("title") or path.name), event_ids=[ev.id],
                          delivered=delivered)
        if kind == "pdf":
            if too_broad_to_serve(path.parent):
                t.staged, t.stage_files = True, []
            t.serve_root, t.serve_rel = str(path.resolve().parent), path.name
        plan.targets.append(t)


def _is_file(p: Path) -> bool:
    try:
        return p.is_file()
    except OSError:
        return False
