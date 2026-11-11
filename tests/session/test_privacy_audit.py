"""Privacy regressions (audit 2026-11-11): a synthetic session full of credentials and PII must not reach the
events, the storyboard digest or the product draft that the film and the LLM see."""
import json
from dataclasses import asdict

import pytest
from session_synth import Transcript

from showreel_core.contracts import Event
from showreel_core.session import analyze_rows
from showreel_core.session.redact import PHONE, SECRET, USER, Redactor, redact_events

# Fake values assembled at runtime so the repo never contains a key-shaped literal.
OPENAI = "sk-" + "proj-" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4"
AWS_SECRET = "wJalrXUtnFEMI" + "/K7MDENG/bPxRfiCYzq81KEYzz"
PASSPHRASE = "correcthorse" + "batterystaple"
SHORTPW = "Tr0u" + "b4d!x"
ODDVAL = "Zq" + "9-kk"        # a short value under a name nothing would call secret
EMAIL = "alice.smith" + "@gmail.com"
ENV = (f"OPENAI_API_KEY={OPENAI}\nAWS_SECRET_ACCESS_KEY={AWS_SECRET}\nPASSWORD={PASSPHRASE}\n"
       f"ADMIN_PASS={SHORTPW}\nWIDGET_MODE={ODDVAL}\nCONTACT={EMAIL}\nPHONE=+1 (415) 555-0132\n")


def _session():
    t = Transcript()
    t.user(f"Build Tempo, a pomodoro app. Mail {EMAIL} or call +92 300 1234567. Ünïcødé 日本語 مرحبا 🍅")
    t.call("write_file", {"path": "C:\\Users\\alice\\tempo\\.env", "content": ENV}, {"bytes_written": 300})
    t.call("terminal", {"command": "cat /home/alice/tempo/.env"}, {"output": ENV, "exit_code": 0})
    t.call("terminal", {"command": "whoami && npm run dev"},
           {"output": "alice\nalice@laptop:~/tempo$ npm run dev\n  Local: http://localhost:5173/", "exit_code": 0})
    t.call("terminal", {"command": "git log -1"},
           {"output": f"commit abc\nAuthor: Alice Smith <{EMAIL}>\n\n    feat: timer", "exit_code": 0})
    t.say(f"Done. Admin password is {SHORTPW}; the key {OPENAI} lives in .env.")
    return t.rows


def _all_text(b) -> str:
    return json.dumps({"events": [e.to_dict() for e in b.events], "product": asdict(b.product),
                       "evidence": b.product_evidence, "meta": b.meta, "digest": b.digest}, ensure_ascii=False)


@pytest.mark.parametrize("leak", [OPENAI, AWS_SECRET, PASSPHRASE, SHORTPW, ODDVAL, EMAIL, "555-0132", "1234567",
                                  "Users\\\\alice", "/home/alice", "alice@laptop", "Alice Smith", '"alice"'])
def test_synthetic_session_leaks_nothing(tmp_path, leak):
    b = analyze_rows(_session(), {"cwd": "C:\\Users\\alice\\tempo"}, session_id="s", assets_dir=tmp_path,
                     redactor=Redactor(home="C:\\Users\\alice"))
    assert b.events and b.digest
    assert leak.lower() not in _all_text(b).lower()


def test_credential_file_values_are_masked_whatever_the_key():
    ev = Event(id="e1", t=0, kind="file_write", tool="write_file", title=".env", summary="",
               data={"path": "~/app/.env.local", "lines": ["NODE_ENV=production", "WIDGET_MODE=" + ODDVAL, "# note",
                                                          "  \"type\": \"service_account\","]})
    later = Event(id="e2", t=1, kind="assistant_note", tool="", title="", summary="", data={"text": "mode Zq9-kk ok"})
    redact_events([ev, later], Redactor(home="/home/tester"))
    assert ev.data["lines"] == [f"NODE_ENV={SECRET}", f"WIDGET_MODE={SECRET}", "# note", f"  \"type\": {SECRET},"]
    assert ev.data["path"] == "~/app/.env.local"
    assert later.data["text"] == "mode Zq9-kk ok"          # a short non-secret value is not hunted everywhere


@pytest.mark.parametrize("text,expect", [
    ("PASSWORD=correcthorsebatterystaple", f"PASSWORD={SECRET}"),
    ("DB_PASS=hunter22", f"DB_PASS={SECRET}"),
    ("SMTP_PWD=letmein99", f"SMTP_PWD={SECRET}"),
    ("call +44 20 7946 0958 or (415) 555-0132", f"call {PHONE} or {PHONE}"),
    ("jane@janes-mbp tempo % npm test", f"{USER} tempo % npm test"),
    ("root@abc123:/app# ls", f"{USER}:/app# ls"),
    ('git config --global user.name "Jane Doe"', f"git config --global user.name {USER}"),
    ("Signed-off-by: Jane Doe <jane@corp.io>", f"Signed-off-by: {USER} <‹email›>"),
])
def test_new_pii_passes(text, expect):
    assert Redactor(home="/home/tester").text(text) == expect


@pytest.mark.parametrize("text", [
    "first_pass = compute_all()", "password = getpass.getpass()", "password_field = models.CharField",
    "I will run the tests at 10:30 on 2026-11-11 (took 12.5 s)", "+12 −0 lines, +120 -30", "> tempo@0.1.0 dev",
    "git@github.com:org/repo.git", "UTC+05:00 2026-11-11T21:27:59+05:00", "timestamp 1793000000.123", "react@18.2.0",
])
def test_new_passes_keep_ordinary_text(text):
    assert Redactor(home="/home/will").text(text) == text


def test_login_name_masked_only_where_it_identifies():
    r = Redactor(home="/home/will")
    assert r.text("will") == USER                                   # whoami output
    assert r.text("will@Wills-MacBook-Pro tempo % ls") == f"{USER} tempo % ls"
    assert r.text("it will work") == "it will work"                # an ordinary word stays


@pytest.mark.parametrize("text,expect", [
    ("/c/Users/Alice Smith/proj/app.py", "~/proj/app.py"),            # git-bash: Hermes's terminal on Windows
    ("/mnt/c/Users/Alice Smith/proj", "~/proj"),                      # WSL
    ("cd 'c:/users/alice smith/proj' && ls", "cd '~/proj' && ls"),
    (r"C:\Users\Alice Smith\proj\app.py", r"~\proj\app.py"),
])
def test_home_with_a_space_is_masked_in_every_spelling(text, expect):
    """Audit 2026-11-11: the generic home patterns stop at a space, so an MSYS/WSL/lower-case spelling of
    C:/Users/Alice Smith left '~ Smith' on screen (and broke the capture's path resolution)."""
    assert Redactor(home=r"C:\Users\Alice Smith").text(text) == expect
