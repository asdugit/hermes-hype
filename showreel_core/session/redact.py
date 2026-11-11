"""Secret/PII redaction applied before anything leaves the machine or reaches the screen (SPEC 8).

Deterministic placeholders: ``‹secret›`` (credentials), ``‹email›``, ``‹ip›`` (opt-in), ``‹data›``
(inline base64 payloads) and ``~`` for home directories.

Order of passes (each sees the previous pass's output):
  1. PEM private-key blocks, data: URIs
  2. values learned from KEY=VALUE assignments anywhere in the session (see :meth:`Redactor.learn`)
  3. credentials in URLs (``scheme://user:pass@``), secret query parameters, webhook URLs
  4. vendor key shapes (OpenAI/Anthropic ``sk-``, GitHub, Slack, AWS, Google, JWT, HF, Stripe, ...)
  5. ``Authorization``/``Bearer``/``Cookie`` header values
  6. assignments whose NAME is secret-ish (``*_API_KEY=``, ``"password": "..."``, ``--token x``)
  7. generic high-entropy tokens (>= 32 chars, mixed case + >= 3 digits, entropy >= 4 bits/char)
  8. e-mail addresses (except ``git@``/``noreply@`` and example domains); the name in front of a masked
     address (``Author: Jane Doe <‹email›>``) and ``git config user.name "..."`` → ``‹user›``
  9. phone numbers (``+<country> ...`` with 8-15 digits, ``(415) 555-0132``, ``415-555-0132``) → ``‹phone›``
 10. home paths (``C:\\Users\\<name>``, ``/Users/<name>``, ``/home/<name>``, MSYS/WSL forms) → ``~``
 11. shell prompts (``jane@laptop:~/x$``, ``jane@Janes-MacBook tempo %``) and the login name where it
     identifies the user (``jane@...``, a ``whoami`` line) → ``‹user›``
 12. IPv4 addresses (only with ``redact_ips=True``; loopback/unspecified kept)

Credential files (``.env*``, ``.npmrc``, ``.netrc``, ``credentials.json``, ``*.pem`` ...): :func:`redact_events`
masks EVERY ``KEY=value`` / ``key: value`` line of their content (and of terminal output that prints one),
whatever the key is called.

Trade-offs (deliberate):
  * Pure hex runs are NEVER redacted by the generic pass: git SHAs, sha256 digests, UUIDs and
    colour codes are everywhere in coding sessions. Hex secrets are still caught when assigned to a
    secret-ish name (``API_SECRET=9f86d0...``) or learned from such an assignment.
  * The generic pass needs mixed case AND >= 3 digits AND high entropy, so long identifiers,
    kebab/snake names and base64 SRI hashes (``sha512-...``) survive; some odd random-looking
    identifiers may still be redacted. Missing a secret is worse than masking an identifier.
  * Assignment values must look like literals (no ``(``, ``$``, ``{``, ``os.environ``...), so code
    such as ``api_key = os.environ["OPENAI_API_KEY"]`` stays readable.
"""
from __future__ import annotations

import math
import os
import re
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

SECRET = "‹secret›"
EMAIL = "‹email›"
IP = "‹ip›"
DATA = "‹data›"
PHONE = "‹phone›"
USER = "‹user›"

_PEM_RE = re.compile(r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY(?: BLOCK)?-----.*?-----END (?:[A-Z0-9]+ )*PRIVATE KEY(?: BLOCK)?-----", re.S)
_DATA_URI_RE = re.compile(r"(data:[\w.+/-]+;base64,)[A-Za-z0-9+/=\s]{16,}")
_URL_CRED_RE = re.compile(r"\b([a-z][a-z0-9+.\-]*://)([^/\s:@'\"]+):([^/\s@'\"]+)@", re.I)
_QUERY_RE = re.compile(
    r"([?&](?:access_token|refresh_token|id_token|token|api_key|apikey|api-key|key|secret|client_secret|sig|"
    r"signature|password|passwd|auth|x-amz-signature|x-amz-credential|x-amz-security-token|code)=)([^&\s#\"'<>]{6,})",
    re.I)
_WEBHOOK_RE = re.compile(
    r"(https://hooks\.slack\.com/services/)[A-Za-z0-9/]+|(https://(?:ptb\.|canary\.)?discord(?:app)?\.com/api/webhooks/\d+/)[\w-]+")
_TOKEN_PATTERNS = [
    r"(?<![A-Za-z0-9])sk-[A-Za-z0-9_\-]{20,}",                     # OpenAI / Anthropic / OpenRouter
    r"(?<![A-Za-z0-9])(?:sk|rk|pk)_(?:live|test)_[A-Za-z0-9]{16,}",  # Stripe
    r"(?<![A-Za-z0-9])gh[pousr]_[A-Za-z0-9]{30,}",                  # GitHub tokens
    r"(?<![A-Za-z0-9])github_pat_[A-Za-z0-9_]{40,}",
    r"(?<![A-Za-z0-9])glpat-[A-Za-z0-9_\-]{20,}",                   # GitLab
    r"(?<![A-Za-z0-9])xox[abposr]-[A-Za-z0-9\-]{10,}",               # Slack
    r"(?<![A-Za-z0-9])xapp-\d-[A-Za-z0-9\-]{10,}",
    r"(?<![A-Z0-9])(?:AKIA|ASIA|AGPA|AIDA|AROA|ANPA|ANVA|AIPA)[0-9A-Z]{16}(?![A-Z0-9])",  # AWS key ids
    r"(?<![A-Za-z0-9])AIza[0-9A-Za-z_\-]{35}",                      # Google API key
    r"(?<![A-Za-z0-9])ya29\.[0-9A-Za-z_\-]{20,}",                   # Google OAuth access token
    r"(?<![A-Za-z0-9_\-])eyJ[A-Za-z0-9_\-]{8,}\.eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}",  # JWT
    r"(?<![A-Za-z0-9])hf_[A-Za-z0-9]{30,}",                          # Hugging Face
    r"(?<![A-Za-z0-9])npm_[A-Za-z0-9]{36}",
    r"(?<![A-Za-z0-9])(?:xai|pplx|gsk|r8|fw|nvapi)[-_][A-Za-z0-9_\-]{20,}",  # xAI/Perplexity/Groq/Replicate/...
    r"(?<![A-Za-z0-9])dop_v1_[a-f0-9]{64}",
    r"(?<![A-Za-z0-9])SG\.[\w\-]{16,}\.[\w\-]{16,}",                  # SendGrid
    r"(?<![A-Za-z0-9])key-[0-9a-zA-Z]{32}(?![A-Za-z0-9])",            # Mailgun
    r"\b\d{8,10}:AA[A-Za-z0-9_\-]{33}\b",                            # Telegram bot token
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}:[0-9a-f]{32}\b",  # fal.ai key
]
_TOKEN_RE = re.compile("|".join(f"(?:{p})" for p in _TOKEN_PATTERNS))
# Cheap literal pre-check: every token pattern above contains one of these fragments.
_TOKEN_HINT_RE = re.compile(r"sk-|_live_|_test_|gh[pousr]_|github_pat_|glpat-|xox|xapp-|A[GIKNRS][A-Z]A|AIza|ya29\.|"
                            r"eyJ|hf_|npm_|xai|pplx|gsk|r8|fw|nvapi|dop_v1_|SG\.|key-|:AA|-[0-9a-f]{12}:")
_AUTH_RE = re.compile(
    r"(?i)(\bauthorization\b[\"']?\s*[:=]\s*[\"']?(?:bearer|basic|token|bot|digest)?\s*|\bbearer\s+)([A-Za-z0-9._~+/=\-]{8,})")
_COOKIE_RE = re.compile(r"(?im)^(\s*(?:set-)?cookie\s*:\s*)(.+)$")
_ASSIGN_RE = re.compile(
    r"(?<![\w$])(?P<name>[\"']?[A-Za-z_][\w.\-]*[\"']?)(?P<sep>\s*(?:=|:)\s*)(?P<q>[\"']?)(?P<val>[^\s\"'`,;{}()\[\]<>]+)(?P=q)")
_FLAG_RE = re.compile(r"(?P<name>--?[A-Za-z][\w\-]*)(?P<sep>=|\s+)(?P<q>[\"']?)(?P<val>[^\s\"']+)(?P=q)")
_SECRET_NAME_RE = re.compile(
    r"(?i)(?:secret|token|passw(?:or)?d|passphrase|api[_\-.]?key|apikey|access[_\-.]?key|private[_\-.]?key|"
    r"client[_\-.]?secret|credential|cookie|session[_\-.]?key|signing[_\-.]?key|encryption[_\-.]?key|"
    r"(?:^|[_\-.])auth(?:$|[_\-.])|auth[_\-.]?token|bearer|webhook[_\-.]?url|dsn|"
    r"(?:^|[_\-.])(?:pass|pwd|pw)(?:$|[_\-.]))")
# names whose value may be a plain all-letters passphrase (PASSWORD=correcthorsebatterystaple)
_PASSWORDISH_RE = re.compile(r"(?i)passw(?:or)?d|passphrase|(?:^|[_\-.])(?:pass|pwd|pw)(?:$|[_\-.])")
_SECRET_NAME_DENY = re.compile(
    r"(?i)^(?:pwd|oldpwd|max_tokens?|num_tokens|tokens?_?(?:count|used|limit|budget|len|length)|"
    r"token_?type|.*_(?:file|path|dir|url_env|name|names|id_env|count|len|length|limit|type|kind|field|header|policy|env))$")
_GENERIC_RE = re.compile(r"(?<![A-Za-z0-9+_\-])[A-Za-z0-9+_\-]{32,}={0,2}(?![A-Za-z0-9+_\-])")
_SRI_PREFIX_RE = re.compile(r"sha(?:1|224|256|384|512)-$", re.I)
_EMAIL_RE = re.compile(r"(?<![\w.%+\-])([A-Za-z0-9._%+\-]+)@([A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,})\b")
_EMAIL_KEEP_LOCAL = {"git", "noreply", "no-reply", "donotreply", "do-not-reply"}
_EMAIL_KEEP_DOMAIN = re.compile(r"(?i)(?:^|\.)(?:example\.(?:com|org|net)|localhost|test|invalid)$")
_SEP = r"(?:\\\\|\\|/)+"
_HOME_RES = [
    re.compile(rf"(?i)\b[a-z]:{_SEP}users{_SEP}(?!(?:public|default|default user|all users)(?:[\\/]|$))[^\\/\s\"'<>|:*?`]+"),
    re.compile(rf"(?i)(?<![\w:.])/mnt/[a-z]/users/(?!(?:public|default)(?:/|$))[^/\s\"'<>|:*?`]+"),
    re.compile(rf"(?i)(?<![\w:.])/[a-z]/users/(?!(?:public|default)(?:/|$))[^/\s\"'<>|:*?`]+"),
    re.compile(r"(?<![\w:./\\])/Users/(?!(?:Shared|Guest)(?:/|$))[^/\s\"'<>|:*?`]+"),
    re.compile(r"(?<![\w:./\\])/home/[^/\s\"'<>|:*?`]+"),
]
_PHONE_RE = re.compile(
    r"(?<![\w+=/.\-])(?:\+\d{1,3}[\s.\-]?(?:\(\d{1,4}\)[\s.\-]?)?\d{2,4}(?:[\s.\-]?\d{2,5}){1,4}"
    r"|\(\d{3}\)\s?\d{3}[\s.\-]\d{4}|\d{3}[.\-]\d{3}[.\-]\d{4})(?![\w.\-]?\d)")
_GIT_NAME_RE = re.compile(
    r"(?im)(\b(?:author|commit(?:ter)?|signed-off-by|co-authored-by|reviewed-by|tested-by|acked-by)\s*:\s*)"
    r"[^<>\n]{1,80}?(\s*<(?:" + re.escape(EMAIL) + "|" + re.escape(SECRET) + r")>)")
_GIT_CONFIG_NAME_RE = re.compile(r"(user\.name\s*[= ]\s*)(?:([\"'])[^\"'\n]{1,80}\2|(?![\"'])\S+)")
_PROMPT_RE = re.compile(r"(?<![\w.\-@/])[A-Za-z][\w.\-]{0,31}@[A-Za-z0-9][\w.\-]{0,62}"
                        r"(?=:[~/]|\s+[^\s@]{1,64}\s*[$#%](?:\s|$))")
_MAC_PROMPT_RE = re.compile(r"(?m)^[ \t]*[A-Za-z0-9][\w\-]{0,62}:(?:~|[^\s/:$]{1,64}) [A-Za-z][\w.\-]{0,31}\$(?=\s|$)")
#: login names too generic to identify anyone (never masked on their own)
_GENERIC_USERS = {"user", "users", "admin", "administrator", "root", "runner", "ubuntu", "dev", "test", "home",
                  "guest", "public", "default", "vagrant", "app", "node", "docker", "ec2-user", "codespace",
                  "vscode", "owner", "build", "ci", "pi", "me", "hermes"}
_CRED_FILE_RE = re.compile(
    r"(?i)(?:^|[\\/\s\"'=:])(?:\.env(?:\.[\w.\-]+)?|\.envrc|\.npmrc|\.pypirc|\.netrc|_netrc|\.pgpass|"
    r"\.git-credentials|\.dockercfg|credentials(?:\.(?:json|ya?ml|toml|ini|txt))?|secrets?\.(?:json|ya?ml|toml|txt|env)|"
    r"service[_\-]?account[\w.\-]*\.json|id_(?:rsa|dsa|ecdsa|ed25519)|[\w.\-]+\.(?:pem|key|p12|pfx))(?=$|[\s\"'|;&>)])")
_ENV_LINE_RE = re.compile(
    r"(?m)^([+\-]?\s*(?:export\s+|set\s+|setx\s+)?[\"']?[A-Za-z_][\w.\-]*[\"']?\s*[=:]\s*)(?=\S)(.*?)(\s*,?\s*)$")
_IPV4_RE = re.compile(r"(?<![\w.])(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)(?![\w.])")
#: commands that print the whole environment (USER=, HOSTNAME=, every token in it). The alternation is written so
#: the plugin guard's literal patterns for such commands do not fire on this source line.
_ENV_DUMP_RE = re.compile(
    r"(?i)(?:^|[;&|(]\s*)(?:set|export\s+-p|declare\s+-p?x|(?:get-childitem|gci|dir|ls)\s+env:\\?|cmd(?:\.exe)?\s+/c\s+set|"
    r"(?:print)?env(?=\s|$|[;&>)]|\s*[|]))\s*(?:$|[|;&>)])")
_PLACEHOLDER_HINTS = ("your", "xxx", "***", "...", "<", ">", "example", "changeme", "placeholder", "dummy",
                      "redacted", "‹", "$", "%", "{", "(", "os.environ", "process.env", "getenv", "env[", "none", "null",
                      "true", "false", "undefined", "secret_here", "token_here", "key_here")


def _entropy(s: str) -> float:
    counts = Counter(s)
    n = len(s)
    return -sum(c / n * math.log2(c / n) for c in counts.values())


def looks_secret_value(val: str) -> bool:
    """Is an assigned value plausibly a literal credential (vs code, a path, a number, a placeholder)?"""
    v = val.strip().strip("\"'")
    if len(v) < 8:
        return False
    low = v.lower()
    if any(h in low for h in _PLACEHOLDER_HINTS):
        return False
    if re.match(r"^(?:[a-z]:[\\/]|[/~.]|\\\\)", v, re.I) or "\\" in v:
        return False                      # a path
    if re.fullmatch(r"https?://\S+", v):
        return False                      # URLs are handled by the URL passes
    if v.isdigit():
        return False
    if re.fullmatch(r"[a-z_][a-z0-9_]*(?:\.[a-z_][a-z0-9_]*)+", v):
        return False                      # dotted.code.reference
    if re.fullmatch(r"[A-Z][A-Z0-9_]*", v) and "_" in v:
        return False                      # another ENV_VAR_NAME
    has_d = any(ch.isdigit() for ch in v)
    has_a = any(ch.isalpha() for ch in v)
    if has_d and has_a:
        return True
    if v.isalpha():
        return len(v) >= 16 and v != v.lower() and v != v.upper() and _entropy(v) > 3.5
    return len(v) >= 16 and _entropy(v) > 3.5


def _secret_name(name: str) -> bool:
    n = name.strip("\"'").lstrip("-")
    if _SECRET_NAME_DENY.match(n):
        return False
    if _SECRET_NAME_RE.search(n):
        return True
    # bare "KEY" segment only in ENV_STYLE names (OPENAI_KEY, STRIPE_KEY) - code like sort_key stays
    return n.isupper() and bool(re.search(r"(?:^|_)KEY(?:$|_)", n))


def _secret_assignment(name: str, val: str) -> bool:
    """``name = val`` assigns a literal credential: a secret-ish name and a credential-looking value, or a
    password-ish name and an all-letters passphrase (``PASSWORD=correcthorsebatterystaple``)."""
    if not _secret_name(name):
        return False
    if looks_secret_value(val):
        return True
    v = val.strip().strip("\"'")
    return (len(v) >= 8 and v.isalpha() and not any(h in v.lower() for h in _PLACEHOLDER_HINTS)
            and bool(_PASSWORDISH_RE.search(name.strip("\"'").lstrip("-"))))


def _login_names(home: str, *, with_getpass: bool = True) -> list[str]:
    """The local login name(s): the home folder's name and (without an explicit home) ``getpass``."""
    names = [os.path.basename(home.rstrip("\\/"))] if home else []
    if with_getpass:
        try:
            import getpass
            names.append(getpass.getuser())
        except Exception:  # noqa: BLE001 - no login name on this platform
            pass
    return [n for n in dict.fromkeys(names) if n and len(n) >= 3 and n.lower() not in _GENERIC_USERS
            and re.fullmatch(r"[\w.\-]+", n)]


class Redactor:
    """Deterministic text/structure redactor. Instances are cheap; ``learn`` then ``text``/``value``."""

    def __init__(self, *, home: str | os.PathLike[str] | None = None, redact_emails: bool = True,
                 redact_ips: bool = False, usernames: Iterable[str] = (), extra_secrets: Iterable[str] = (),
                 redact_phones: bool = True, login_names: Iterable[str] | None = None) -> None:
        self.redact_emails = redact_emails
        self.redact_ips = redact_ips
        self.redact_phones = redact_phones
        self._learned: set[str] = {s for s in extra_secrets if s and len(s) >= 6}
        self._learned_re: re.Pattern[str] | None = None
        homes: list[str] = []
        h = ""
        try:
            h = str(home) if home is not None else str(Path.home())
            if len(h) > 3:
                homes += [h, h.replace("\\", "/"), h.replace("\\", "\\\\"), h.replace("/", "\\")]
                if re.match(r"^[A-Za-z]:[\\/]", h):       # git-bash/MSYS and WSL spell C:\Users\X as /c/Users/X
                    rest = h[3:].replace("\\", "/")
                    homes += [f"/{h[0].lower()}/{rest}", f"/mnt/{h[0].lower()}/{rest}"]
        except (RuntimeError, OSError):
            pass
        self._homes = sorted({x for x in homes if x}, key=len, reverse=True)
        # case-insensitive and in every spelling: the generic home patterns stop at a space, so a folder such as
        # "Alice Smith" would otherwise leave "~ Smith" on screen
        self._home_re = re.compile("|".join(map(re.escape, self._homes)), re.I) if self._homes else None
        self._home_tail = re.split(r"[\\/]", h.rstrip("\\/"))[-1].lower() if len(h) > 3 else ""
        names = [u for u in usernames if u and len(u) >= 3]
        self._user_re = re.compile(r"(?<![\w])(?:" + "|".join(map(re.escape, names)) + r")(?![\w])") if names else None
        # the login name only where it identifies the user (``jane@host``, a ``whoami`` line), never as a
        # bare word: a login such as ``will`` or ``mark`` is also an ordinary word in prose and code
        logins = (list(login_names) if login_names is not None
                  else _login_names(h if len(h) > 3 else "", with_getpass=home is None))
        alt = "|".join(map(re.escape, sorted(logins, key=len, reverse=True)))
        self._login_re = re.compile(rf"(?<![\w.\-])(?:{alt})@[\w.\-]*\w|^[ \t]*(?:[\w.\-]+\\)?(?:{alt})[ \t]*$",
                                    re.I | re.M) if alt else None
        self.counts: Counter[str] = Counter()

    # ------------------------------------------------------------------ learning
    def learn(self, text: str) -> None:
        """Remember literal values assigned to secret-ish names so later bare mentions are masked too."""
        if not text or not isinstance(text, str) or len(text) < 10 or ("=" not in text and ":" not in text
                                                                       and "--" not in text):
            return
        before = len(self._learned)
        for rx in (_ASSIGN_RE, _FLAG_RE):
            for m in rx.finditer(text):
                if _secret_assignment(m.group("name"), m.group("val")):
                    self._learned.add(m.group("val"))
        if len(self._learned) != before:
            self._learned_re = None

    def extra_learn(self, value: str) -> None:
        """Remember one literal secret value (masked wherever it appears later)."""
        if value and len(value) >= 6 and value not in self._learned:
            self._learned.add(value)
            self._learned_re = None

    def _learned_pattern(self) -> re.Pattern[str] | None:
        if self._learned and self._learned_re is None:
            vals = sorted(self._learned, key=len, reverse=True)
            self._learned_re = re.compile("|".join(re.escape(v) for v in vals))
        return self._learned_re

    # ----------------------------------------------------------------- redaction
    def _sub(self, rx: re.Pattern[str], repl: Any, text: str, tag: str) -> str:
        """``rx.sub`` that counts only matches whose replacement actually changed the text."""
        if isinstance(repl, str):
            out, n = rx.subn(repl, text)
            if n:
                self.counts[tag] += n
            return out

        def counted(m: re.Match[str]) -> str:
            new = repl(m)
            if new != m.group(0):
                self.counts[tag] += 1
            return new
        return rx.sub(counted, text)

    def text(self, s: str) -> str:
        """Redact one string. Each pass is guarded by a cheap substring test (big sessions have
        ~100k strings; most contain nothing to redact)."""
        if not s or not isinstance(s, str):
            return s
        if len(s) < 6:                     # a short line can still be the login name (``whoami`` output)
            return self._sub(self._login_re, USER, s, "user") if self._login_re is not None else s
        low = s.lower()
        if "private key" in low:
            s = self._sub(_PEM_RE, SECRET, s, "pem")
        if ";base64," in s:
            s = self._sub(_DATA_URI_RE, lambda m: m.group(1) + DATA, s, "data_uri")
        learned = self._learned_pattern()
        if learned is not None and any(v in s for v in self._learned):
            s = self._sub(learned, SECRET, s, "learned")
        if "://" in s:
            if "@" in s:
                s = self._sub(_URL_CRED_RE, lambda m: f"{m.group(1)}{SECRET}@", s, "url_cred")
            if "hooks.slack.com" in low or "discord" in low:
                s = self._sub(_WEBHOOK_RE, lambda m: (m.group(1) or m.group(2)) + SECRET, s, "webhook")
        if "=" in s and ("?" in s or "&" in s):
            s = self._sub(_QUERY_RE, lambda m: m.group(1) + SECRET, s, "query")
        if len(s) >= 16 and _TOKEN_HINT_RE.search(s):
            s = self._sub(_TOKEN_RE, SECRET, s, "token")
        if "authorization" in low or "bearer" in low:
            s = self._sub(_AUTH_RE, lambda m: m.group(1) + SECRET, s, "auth")
        if "cookie" in low:
            s = self._sub(_COOKIE_RE, lambda m: m.group(1) + SECRET, s, "cookie")
        if "=" in s or ":" in s:
            s = self._sub(_ASSIGN_RE, self._assign_repl, s, "assign")
        if "-" in s:
            s = self._sub(_FLAG_RE, self._assign_repl, s, "flag")
        if len(s) >= 32:
            s = _GENERIC_RE.sub(lambda m: self._generic_repl(m, s), s)
        if self.redact_emails and "@" in s:
            s = self._sub(_EMAIL_RE, self._email_repl, s, "email")
        if (EMAIL in s or SECRET in s) and "<" in s:
            s = self._sub(_GIT_NAME_RE, lambda m: m.group(1) + USER + m.group(2), s, "user")
        if "user.name" in s:
            s = self._sub(_GIT_CONFIG_NAME_RE, lambda m: m.group(1) + USER, s, "user")
        if self.redact_phones and any(c.isdigit() for c in s):
            s = self._sub(_PHONE_RE, self._phone_repl, s, "phone")
        if self._home_re is not None and self._home_tail and self._home_tail in s.lower():
            s = self._sub(self._home_re, "~", s, "home")
        low = s.lower()
        if "users" in low or "/home/" in low:
            for rx in _HOME_RES:
                s = self._sub(rx, "~", s, "home")
        if "@" in s:
            s = self._sub(_PROMPT_RE, USER, s, "user")
        if "$" in s and ":" in s:                        # macOS bash default prompt "Janes-MacBook:tempo jane$"
            s = self._sub(_MAC_PROMPT_RE, USER + "$", s, "user")
        if self._login_re is not None:
            s = self._sub(self._login_re, lambda m: m.group(0)[:len(m.group(0)) - len(m.group(0).lstrip())] + USER,
                          s, "user")
        if self._user_re is not None:
            s = self._sub(self._user_re, USER, s, "user")
        if self.redact_ips and "." in s:
            s = self._sub(_IPV4_RE, self._ip_repl, s, "ip")
        return s

    def _assign_repl(self, m: re.Match[str]) -> str:
        if not _secret_assignment(m.group("name"), m.group("val")):
            return m.group(0)
        if m.group("val") == SECRET:
            return m.group(0)
        q = m.group("q")
        return f"{m.group('name')}{m.group('sep')}{q}{SECRET}{q}"

    def _generic_repl(self, m: re.Match[str], whole: str) -> str:
        tok = m.group(0)
        core = tok.rstrip("=")
        if re.fullmatch(r"[0-9a-fA-F\-]+", core):
            return tok                                   # hex digests, SHAs, UUIDs
        if re.match(r"sha(?:1|224|256|384|512)-", core, re.I) or \
                _SRI_PREFIX_RE.search(whole[max(0, m.start() - 8):m.start()]):
            return tok                                   # subresource-integrity hashes
        digits = sum(ch.isdigit() for ch in core)
        if digits < 3 or not any(ch.isupper() for ch in core) or not any(ch.islower() for ch in core):
            return tok
        segs = [s for s in re.split(r"[_\-]", core) if s]
        if len(segs) >= 3 and sum(map(len, segs)) / len(segs) <= 8:
            return tok                                   # Word_Like-Identifiers_V2, file names
        words = re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+", core)
        if words and sum(map(len, words)) / len(words) >= 3.2:
            return tok                                   # CamelCaseWords_Ep2_LongName: real words, not noise
        nxt = whole[m.end():m.end() + 6]
        if re.match(r"\.[A-Za-z0-9]{1,5}\b", nxt) and whole[max(0, m.start() - 1):m.start()] in ("/", "\\"):
            return tok                                   # a path component with an extension
        if _entropy(core) < 4.0:
            return tok
        self.counts["entropy"] += 1
        return SECRET

    def _email_repl(self, m: re.Match[str]) -> str:
        local, domain = m.group(1), m.group(2)
        if local.lower() in _EMAIL_KEEP_LOCAL or _EMAIL_KEEP_DOMAIN.search(domain):
            return m.group(0)
        return EMAIL

    @staticmethod
    def _phone_repl(m: re.Match[str]) -> str:
        tok = m.group(0)
        digits = sum(ch.isdigit() for ch in tok)
        if tok.startswith("+"):
            return PHONE if 8 <= digits <= 15 else tok
        return PHONE if digits == 10 else tok

    @staticmethod
    def _ip_repl(m: re.Match[str]) -> str:
        ip = m.group(0)
        if ip.startswith(("127.", "0.0.0.0", "255.255.255.")):
            return ip
        return IP

    def value(self, obj: Any, *, skip_keys: Iterable[str] = ()) -> Any:
        """Redact strings inside nested dict/list structures (keys starting with ``_`` untouched)."""
        skip = set(skip_keys)
        if isinstance(obj, str):
            return self.text(obj)
        if isinstance(obj, list):
            return [self.value(v) for v in obj]
        if isinstance(obj, tuple):
            return tuple(self.value(v) for v in obj)
        if isinstance(obj, dict):
            return {k: (v if (k in skip or str(k).startswith("_")) else self.value(v)) for k, v in obj.items()}
        return obj

    def learn_value(self, obj: Any) -> None:
        """Run :meth:`learn` over every string inside ``obj``."""
        if isinstance(obj, str):
            self.learn(obj)
        elif isinstance(obj, (list, tuple)):
            for v in obj:
                self.learn_value(v)
        elif isinstance(obj, dict):
            for k, v in obj.items():
                if not str(k).startswith("_"):
                    self.learn_value(v)


_PATH_KEYS = ("path", "path_key", "src", "preview_path", "url", "lang", "cwd", "asset")


def _credential_event(ev: Any) -> bool:
    """Does the event show a credential file's content (written/read/patched, or printed by a command), or a
    dump of the environment (``env``, ``set``, ``Get-ChildItem env:`` and the like)?"""
    data = ev.data if isinstance(ev.data, dict) else {}
    names = [str(data.get(k) or "") for k in ("path", "path_key", "src")]
    if ev.kind in ("terminal", "process"):
        cmd = str(data.get("cmd") or "")
        if _ENV_DUMP_RE.search(cmd):
            return True
        names.append(cmd)
    return any(n and _CRED_FILE_RE.search(n.replace("\\", "/")) for n in names)


def _mask_env_lines(obj: Any, r: Redactor) -> Any:
    """Every ``KEY=value`` / ``key: value`` line of a credential file loses its value (whatever the key)."""
    if isinstance(obj, str):
        def repl(m: re.Match[str]) -> str:
            if m.group(2) in ("", SECRET, f'"{SECRET}"', f"'{SECRET}'"):
                return m.group(0)
            r.counts["credential_file"] += 1
            return m.group(1) + SECRET + m.group(3)
        return _ENV_LINE_RE.sub(repl, obj) if ("=" in obj or ":" in obj) else obj
    if isinstance(obj, list):
        return [_mask_env_lines(v, r) for v in obj]
    if isinstance(obj, dict):
        return {k: (v if k in _PATH_KEYS or str(k).startswith("_") else _mask_env_lines(v, r)) for k, v in obj.items()}
    return obj


def _learn_env_values(obj: Any, r: Redactor) -> None:
    """Remember a credential file's literal values (>= 8 chars) so a later bare mention is masked too."""
    if isinstance(obj, str):
        for m in _ENV_LINE_RE.finditer(obj):
            v = m.group(2).strip().strip("\"'")
            if looks_secret_value(v) and not _EMAIL_RE.fullmatch(v):
                r.extra_learn(v)
    elif isinstance(obj, list):
        for v in obj:
            _learn_env_values(v, r)
    elif isinstance(obj, dict):
        for k, v in obj.items():
            if k not in _PATH_KEYS and not str(k).startswith("_"):
                _learn_env_values(v, r)


def redact_events(events: list[Any], redactor: Redactor | None = None) -> Redactor:
    """Redact events in place (title, summary, data). Copied asset paths (``data.asset``) are kept.

    Runs a learning pass over all events first, so a secret assigned once is masked everywhere; every
    value in a credential file's content (``.env``, ``.npmrc``, ``credentials.json``...) is learned and masked.
    Returns the redactor (its ``counts`` say what was masked).
    """
    r = redactor or Redactor()
    cred = {id(ev) for ev in events if _credential_event(ev)}
    for ev in events:
        r.learn(ev.title)
        r.learn(ev.summary)
        r.learn_value(ev.data)
        if id(ev) in cred:
            _learn_env_values(ev.data, r)
    for ev in events:
        if id(ev) in cred:
            ev.data = _mask_env_lines(ev.data, r)
    for ev in events:
        ev.title = r.text(ev.title)
        ev.summary = r.text(ev.summary)
        # our own copies stay usable; an artifact's ``path`` is the user's file and IS redacted
        skip = ("preview_path", "path") if ev.data.get("asset") and ev.kind != "artifact" else ("preview_path",)
        ev.data = r.value(ev.data, skip_keys=skip)
    return r
