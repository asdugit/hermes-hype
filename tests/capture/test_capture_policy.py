"""Network policy of the capture browser (pure logic)."""
from __future__ import annotations

from showreel_core.capture.policy import NetPolicy, origin_aliases, origin_of, resolver_rules


def test_origin_helpers():
    assert origin_of("http://LOCALHOST:5173/x?y") == "http://localhost:5173"
    assert origin_of("https://a.example/") == "https://a.example"
    assert origin_aliases("http://localhost:5173") == {"http://localhost:5173", "http://127.0.0.1:5173",
                                                       "http://[::1]:5173"}
    assert origin_aliases("https://a.example") == {"https://a.example"}


def test_same_origin_and_loopback_aliases_allowed():
    p = NetPolicy.for_origin("http://localhost:5173")
    assert p.decide("http://localhost:5173/src/main.js") == ("continue", "")
    assert p.decide("http://127.0.0.1:5173/@vite/client") == ("continue", "")
    assert p.decide("http://127.0.0.1:5174/other")[0] == "block"
    assert p.decide("https://fonts.googleapis.com/css2")[0] == "block"
    assert p.decide("data:image/png;base64,xx") == ("continue", "")
    assert p.decide("blob:http://localhost:5173/uuid") == ("continue", "")
    assert p.stats["blocked"] == 2


def test_writes_blocked_unless_allowed():
    p = NetPolicy.for_origin("http://127.0.0.1:8000")
    verdict, why = p.decide("http://127.0.0.1:8000/api/notes", "DELETE")
    assert verdict == "block" and "write" in why
    assert p.decide("http://127.0.0.1:8000/api", "OPTIONS")[0] == "continue"
    assert NetPolicy.for_origin("http://127.0.0.1:8000", writes=True).decide("http://127.0.0.1:8000/a", "POST")[0] \
        == "continue"


def test_third_party_get_only_when_allowed():
    p = NetPolicy.for_origin("http://127.0.0.1:8000", third_party=True)
    assert p.decide("https://cdn.example/x.js") == ("continue", "")
    assert p.decide("https://cdn.example/collect", "POST")[0] == "block"


def test_root_paths_rewritten_under_token_prefix():
    base = "http://127.0.0.1:40000/abc123/"
    p = NetPolicy.for_origin("http://127.0.0.1:40000", rewrite_prefix=base)
    assert p.decide(base + "index.html") == ("continue", "")
    assert p.decide("http://127.0.0.1:40000/assets/site.css") == ("continue", base + "assets/site.css")
    assert p.decide("http://localhost:40000/favicon.ico") == ("continue", "")   # alias, not rewritten origin


def test_resolver_rules():
    r = resolver_rules(["192.168.1.9", "fd12::1"])
    assert r.startswith("MAP * ~NOTFOUND , EXCLUDE 127.0.0.1 , EXCLUDE localhost")
    assert "EXCLUDE 192.168.1.9" in r and "EXCLUDE [fd12::1]" in r and "EXCLUDE *.localhost" in r
    assert resolver_rules(["x"], open_dns=True) == ""
