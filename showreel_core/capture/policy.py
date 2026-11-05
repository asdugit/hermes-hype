"""Network policy of the capture browser (pure logic, unit-tested without a browser).

Default: the page may load only from its own origin (every loopback spelling of a loopback port
counts as the same server) plus ``data:``/``blob:`` and the browser's internal schemes. Everything
else is failed with ``BlockedByClient`` by request interception, and DNS for any other host name is
disabled with ``--host-resolver-rules`` as a second wall (covers WebSockets, cross-site iframes and
popups that request interception does not see). Write requests (POST/PUT/PATCH/DELETE) are blocked
even on the target origin, so a capture never changes the app's data.

``third_party=True`` (the caller's ``allow_network``) additionally lets the page GET public http(s)
resources (CDN scripts, web fonts) and turns DNS back on.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from .targets import parse_url

INTERNAL_SCHEMES = ("data:", "blob:", "about:", "chrome-extension:", "chrome:", "devtools:")
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
LOOPBACK_ALIASES = ("127.0.0.1", "localhost", "[::1]")

POLICY_DISCLOSURE = (
    "Showreel's capture browser loads only the product's own origin (plus data:/blob:). Every other host is "
    "blocked by request interception and by disabling DNS for all other names; write requests (POST/PUT/PATCH/"
    "DELETE) are blocked so capturing never changes your app's data. It never starts servers or runs commands. "
    "With allow_network, public https pages that appeared in the session may be opened and pages may load "
    "public CDN assets (GET only).")


def origin_of(url: str) -> str:
    """``scheme://host[:port]`` in canonical form (lower case, default ports dropped), or ""."""
    p = parse_url(url)
    if p is not None:
        return p.origin
    try:
        sp = urlsplit(url)
    except ValueError:
        return ""
    return f"{sp.scheme.lower()}://{sp.netloc.lower()}" if sp.scheme and sp.netloc else ""


def origin_aliases(origin: str) -> set[str]:
    """The origin plus every loopback spelling of the same port (127.0.0.1, localhost, [::1])."""
    p = parse_url(origin + "/")
    if p is None:
        return {origin}
    out = {p.origin}
    if p.host_class == "loopback" and not p.host.endswith(".localhost"):
        for h in LOOPBACK_ALIASES:
            q = parse_url(f"{p.scheme}://{h}:{p.port}/")
            if q is not None:
                out.add(q.origin)
    return out


@dataclass
class NetPolicy:
    """Per-page request rules. :meth:`decide` -> ("continue", rewritten url or "") | ("block", reason)."""
    origins: frozenset[str] = frozenset()
    rewrite_origin: str = ""        # served local pages: requests to this origin outside the token prefix
    rewrite_prefix: str = ""        # are rewritten under it, so root-absolute asset paths keep working
    third_party: bool = False
    writes: bool = False
    stats: dict[str, int] = field(default_factory=lambda: {"allowed": 0, "blocked": 0, "third_party": 0,
                                                             "writes_blocked": 0, "rewritten": 0})

    @classmethod
    def for_origin(cls, origin: str, *, third_party: bool = False, writes: bool = False,
                   rewrite_prefix: str = "") -> NetPolicy:
        """Policy allowing ``origin`` (with loopback aliases) and, for served pages, a token prefix."""
        return cls(frozenset(origin_aliases(origin)), origin if rewrite_prefix else "", rewrite_prefix,
                   third_party, writes)

    def decide(self, url: str, method: str = "GET") -> tuple[str, str]:
        low = url[:24].lower()
        if low.startswith(INTERNAL_SCHEMES):
            return "continue", ""
        method = (method or "GET").upper()
        org = origin_of(url)
        if org and org in self.origins:
            if method not in SAFE_METHODS and not self.writes:
                self.stats["writes_blocked"] += 1
                return "block", f"write request ({method}) blocked"
            if self.rewrite_prefix and org == self.rewrite_origin and not url.startswith(self.rewrite_prefix):
                path = url[len(org):].lstrip("/")
                self.stats["rewritten"] += 1
                return "continue", self.rewrite_prefix + path
            self.stats["allowed"] += 1
            return "continue", ""
        if self.third_party and low.startswith(("http:", "https:")) and method in SAFE_METHODS:
            self.stats["third_party"] += 1
            return "continue", ""
        self.stats["blocked"] += 1
        return "block", "off-origin request blocked"


def resolver_rules(hosts: Iterable[str], *, open_dns: bool = False) -> str:
    """Value for ``--host-resolver-rules``: no name resolves except loopback and ``hosts``.

    ``open_dns=True`` returns "" (the flag then clears the renderer's default MAP rule; the last
    occurrence of a Chromium switch wins).
    """
    if open_dns:
        return ""
    excl: list[str] = ["127.0.0.1", "localhost", "[::1]", "::1", "*.localhost"]
    for h in hosts:
        h = h.strip().lower()
        if not h:
            continue
        for v in ((f"[{h}]", h) if ":" in h else (h,)):
            if v not in excl:
                excl.append(v)
    return "MAP * ~NOTFOUND , " + " , ".join(f"EXCLUDE {h}" for h in excl)
