"""Redaction: positive cases (must mask) and negative cases (must keep ordinary code readable)."""
import pytest

from showreel_core.contracts import Event
from showreel_core.session.redact import EMAIL, IP, SECRET, Redactor, looks_secret_value, redact_events

R = Redactor(home="/home/tester")

# Fake credentials assembled at runtime so the repo never contains a key-shaped literal.
OPENAI = "sk-" + "proj-" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4"
ANTHROPIC = "sk-ant-" + "api03-" + "Zz9Yy8Xx7Ww6Vv5Uu4Tt3Ss2Rr1Qq0"
GITHUB = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"
GITHUB_PAT = "github_pat_" + "11ABCDEFG0" + "a1b2c3d4e5f6g7h8i9j0" * 3
SLACK = "xoxb-" + "123456789012-123456789012-AbCdEfGhIjKlMnOpQrStUvWx"
AWS = "AKIA" + "IOSFODNN7EXAMPLQ"
GOOGLE = "AIza" + "SyA1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q"
JWT = "eyJ" + "hbGciOiJIUzI1NiJ9" + "." + "eyJ" + "zdWIiOiIxMjM0NTY3ODkwIn0" + "." + "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
HF = "hf_" + "AbCdEfGhIjKlMnOpQrStUvWxYz012345"
STRIPE = "sk_" + "live_" + "4eC39HqLyjWDarjtT1zdp7dc"
TELEGRAM = "123456789:" + "AA" + "HdqTcvCH1vGWJxfSeofSAs0K5PALDsaw"
PEM = "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA\nabc\n-----END RSA PRIVATE KEY-----"
RANDOM40 = "Q7x" + "Lm2pR9vT4kW8zN1bY6cJ3hF5dS0gA7eUu"


@pytest.mark.parametrize("token", [OPENAI, ANTHROPIC, GITHUB, GITHUB_PAT, SLACK, AWS, GOOGLE, JWT, HF, STRIPE, TELEGRAM])
def test_vendor_token_shapes(token):
    out = R.text(f"key is {token} ok")
    assert token not in out and SECRET in out and out.startswith("key is ") and out.endswith(" ok")


@pytest.mark.parametrize("text,leak", [
    ("export OPENAI_API_KEY=abcd1234efgh5678", "abcd1234efgh5678"),
    ('{"api_key": "zz99yy88xx77ww66"}', "zz99yy88xx77ww66"),
    ("password: hunter2hunter2", "hunter2hunter2"),
    ("DB_PASSWORD='p4ssw0rd!long'", "p4ssw0rd!long"),
    ("STRIPE_KEY=rk9Ab8Cd7Ef6Gh5Ij4", "rk9Ab8Cd7Ef6Gh5Ij4"),
    ("client_secret = \"7f3c9a1e5b2d8f4a\"", "7f3c9a1e5b2d8f4a"),
    ("$env:HF_TOKEN=\"t0k3nValue123456\"", "t0k3nValue123456"),
    ("mytool --api-key Kx81mQ02pz77wq --verbose", "Kx81mQ02pz77wq"),
    ("curl -H 'Authorization: Bearer abc.def-123_456ghi' x", "abc.def-123_456ghi"),
    ("Authorization: token 0123456789abcdef0123", "0123456789abcdef0123"),
    ("git clone https://bob:s3cretPass@github.com/x/y.git", "s3cretPass"),
    ("https://api.example.com/v1?api_key=Zx81Qw92Er03&x=1", "Zx81Qw92Er03"),
    ("https://hooks.slack.com/services/T000/B000/XXXXabcd1234", "XXXXabcd1234"),
    ("Cookie: session=abcdef0123456789; theme=dark", "abcdef0123456789"),
    (f"blob {RANDOM40} end", RANDOM40),
    (PEM, "MIIEowIBAAKCAQEA"),
])
def test_assignment_header_url_and_entropy_secrets(text, leak):
    assert leak not in R.text(text)


def test_learned_secret_is_masked_everywhere():
    r = Redactor(home="/home/tester")
    r.learn("MY_SERVICE_TOKEN=Abc123Def456Ghi7")
    assert r.text("echo Abc123Def456Ghi7") == f"echo {SECRET}"


def test_emails_and_exemptions():
    assert R.text("mail jane.doe@acme.io now") == f"mail {EMAIL} now"
    assert R.text("git@github.com:org/repo.git") == "git@github.com:org/repo.git"
    assert R.text("user@example.com") == "user@example.com"
    assert R.text("npm i react@18.2.0") == "npm i react@18.2.0"


@pytest.mark.parametrize("text,expected", [
    ("C:\\Users\\Alice\\proj\\a.py", "~\\proj\\a.py"),
    ("C:/Users/Alice/proj", "~/proj"),
    ("C:\\\\Users\\\\Alice\\\\x", "~\\\\x"),
    ("/Users/alice/Library/x", "~/Library/x"),
    ("/home/bob/.config", "~/.config"),
    ("/c/Users/Alice/x", "~/x"),
    ("/mnt/c/Users/Alice/x", "~/x"),
    ("C:\\Users\\Public\\x", "C:\\Users\\Public\\x"),
    ("/home/tester/work", "~/work"),
])
def test_home_paths(text, expected):
    assert R.text(text) == expected


def test_ips_opt_in():
    assert R.text("host 10.1.2.3") == "host 10.1.2.3"
    r = Redactor(home="/home/tester", redact_ips=True)
    assert r.text("host 10.1.2.3 and 127.0.0.1") == f"host {IP} and 127.0.0.1"


@pytest.mark.parametrize("text", [
    "commit a94a8fe5ccb19ba61c4c0873d391e987982fbbd3 fixed it",            # git SHA
    "sha256: 9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
    "id 123e4567-e89b-12d3-a456-426614174000",                             # UUID
    "api_key = os.environ[\"OPENAI_API_KEY\"]",                             # code, not a literal
    "token = get_token()",
    "max_tokens=4096",
    "password: str",
    "PWD=/srv/app",
    "TOKEN_FILE=/etc/app/token",
    "sort_key = 'name_and_date'",
    "the_very_long_snake_case_identifier_for_testing_purposes_v2",
    "WhatIfCubed_Ep2_SomethingElse_FinalCut4K_Master",
    "AbstractSingletonProxyFactoryBean2024Impl",
    "integrity sha512-Q7xLm2pR9vT4kW8zN1bY6cJ3hF5dS0gA7eUuQ7xLm2pR9vT4kW8zN1bY6cJ3hF5dS0gA7eUu==",
    "color: #ff00aa; margin: 12px",
    "API_KEY=your-api-key-here",
    "SECRET_KEY=${SECRET_KEY}",
    "scikit-learn and disk-usage-monitor-service-names",
])
def test_ordinary_code_is_kept(text):
    assert R.text(text) == text


def test_looks_secret_value():
    assert looks_secret_value("abcd1234efgh")
    assert not looks_secret_value("os.environ.get")
    assert not looks_secret_value("12345678")
    assert not looks_secret_value("/path/to/file")
    assert not looks_secret_value("OTHER_ENV_NAME")


def test_redact_events_keeps_copied_asset_path_and_counts():
    shot = Event(id="e1", t=0, kind="screenshot", tool="browser", title="C:\\Users\\Alice\\s.png", summary="",
                 data={"path": "C:\\Users\\Alice\\job\\assets\\e1_s.png", "asset": True, "src": "C:\\Users\\Alice\\s.png"})
    art = Event(id="e2", t=0, kind="artifact", tool="", title="", summary="",
                data={"path": "C:\\Users\\Alice\\site\\index.html", "preview_path": "C:\\Users\\Alice\\job\\p.png",
                      "asset": True})
    note = Event(id="e3", t=0, kind="assistant_note", tool="", title="", summary="",
                 data={"text": "set GITHUB_TOKEN=" + GITHUB, "_private": "C:\\Users\\Alice"})
    r = redact_events([shot, art, note], Redactor(home="C:\\Users\\Alice"))
    assert shot.data["path"].startswith("C:\\Users\\Alice")      # our copy: still usable
    assert shot.data["src"] == "~\\s.png" and shot.title == "~\\s.png"
    assert art.data["path"] == "~\\site\\index.html"              # the user's file: redacted
    assert art.data["preview_path"].startswith("C:\\Users\\Alice")
    assert GITHUB not in note.data["text"] and note.data["_private"] == "C:\\Users\\Alice"
    assert r.counts["home"] >= 2 and r.counts["token"] + r.counts["assign"] + r.counts["learned"] >= 1
