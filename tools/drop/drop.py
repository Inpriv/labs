#!/usr/bin/env python3
"""drop — what would hurt you if this folder, laptop or backup leaked?

A local, offline, read-only scanner for files that could leak sensitive data:
sensitive filenames, secrets inside text files, loose POSIX permissions, leaky
shell history, unencrypted PII and metadata (GPS in photos, document authors).

Privacy by design: pure standard library, no network code at all, never
writes, moves or deletes anything, and never prints a secret in full.

    python drop.py scan [PATH ...] [--home] [--json] [--min-severity LEVEL]
    python drop.py rules

Exit codes: 0 clean, 1 findings at/above --min-severity, 2 error.
"""

from __future__ import annotations

import argparse
import base64
import codecs
import fnmatch
import glob
import json
import math
import os
import re
import stat
import struct
import sys
import time
import zipfile
from collections import Counter, namedtuple
from typing import List, Optional, Tuple

VERSION = "0.1.0"

SEVERITIES = ("low", "medium", "high", "critical")
RANK = {s: i for i, s in enumerate(SEVERITIES)}

# exposure score = min(100, sum of these weights over the reported findings).
# One critical finding is a quarter of the scale on its own; four max it out.
WEIGHT = {"low": 1, "medium": 4, "high": 10, "critical": 25}


# -- Terminal colours (Inpriv M3 palette, same tokens as trns) ---------------

def _enable_windows_vt() -> bool:
    """Ask the Windows console to interpret ANSI escapes (Windows 10+)."""
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle, mode = kernel32.GetStdHandle(-11), ctypes.c_uint32()  # STD_OUTPUT_HANDLE
        return bool(kernel32.GetConsoleMode(handle, ctypes.byref(mode))
                    and kernel32.SetConsoleMode(handle, mode.value | 0x0004))  # VT processing
    except Exception:
        return False


def _color_enabled() -> bool:
    if os.environ.get("NO_COLOR") or os.environ.get("TERM") == "dumb":
        return False
    return getattr(sys.stdout, "isatty", lambda: False)() and (os.name != "nt" or _enable_windows_vt())


USE_COLOR = _color_enabled()


def _paint(code: str):
    return lambda text: f"\033[{code}m{text}\033[0m" if USE_COLOR else str(text)


bold, dim, muted = _paint("1"), _paint("38;2;148;143;153"), _paint("38;2;203;196;212")
primary, ok, warn = _paint("38;2;203;190;255"), _paint("38;2;171;211;122"), _paint("38;2;255;184;104")
err = _paint("38;2;255;134;112")
SEV_COLOR = {"critical": _paint("1;38;2;255;134;112"), "high": err, "medium": warn, "low": muted}


# -- Rules ------------------------------------------------------------------

Rule = namedtuple("Rule", "id severity title fix")

RULES = [
    # 1. sensitive filenames
    Rule("file.private-key", "critical", "SSH / PuTTY private key file",
         "Add a passphrase (ssh-keygen -p -f FILE); keep keys in ~/.ssh, never in projects or clouds."),
    Rule("file.pkcs12", "high", "PKCS#12 bundle (.p12 / .pfx) holding a private key",
         "Import it into the OS keychain or a password manager, then delete loose copies."),
    Rule("file.crypto-wallet", "high", "cryptocurrency wallet / keystore file",
         "Keep wallet files encrypted and offline; move funds to a hardware wallet."),
    Rule("file.keystore", "high", "Java / Android keystore",
         "Keep signing keystores out of source trees and backups; use a secrets manager."),
    Rule("file.password-db", "medium", "password manager database (.kdbx)",
         "Encrypted, but copies can be brute-forced offline: use a long master password and a key file."),
    Rule("file.env", "high", "dotenv file (usually API keys and passwords)",
         "Never commit or sync .env files (add them to .gitignore); load secrets from a vault or keychain."),
    Rule("file.credentials", "high", "credential / token store (netrc, git-credentials, cloud CLI…)",
         "Prefer short-lived tokens and a credential helper (keychain, libsecret, wincred)."),
    Rule("file.vpn-config", "high", "OpenVPN profile (often embeds its private key)",
         "Keep .ovpn profiles out of shared folders; re-issue the profile if a copy leaked."),
    Rule("file.tfstate", "high", "Terraform state (holds resource secrets in plaintext)",
         "Use an encrypted remote backend; never commit, sync or email tfstate files."),
    Rule("file.browser-logins", "high", "browser saved-password database",
         "Set a browser primary password or use a password manager; don't back profiles up unencrypted."),
    Rule("file.db-dump", "medium", "database dump",
         "Delete dumps after use, or keep them encrypted (gpg -c, age)."),
    Rule("file.backup", "medium", "backup file or archive",
         "Encrypt backups (restic, borg, age, 7z -p -mhe=on) and delete stale .bak copies."),
    # 2. secrets inside text files
    Rule("secret.private-key", "critical", "private key block",
         "Remove the key from this file and rotate it; keep keys encrypted in ~/.ssh or an agent."),
    Rule("secret.aws-key", "critical", "AWS access key id",
         "Deactivate and rotate it in IAM, then switch to SSO / short-lived credentials."),
    Rule("secret.github-token", "critical", "GitHub token",
         "Revoke it at github.com/settings/tokens; use a fine-grained, expiring token instead."),
    Rule("secret.gitlab-token", "critical", "GitLab personal access token",
         "Revoke it in GitLab > Preferences > Access tokens."),
    Rule("secret.google-api-key", "high", "Google API key",
         "Regenerate or restrict it in Google Cloud Console > Credentials."),
    Rule("secret.slack-token", "high", "Slack token or webhook",
         "Revoke it in the Slack app settings and reinstall the app."),
    Rule("secret.stripe-key", "critical", "Stripe live secret key",
         "Roll the key in the Stripe dashboard > Developers > API keys."),
    Rule("secret.ai-api-key", "critical", "AI provider API key (OpenAI / Anthropic)",
         "Revoke it in the provider console; load keys from the environment instead."),
    Rule("secret.jwt", "medium", "JSON Web Token",
         "Treat bearer tokens like passwords: revoke the session and keep tokens out of files."),
    Rule("secret.url-credentials", "high", "credentials embedded in a URL",
         "Remove user:password@ from the URL; use a credential helper or env vars."),
    Rule("secret.assignment", "high", "hard-coded password / secret / token",
         "Rotate the value and load it from an environment variable or secrets manager."),
    Rule("secret.high-entropy", "medium", "high-entropy string (possible key or token)",
         "If it is a credential, rotate it and move it out; if not, add the file to .dropignore."),
    Rule("secret.seed-phrase", "high", "possible wallet seed phrase (heuristic)",
         "If this is a real seed, move the funds to a new wallet now; never keep seeds in files."),
    # 3. permissions (POSIX only)
    Rule("perm.private-key", "high", "private key readable by group/others",
         "chmod 600 FILE (ssh refuses to use keys with looser permissions)."),
    Rule("perm.credentials", "medium", "credential file readable by group/others", "chmod 600 FILE"),
    Rule("perm.world-writable", "medium", "world-writable config file",
         "chmod o-w FILE: right now anyone on this machine can modify it."),
    # 4. shell / REPL history
    Rule("history.secret", "high", "secret in shell / REPL history",
         "Delete the line and rotate the secret; start such commands with a space (HISTCONTROL=ignorespace)."),
    # 5. unencrypted PII (heuristics, checksum-validated where possible)
    Rule("pii.credit-card", "medium", "card number (Luhn-valid, heuristic)",
         "Delete or encrypt the file; card numbers should never sit in plaintext."),
    Rule("pii.iban", "medium", "IBAN (mod-97 valid, heuristic)",
         "Keep documents with bank details in an encrypted vault."),
    Rule("pii.pesel", "low", "Polish PESEL number (checksum-valid, heuristic)",
         "Encrypt or delete documents containing national ID numbers."),
    Rule("pii.ssn", "low", "US SSN-like number (heuristic)",
         "Encrypt or delete documents containing national ID numbers."),
    Rule("pii.credential-dump", "medium", "email:password pairs (credential dump, heuristic)",
         "Delete it; if the accounts are yours, change those passwords and enable 2FA."),
    # 6. metadata leaks
    Rule("meta.gps-exif", "medium", "photo with GPS location in EXIF",
         "Strip location before sharing (exiftool -gps:all= FILE, or your phone's 'remove location')."),
    Rule("meta.doc-author", "low", "document with author metadata",
         "Remove personal info before sharing (Office: Inspect Document; exiftool -all= FILE)."),
]
RULE = {r.id: r for r in RULES}
CATEGORY_TITLES = {"file": "sensitive filenames", "secret": "secrets in text files",
                   "perm": "permissions (POSIX only)", "history": "shell / REPL history",
                   "pii": "unencrypted PII (heuristics)", "meta": "metadata leaks"}


# -- Findings and small, testable helpers -----------------------------------

def redact(value: str) -> str:
    """Mask a secret for display: AKIA****XY. Never reveals more than a third of it."""
    v = value.strip()
    if len(v) >= 18:
        return v[:4] + "****" + v[-2:]
    return v[:2] + "****" + v[-1:] if len(v) >= 9 else "****"


class Finding:
    """One reported issue. A raw `secret` is redacted on the way in and never stored."""

    def __init__(self, rule, path, line=None, secret=None, shown=None, detail="", severity=None):
        self.rule, self.path, self.line, self.detail = rule, path, line, detail
        self.shown = redact(secret) if secret is not None else shown
        self.severity = severity or RULE[rule].severity

    @property
    def message(self) -> str:
        title = RULE[self.rule].title
        return f"{title} ({self.detail})" if self.detail else title

    def to_json(self) -> dict:
        return {"rule": self.rule, "severity": self.severity, "path": self.path, "line": self.line,
                "redacted_match": self.shown, "message": self.message, "fix": RULE[self.rule].fix}


def shannon_entropy(s: str) -> float:
    """Bits of entropy per character (0 for 'aaaa', 2.0 for 'abcd')."""
    n = len(s)
    return -sum(c / n * math.log2(c / n) for c in Counter(s).values()) if s else 0.0


def luhn_ok(digits: str) -> bool:
    if not digits.isdigit() or len(digits) < 2:
        return False
    doubled = (int(c) * (2 if i % 2 else 1) for i, c in enumerate(reversed(digits)))
    return sum(d - 9 if d > 9 else d for d in doubled) % 10 == 0


def iban_ok(iban: str) -> bool:
    s = iban.replace(" ", "").upper()
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{11,30}", s):
        return False
    # move country + check digits to the end, letters become 10..35, then mod 97
    return int("".join(str(int(c, 36)) for c in s[4:] + s[:4])) % 97 == 1


def pesel_ok(pesel: str) -> bool:
    if not re.fullmatch(r"\d{11}", pesel):
        return False
    d = [int(c) for c in pesel]
    check = (10 - sum(w * x for w, x in zip((1, 3, 7, 9, 1, 3, 7, 9, 1, 3), d)) % 10) % 10
    month, day = int(pesel[2:4]) % 20, int(pesel[4:6])  # +20/40/60/80 encodes the century
    return check == d[10] and 1 <= month <= 12 and 1 <= day <= 31


PLACEHOLDER_WORDS = frozenset("password passwd pass secret token changeme none null nil true false "
                              "undefined required optional string empty blank default".split())
PLACEHOLDER_BITS = ("example", "placeholder", "your", "xxxx", "****", "dummy", "redacted",
                    "changeme", "change_me", "sample", "<", ">", "${", "{{", "%(", "(", ")", "[", "]")
IDENTIFIER_RE = re.compile(r"[a-z_][a-z0-9_]*(?:[._][a-z_][a-z0-9_]*)+|[a-z]+(?:-[a-z]+)+")


def looks_placeholder(value: str, key: str = "") -> bool:
    """True for values that are obviously not real secrets (templates, refs, URLs, 'xxxx')."""
    v = value.strip().lower()
    return (not v or v in PLACEHOLDER_WORDS or v == key.lower()
            or v[0] in "$%@!&*[{</~.:"                    # templating, variables, paths, scopes
            or any(b in v for b in PLACEHOLDER_BITS)
            or "://" in v                                  # a URL (user:pass@ has its own rule)
            or len(set(v)) <= 2                            # 'aaaaaa', '000000'
            or IDENTIFIER_RE.fullmatch(v) is not None      # access_token, db.password, no-such-flag
            # a token/key/secret that is one plain lowercase word is a name, not a credential
            or (key != "" and "pass" not in key.lower() and value.isalpha() and value.islower()))


# -- 2 / 4 / 5: content rules -----------------------------------------------

SECRET_PATTERNS = [  # (rule, regex whose group 1 is the secret)
    ("secret.aws-key", re.compile(r"\b((?:AKIA|ASIA)[0-9A-Z]{16})\b")),
    ("secret.github-token", re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{36,255}|github_pat_[A-Za-z0-9_]{22,255})\b")),
    ("secret.gitlab-token", re.compile(r"\b(glpat-[A-Za-z0-9_-]{20,})")),
    ("secret.google-api-key", re.compile(r"\b(AIza[0-9A-Za-z_-]{35})")),
    ("secret.slack-token", re.compile(r"\b(xox[abposr]-[A-Za-z0-9-]{10,}"
                                      r"|https://hooks\.slack\.com/services/[A-Za-z0-9/]{20,})")),
    ("secret.stripe-key", re.compile(r"\b((?:sk|rk)_live_[0-9A-Za-z]{20,})")),
    ("secret.ai-api-key", re.compile(r"\b(sk-(?:ant|proj)-[A-Za-z0-9_-]{32,})")),
    ("secret.jwt", re.compile(r"\b(eyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,})")),
    ("secret.url-credentials",
     re.compile(r"\b[A-Za-z][A-Za-z0-9+.-]{1,20}://[^\s:/@]+:([^\s:/@]+)@[A-Za-z0-9.-]+")),
]
PRIVATE_KEY_RE = re.compile(r"-----BEGIN ((?:[A-Z0-9]+ )*PRIVATE KEY(?: BLOCK)?)-----")
# cheap per-line prefilters: most lines cannot match, so skip the full pattern sets
SECRET_HINT = re.compile(r"AKIA|ASIA|gh[pousr]_|github_pat_|glpat-|AIza|xox|_live_|sk-|eyJ|://")
PII_HINT = re.compile(r"\d(?:[ -]?\d){8}")  # every PII pattern needs 9+ nearby digits

# key = "value" assignments. The key must *end* in a sensitive word (optionally
# + _key/_base/_value/_prod/_live), so 'tokenizer = …' or 'PASSWORD_MIN_LENGTH = 8'
# do not match. Groups: 1 key, 2 quote, 3 quoted value, 4 bare value.
ASSIGN_RE = re.compile(
    r"(?i)(?<![a-z0-9_.-])([a-z0-9_.-]*(?:password|passwd|passphrase|secret|token"
    r"|api[_-]?key|access[_-]?key)(?:[_.-]?(?:key|base|value|prod|live))?)"
    r"[\"']?\s*(?:=>|:=|=|:)\s*"
    r"(?:([\"'])([^\"'\s]{6,})\2|([^\s\"'`,;#]{6,}))")
ASSIGN_WORDS = ("pass", "secret", "token", "key")  # substring prefilter for ASSIGN_RE

HISTORY_PATTERNS = [  # command-line secrets, only checked in shell history files
    re.compile(r"\b(?:mysql|mysqldump|mysqladmin|mariadb)\b.*?\s-p(\S{3,})"),  # mysql -pSECRET
    re.compile(r"\bsshpass\s+-p\s*(\S+)"),
    re.compile(r"\s(?:-u|--user)\s+[^\s:]+:(\S+)"),                          # curl -u user:pass
    re.compile(r"--(?:password|passwd|token|api-key|secret)\s+(\S+)"),
]

TOKEN_RE = re.compile(r"[A-Za-z0-9+/_-]{20,}={0,2}")
ENTROPY_THRESHOLD = 4.5  # bits/char; random base64 of ~30+ chars scores 4.6-5.2
ENTROPY_SKIP = re.compile(r"(?i)integrity|checksum|sha\d|hash|digest|;base64,"  # hashes, data URIs,
                          r"|ssh-(?:rsa|ed25519|dss)|ecdsa-sha2")                # public keys
MAX_HEURISTIC_LINE = 2000  # longer lines (minified code, blobs) only get the specific patterns

WORD_RUN_RE = re.compile(r"(?<![\w-])[a-z]+(?: [a-z]+){11,}(?![\w-])")
SEED_STOPWORDS = frozenset("the and for with from are was were you your has had been would should "
                           "could which these those".split())  # common words that are not BIP-39 words
SEED_CONTEXT = re.compile(r"(?i)seed|mnemonic|recovery|phrase|wallet|bip-?39|backup")

TEST_CARDS = {"4111111111111111", "4242424242424242", "5555555555554444", "378282246310005"}
CARD_PREFIX = re.compile(r"4|5[1-5]|2[2-7]|3[47]|6(?:011|5)|35")
COMBO_RE = re.compile(r"^\s*[\w.+-]+@[\w-]+(?:\.[\w-]+)+\s*[:;|]\s*(\S{4,})\s*$")


def card_ok(raw: str) -> bool:
    digits = re.sub(r"\D", "", raw)
    return (13 <= len(digits) <= 19 and digits not in TEST_CARDS and len(set(digits)) >= 5
            and CARD_PREFIX.match(digits) is not None and luhn_ok(digits))


PII_CHECKS = [  # (rule, regex, validator)
    # 4-digit groups standing alone (not inside a longer run of numbers, e.g. code tables)
    ("pii.credit-card", re.compile(r"(?<![\w.-])(?<!\d[ -])(?:\d{4}[ -]?){3}\d{1,7}(?!\w|[ .-]\d)"), card_ok),
    ("pii.iban", re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]){11,30}\b"), iban_ok),
    ("pii.pesel", re.compile(r"(?<!\d)\d{11}(?!\d)"), pesel_ok),
    ("pii.ssn", re.compile(r"(?<![\d-])(?!000|666|9\d\d)\d{3}-(?!00)\d{2}-(?!0000)\d{4}(?![\d-])"),
     lambda s: True),
]


def key_is_encrypted(label: str, body: str) -> bool:
    """Best effort: does this private key block need a passphrase to be used?"""
    if "ENCRYPTED" in label or "Proc-Type: 4,ENCRYPTED" in body[:200]:
        return True
    if label.startswith("OPENSSH"):  # openssh-key-v1: magic, then a length-prefixed cipher name
        try:
            raw = base64.b64decode(re.sub(r"\s", "", body)[:96])
        except ValueError:
            return False
        if raw.startswith(b"openssh-key-v1\x00") and len(raw) >= 19:
            return raw[19:19 + struct.unpack(">I", raw[15:19])[0]] != b"none"
    return False


def looks_random(token: str) -> bool:
    return (all(re.search(cls, token) for cls in ("[a-z]", "[A-Z]", r"\d"))
            and token.count("/") < 3 and shannon_entropy(token) >= ENTROPY_THRESHOLD)


def looks_like_seed(words: List[str], line: str) -> bool:
    """BIP-39-ish mnemonic: 12-24 distinct, randomly ordered, short English-looking words
    with little else on the line. Keyword lists in syntax files fail the vowel/order tests."""
    ascending = sum(a < b for a, b in zip(words, words[1:]))
    return (len(words) in (12, 15, 18, 21, 24) and all(3 <= len(w) <= 8 for w in words)
            and len(set(words)) >= len(words) - 1 and not SEED_STOPWORDS.intersection(words)
            and all(re.search("[aeiouy]", w) for w in words)
            and 1 < ascending < len(words) - 2                    # a sorted list is not random
            and len(re.findall(r"[A-Za-z]+", line)) <= len(words) + 2)


def scan_text(path: str, text: str, history: bool = False, code: bool = False) -> List[Finding]:
    """Run every content rule over one decoded text file."""
    found: List[Finding] = []
    seen = set()  # (rule, value-or-line) already reported in this file

    def add(rule, lineno, secret=None, shown=None, detail="", severity=None):
        severity = severity or RULE[rule].severity
        if history and rule.startswith("secret."):  # same secret, different fix
            rule, detail = "history.secret", RULE[rule].title
            severity = max(severity, "high", key=RANK.get)
        key = (rule, secret if secret is not None else lineno)
        if key not in seen:
            seen.add(key)
            found.append(Finding(rule, path, lineno, secret, shown, detail, severity))

    def free(span, taken):  # not already claimed by a more specific rule on this line
        return not any(span[0] < end and start < span[1] for start, end in taken)

    for m in PRIVATE_KEY_RE.finditer(text):  # multi-line, so run on the whole text
        end = text.find("-----END", m.end())
        body = text[m.end():end if end != -1 else m.end() + 4096]
        if not re.search(r"[A-Za-z0-9+/=]{40,}", body):
            continue  # just the header (docs, MIME magic): no key material follows
        locked = key_is_encrypted(m.group(1), body)
        add("secret.private-key", text.count("\n", 0, m.start()) + 1, shown=m.group(1),
            detail="passphrase-protected" if locked else "unencrypted", severity="high" if locked else None)

    lines = text.split("\n")  # not splitlines(): keep line numbers identical to editors
    pii = {}      # rule -> [count, first line, first value]
    combos = []   # lines that look like email:password
    for lineno, line in enumerate(lines, 1):
        taken = []
        for rule, rx in SECRET_PATTERNS if SECRET_HINT.search(line) else ():
            for m in rx.finditer(line):
                value = m.group(1)
                if "EXAMPLE" in value.upper() or (rule == "secret.url-credentials" and looks_placeholder(value)):
                    continue  # AWS docs' AKIA...EXAMPLE, user:${PASS}@host
                add(rule, lineno, secret=value)
                taken.append(m.span(1))
        if len(line) > MAX_HEURISTIC_LINE:
            continue

        lowered = line.lower()
        for m in ASSIGN_RE.finditer(line) if any(w in lowered for w in ASSIGN_WORDS) else ():
            group = 3 if m.group(3) is not None else 4
            # in source code only quoted literals count: 'password = user.password' is not a leak
            if (group == 3 or not code) and not looks_placeholder(m.group(group), m.group(1)) \
                    and free(m.span(group), taken):
                add("secret.assignment", lineno, secret=m.group(group), detail=m.group(1))
                taken.append(m.span(group))

        for rx in HISTORY_PATTERNS if history else ():
            for m in rx.finditer(line):
                if not looks_placeholder(m.group(1)) and free(m.span(1), taken):
                    add("history.secret", lineno, secret=m.group(1), detail="password on the command line")
                    taken.append(m.span(1))

        # high entropy: only right after = : or a quote, never in known-noisy lines
        for m in TOKEN_RE.finditer(line) if len(line) <= 400 else ():
            before = line[:m.start()].rstrip()[-1:]
            if before and before in "=:'\"`" and free(m.span(), taken) and looks_random(m.group()) \
                    and not ENTROPY_SKIP.search(line):
                add("secret.high-entropy", lineno, secret=m.group(),
                    detail=f"{shannon_entropy(m.group()):.1f} bits/char")

        for m in WORD_RUN_RE.finditer(line):
            words = m.group().split()
            if looks_like_seed(words, line):
                hot = SEED_CONTEXT.search(" ".join(lines[max(0, lineno - 2):lineno]))
                add("secret.seed-phrase", lineno, shown=f"{len(words)} words (hidden)",
                    severity="critical" if hot else None)

        for rule, rx, valid in PII_CHECKS if PII_HINT.search(line) else ():
            for m in rx.finditer(line):
                if valid(m.group()):
                    pii.setdefault(rule, [0, lineno, m.group()])[0] += 1
        if "@" in line and COMBO_RE.match(line) and not line.rstrip().endswith(".git"):
            combos.append(lineno)

    # PII is reported once per file (first hit + count) to keep reports readable
    for rule, (count, lineno, value) in pii.items():
        add(rule, lineno, secret=value, detail=f"{count} in this file" if count > 1 else "")
    if len(combos) >= 3:
        add("pii.credential-dump", combos[0], shown=f"{len(combos)} pairs")
    return found


# -- 1: sensitive filenames -------------------------------------------------

ARCHIVES = ("zip", "tar", "tar.gz", "tgz", "tar.bz2", "tar.xz", "7z", "rar")
ENV_TEMPLATES = (".example", ".sample", ".template", ".dist", ".defaults")

# (rule, patterns, markers). Patterns match the lowercase file name, or its last
# two path parts when they contain '/'. With markers, a readable text file only
# counts if one of them appears in it (a plain .npmrc with 'save-exact=true' or
# a migration .sql file is not a leak; pg_dump / mysqldump / sqlite output is).
NAME_RULES = [
    ("file.private-key", ("id_rsa", "id_dsa", "id_ecdsa", "id_ed25519", "id_ecdsa_sk", "id_ed25519_sk",
                          "*.ppk"), None),
    ("file.pkcs12", ("*.p12", "*.pfx"), None),
    ("file.crypto-wallet", ("wallet.dat", "utc--*", "default_wallet"), None),
    ("file.keystore", ("*.keystore", "*.jks", "*.bks", "keystore"), None),
    ("file.password-db", ("*.kdbx", "*.kdb"), None),
    ("file.env", (".env", ".env.*", "*.env", ".envrc"), None),
    ("file.credentials", (".netrc", "_netrc", ".git-credentials", ".pgpass", "kubeconfig", ".aws/credentials",
                          ".kube/config", ".dockercfg", "application_default_credentials.json"), None),
    ("file.credentials", (".npmrc", ".pypirc", ".my.cnf", ".docker/config.json"), ("_auth", "password", '"auth"')),
    ("file.vpn-config", ("*.ovpn",), None),
    ("file.tfstate", ("*.tfstate", "*.tfstate.backup"), None),
    ("file.browser-logins", ("login data", "login data for account", "logins.json", "key4.db", "key3.db",
                             "signons.sqlite"), None),
    ("file.db-dump", ("*.sql", "*.sql.gz", "*.dump"), ("database dump", "mysql dump", "mariadb dump",
                                                      "sql dump", "dump completed", "from stdin;",
                                                      "begin transaction;")),
    ("file.backup", ("*.bak", "*.backup") + tuple(
        f"*{word}*.{ext}" for word in ("backup", "bkp", "dump") for ext in ARCHIVES), None),
]


def check_names(path: str) -> List[Tuple[str, Optional[tuple]]]:
    """(rule, markers) for every filename rule matching this path."""
    parts = path.replace(os.sep, "/").lower().split("/")
    name, tail = parts[-1], "/".join(parts[-2:])
    return [(rule, markers) for rule, patterns, markers in NAME_RULES
            if not (rule == "file.env" and name.endswith(ENV_TEMPLATES))  # templates are meant to be shared
            and any(fnmatch.fnmatchcase(tail if "/" in p else name, p) for p in patterns)]


# -- 6: metadata, parsed by hand (no Pillow / PyPDF) ------------------------

def jpeg_gps(path: str) -> Optional[Tuple[float, float]]:
    """(lat, lon) from a JPEG's EXIF GPS IFD, or None."""
    try:
        with open(path, "rb") as f:
            data = f.read(256 * 1024)  # EXIF lives in APP1, right after the SOI marker
        i = 2 if data[:2] == b"\xff\xd8" else len(data)
        while i + 4 <= len(data) and data[i] == 0xFF and data[i + 1] not in (0xD9, 0xDA):
            seglen = struct.unpack(">H", data[i + 2:i + 4])[0]
            if data[i + 1] == 0xE1 and data[i + 4:i + 10] == b"Exif\x00\x00":
                return _exif_gps(data[i + 10:i + 2 + seglen])
            i += 2 + seglen
    except (OSError, struct.error, IndexError, ValueError):
        pass
    return None


def _exif_gps(tiff: bytes) -> Optional[Tuple[float, float]]:
    endian = {b"II": "<", b"MM": ">"}.get(tiff[:2])
    if endian is None:
        return None

    def num(fmt, off):
        return struct.unpack(endian + fmt, tiff[off:off + struct.calcsize(fmt)])

    def entries(ifd):  # (tag, type, count, offset of the 4-byte value field)
        for k in range(num("H", ifd)[0]):
            yield num("HHI", ifd + 2 + 12 * k) + (ifd + 10 + 12 * k,)

    gps_ifd = next((num("I", v)[0] for tag, _, _, v in entries(num("I", 4)[0]) if tag == 0x8825), None)
    refs, coords = {}, {}
    for tag, typ, count, v in entries(gps_ifd) if gps_ifd else ():
        if tag in (1, 3) and typ == 2:                     # 'N'/'S', 'E'/'W' (inline ASCII)
            refs[tag] = tiff[v:v + 1]
        elif tag in (2, 4) and typ == 5 and count == 3:    # degrees, minutes, seconds
            n = num("6I", num("I", v)[0])
            d, m, s = (a / b if b else 0.0 for a, b in zip(n[0::2], n[1::2]))
            coords[tag] = d + m / 60 + s / 3600
    if 2 not in coords or 4 not in coords or coords[2] == coords[4] == 0:
        return None
    return (-coords[2] if refs.get(1) == b"S" else coords[2],
            -coords[4] if refs.get(3) == b"W" else coords[4])


def pdf_author(path: str) -> Optional[str]:
    """/Author from the PDF Info dictionary (searched in the head and tail of the file)."""
    try:
        with open(path, "rb") as f:
            head = f.read(256 * 1024)
            f.seek(max(f.tell(), os.fstat(f.fileno()).st_size - 256 * 1024))
            blob = head + f.read(256 * 1024)
    except OSError:
        return None
    if not head.startswith(b"%PDF"):
        return None
    m = re.search(rb"/Author\s*\(((?:[^()\\]|\\.){1,200})\)", blob)
    raw = m.group(1) if m else b""
    text = raw[2:].decode("utf-16-be", "replace") if raw.startswith(b"\xfe\xff") else raw.decode("latin-1")
    return text.strip() or None


def office_author(path: str) -> Optional[str]:
    """dc:creator / lastModifiedBy from OOXML docProps/core.xml or ODF meta.xml."""
    try:
        with zipfile.ZipFile(path) as z:
            names = set(z.namelist())
            member = next((n for n in ("docProps/core.xml", "meta.xml") if n in names), None)
            if member is None:
                return None
            with z.open(member) as f:
                xml = f.read(256 * 1024).decode("utf-8", "replace")  # capped: zip bombs
    except Exception:  # truncated, encrypted or exotic archives: metadata is best effort
        return None
    for tag in ("dc:creator", "cp:lastModifiedBy", "meta:initial-creator"):
        m = re.search(rf"<{tag}>([^<]+)</{tag}>", xml)
        if m and m.group(1).strip():
            return m.group(1).strip()
    return None


# -- 3: permissions ---------------------------------------------------------

KEY_RULES = {"file.private-key", "secret.private-key", "file.pkcs12", "file.crypto-wallet", "file.keystore"}
CRED_RULES = {"file.env", "file.credentials", "file.vpn-config", "file.tfstate", "file.password-db",
              "file.browser-logins"}
CONFIG_EXTS = {".conf", ".cfg", ".cnf", ".ini", ".yaml", ".yml", ".toml", ".json", ".xml", ".properties",
               ".env", ".sh", ".service", ".plist"}


def check_permissions(path: str, mode: int, found: List[Finding]) -> List[Finding]:
    if os.name == "nt":
        return []  # NTFS ACLs do not map onto POSIX mode bits
    mode, rules, name = stat.S_IMODE(mode), {f.rule for f in found}, os.path.basename(path)
    out = []
    if mode & 0o077 and rules & (KEY_RULES | CRED_RULES):
        out.append(Finding("perm.private-key" if rules & KEY_RULES else "perm.credentials", path,
                           detail=f"mode {mode:04o}"))
    config_like = name.startswith(".") or os.path.splitext(name)[1] in CONFIG_EXTS
    if mode & 0o002 and (config_like or rules & (KEY_RULES | CRED_RULES)):
        out.append(Finding("perm.world-writable", path, detail=f"mode {mode:04o}"))
    return out


# -- Walking the file system (read-only, symlinks never followed) -----------

SKIP_DIRS = {"node_modules", "__pycache__", "site-packages", "dist-packages", ".tox", ".mypy_cache",
             ".pytest_cache", ".ruff_cache"}
SYSTEM_DIRS = ("/proc", "/sys", "/dev")
HISTORY_FILES = {".bash_history", ".zsh_history", ".sh_history", ".history", "fish_history",
                 "consolehost_history.txt", ".python_history", ".mysql_history", ".psql_history",
                 ".sqlite_history", ".node_repl_history", ".rediscli_history", ".irb_history"}
CODE_EXTS = {".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".java", ".kt", ".go", ".rb", ".php",
             ".cs", ".c", ".h", ".cc", ".cpp", ".hpp", ".rs", ".swift", ".scala", ".dart", ".pl", ".pm",
             ".lua", ".vim", ".el", ".ex", ".exs", ".erl", ".hs", ".ml", ".clj", ".groovy", ".r"}
JPEG_EXTS = {".jpg", ".jpeg", ".jpe"}
OFFICE_EXTS = {".docx", ".xlsx", ".pptx", ".docm", ".xlsm", ".odt", ".ods", ".odp"}
NOISY_FILES = {"package-lock.json", "npm-shrinkwrap.json", "pnpm-lock.yaml", "go.sum", "known_hosts"}
NOISY_SUFFIXES = (".lock", ".min.js", ".min.css", ".map")


class Stats:
    def __init__(self):
        self.files = self.binary = self.large = self.errors = 0
        self.seen = set()  # (st_dev, st_ino): never scan the same file twice


def in_system_dir(path: str) -> bool:
    real = os.path.realpath(path)
    return os.name != "nt" and any(real == d or real.startswith(d + "/") for d in SYSTEM_DIRS)


def load_ignore(root: str) -> List[str]:
    """Glob lines from <root>/.dropignore ('#' comments and blank lines skipped)."""
    try:
        with open(os.path.join(root, ".dropignore"), encoding="utf-8", errors="replace") as f:
            return [ln.strip() for ln in f if ln.strip() and not ln.strip().startswith("#")]
    except OSError:
        return []


def is_ignored(rel: str, patterns: List[str], is_dir: bool = False) -> bool:
    """gitignore-lite: 'name' matches at any depth, 'a/b' or '/a' from the root, 'dir/' dirs only."""
    name = rel.rsplit("/", 1)[-1]
    return any(fnmatch.fnmatch(rel if "/" in p.rstrip("/") else name, p.strip("/"))
               for p in patterns if is_dir or not p.endswith("/"))


def walk(root: str, ignore: List[str], stats: Stats):
    """Yield every candidate file under root (or root itself when it is a file)."""
    if not os.path.isdir(root):
        yield root
        return

    def onerror(_exc):
        stats.errors += 1

    # followlinks=False (the default): symlinked dirs are listed but never entered
    for dirpath, dirnames, filenames in os.walk(root, onerror=onerror):
        rel_dir = os.path.relpath(dirpath, root).replace(os.sep, "/")
        prefix = "" if rel_dir == "." else rel_dir + "/"  # paths relative to root, '/'-separated
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS
                       and not (d in ("objects", "lfs") and os.path.basename(dirpath) == ".git")
                       and os.path.abspath(os.path.join(dirpath, d)) not in SYSTEM_DIRS
                       and not is_ignored(prefix + d, ignore, is_dir=True)]
        for name in filenames:
            full = os.path.join(dirpath, name)
            if not os.path.islink(full) and not is_ignored(prefix + name, ignore):
                yield full


def read_text(path: str, size: int, max_size: int, stats: Stats) -> Optional[str]:
    """Decoded text, or None for binary, oversized or unreadable files."""
    if size > max_size:
        stats.large += 1
        return None
    try:
        with open(path, "rb") as f:
            head = f.read(8192)
            if head[:2] in (codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE):  # Windows "Unicode" text
                return (head + f.read(max_size)).decode("utf-16", "replace")
            if b"\0" in head:
                stats.binary += 1
                return None
            return (head + f.read(max_size)).decode("utf-8", "replace")
    except OSError:
        stats.errors += 1
        return None


def scan_file(path: str, max_size: int, stats: Stats) -> List[Finding]:
    try:
        st = os.stat(path)
    except OSError:
        stats.errors += 1
        return []
    ident = (st.st_dev, st.st_ino)
    if not stat.S_ISREG(st.st_mode) or (st.st_ino and ident in stats.seen):
        return []  # sockets, FIFOs and devices are never opened; duplicates never rescanned
    stats.seen.add(ident)
    stats.files += 1
    name = os.path.basename(path).lower()
    ext = os.path.splitext(name)[1]
    names = check_names(path)
    found: List[Finding] = []

    # 6. metadata in the binary formats we understand
    if ext in JPEG_EXTS:
        gps = jpeg_gps(path)
        if gps:
            found.append(Finding("meta.gps-exif", path, shown="~%.1f, %.1f" % gps,
                                 detail="exact position is in the file"))
    elif ext == ".pdf" or ext in OFFICE_EXTS:
        author = pdf_author(path) if ext == ".pdf" else office_author(path)
        if author:
            found.append(Finding("meta.doc-author", path, secret=author))

    # 2, 4, 5. text content (browser login stores are encrypted blobs: name only)
    text = None
    if not (ext in JPEG_EXTS or ext in OFFICE_EXTS or ext == ".pdf" or name in NOISY_FILES
            or name.endswith(NOISY_SUFFIXES) or any(r == "file.browser-logins" for r, _ in names)):
        text = read_text(path, st.st_size, max_size, stats)
    if text is not None:
        found += scan_text(path, text, history=name in HISTORY_FILES, code=ext in CODE_EXTS)

    # 1. filenames; gated ones only count if the (readable) content agrees
    lowered = text.lower() if text is not None and any(m for _, m in names) else None
    found += [Finding(rule, path) for rule, markers in names
              if not (markers and lowered is not None and not any(m in lowered for m in markers))]

    # id_rsa matches by name *and* by content: keep one line, with the content's verdict
    by_name = next((f for f in found if f.rule == "file.private-key"), None)
    block = next((f for f in found if f.rule == "secret.private-key"), None)
    if by_name and block:
        found.remove(block)
        by_name.severity, by_name.detail = block.severity, block.detail

    # 3. permissions
    return found + check_permissions(path, st.st_mode, found)


# -- --home: common risky places, if they exist -----------------------------

_CHROMIUM = (".config/google-chrome", ".config/chromium", ".config/BraveSoftware/Brave-Browser",
             ".config/microsoft-edge", "Library/Application Support/Google/Chrome",
             "Library/Application Support/Microsoft Edge", "AppData/Local/Google/Chrome/User Data",
             "AppData/Local/Microsoft/Edge/User Data")
_FIREFOX = (".mozilla/firefox", "Library/Application Support/Firefox/Profiles",
            "AppData/Roaming/Mozilla/Firefox/Profiles")
HOME_TARGETS = (  # keys and tokens, wallets, shell history, and where exports/dumps pile up
    ".ssh", ".aws", ".azure", ".docker", ".kube", ".config/gcloud", ".config/gh", ".config/hub", ".config/rclone",
    ".terraform.d", ".netrc", "_netrc", ".npmrc", ".pypirc", ".git-credentials", ".pgpass", ".my.cnf", ".env",
    ".bitcoin/wallet.dat", ".bitcoin/wallets", ".electrum/wallets", ".ethereum/keystore",
    ".bash_history", ".zsh_history", ".sh_history", ".history", ".local/share/fish/fish_history",
    ".python_history", ".mysql_history", ".psql_history", ".sqlite_history", ".node_repl_history",
    ".rediscli_history", ".local/share/powershell/PSReadLine/ConsoleHost_history.txt",
    "AppData/Roaming/Microsoft/Windows/PowerShell/PSReadLine/ConsoleHost_history.txt",
    "Desktop", "Documents", "Downloads", "storage/downloads", "storage/shared/Documents",  # Termux: ~/storage
) + tuple(b + "/*/Login Data" for b in _CHROMIUM) + tuple(
    f"{b}/*/{f}" for b in _FIREFOX for f in ("logins.json", "key4.db"))


def home_targets() -> List[str]:
    home = os.path.expanduser("~")
    return [p for pattern in HOME_TARGETS for p in sorted(glob.glob(os.path.join(home, *pattern.split("/"))))]


# -- Output -----------------------------------------------------------------

def exposure_score(findings: List[Finding]) -> int:
    return min(100, sum(WEIGHT[f.severity] for f in findings))


def _pretty(path: str) -> str:
    home = os.path.expanduser("~")
    return "~" + path[len(home):] if len(home) > 1 and path.startswith(home + os.sep) else path


def print_report(findings: List[Finding], hidden: int, stats: Stats, elapsed: float, args) -> None:
    print(bold("drop") + dim(f" v{VERSION} · offline · read-only") + "\n")
    for sev in reversed(SEVERITIES):
        group = [f for f in findings if f.severity == sev]
        if group:
            print(SEV_COLOR[sev](f"{sev.upper()} ({len(group)})"))
        for i, f in enumerate(group):
            if i == 0 or f.path != group[i - 1].path:
                print("  " + bold(_pretty(f.path)))
            where = f"L{f.line}" if f.line else "-"
            shown = "  " + warn(f.shown) if f.shown else ""
            print(f"    {dim(where.ljust(6))} {primary(f.rule.ljust(22))} {f.message}{shown}")
        if group:
            print()

    if findings:
        print(bold("how to fix"))
        for rule in dict.fromkeys(f.rule for f in findings):
            print(f"  {primary(rule.ljust(22))} {muted(RULE[rule].fix)}")
    else:
        print("  " + ok("nothing found") + dim(f" at or above {args.min_severity}"))

    counts, score = Counter(f.severity for f in findings), exposure_score(findings)
    print("\n" + dim("-" * 60))
    print(f"scanned {stats.files} files in {elapsed:.2f}s" + dim(
        f" · {stats.binary} binary · {stats.large} over {args.max_size / 1048576:g} MB"
        f" · {stats.errors} unreadable"))
    print(" · ".join(SEV_COLOR[s](f"{s} {counts.get(s, 0)}") for s in reversed(SEVERITIES)))
    if hidden:
        print(dim(f"{hidden} lower-severity finding(s) hidden by --min-severity {args.min_severity}"))
    tone = ok if score == 0 else muted if score < 20 else warn if score < 50 else err
    print("exposure score " + bold(tone(f"{score}/100")))


def print_rules() -> None:
    print(bold("drop") + dim(f" v{VERSION} · {len(RULES)} rules, all evaluated locally"))
    for i, r in enumerate(RULES):
        category = r.id.split(".")[0]
        if i == 0 or category != RULES[i - 1].id.split(".")[0]:
            print("\n" + bold(CATEGORY_TITLES[category]))
        print(f"  {SEV_COLOR[r.severity](r.severity.ljust(8))}  {primary(r.id.ljust(22))}  {r.title}")


# -- CLI --------------------------------------------------------------------

def parse_size(text: str) -> int:
    m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*([kmg]?)(?:i?b)?\s*", text.lower())
    if not m:
        raise argparse.ArgumentTypeError(f"invalid size {text!r} (try 500KB, 5MB, 1GB)")
    return int(float(m.group(1)) * 1024 ** " kmg".index(m.group(2) or " "))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="drop",
        description="Find files on your own machine that would hurt if they leaked. "
                    "Offline and read-only: nothing is modified, uploaded or sent anywhere.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Examples:\n  drop scan\n  drop scan --home\n  drop scan ~/src --min-severity high --json\n"
               "\nExit codes: 0 clean, 1 findings at/above --min-severity, 2 error.")
    p.add_argument("--version", action="version", version=f"drop {VERSION}")
    sub = p.add_subparsers(dest="cmd", metavar="COMMAND")
    s = sub.add_parser("scan", help="scan paths (default: current directory)")
    s.add_argument("paths", nargs="*", metavar="PATH", help="files or directories to scan")
    s.add_argument("--home", action="store_true", help="scan common risky locations in your home dir")
    s.add_argument("--json", action="store_true", help="machine-readable output")
    s.add_argument("--min-severity", choices=SEVERITIES, default="low", metavar="LEVEL",
                   help="report only findings at or above LEVEL: low|medium|high|critical")
    s.add_argument("--exclude", action="append", default=[], metavar="GLOB",
                   help="skip files/dirs matching GLOB (repeatable, .dropignore syntax)")
    s.add_argument("--max-size", type=parse_size, default=5 * 1024 * 1024, metavar="SIZE",
                   help="skip content scanning of larger files (default: 5MB)")
    sub.add_parser("rules", help="list all detection rules")
    return p


def run_scan(args) -> int:
    missing = [p for p in args.paths if not os.path.exists(p)]
    if missing:
        sys.stderr.write("".join(err(f"drop: no such file or directory: {p}") + "\n" for p in missing))
        return 2
    roots = list(dict.fromkeys((args.paths or ([] if args.home else ["."]))
                               + (home_targets() if args.home else [])))
    stats, findings, started = Stats(), [], time.time()
    for root in roots:
        if in_system_dir(root):
            sys.stderr.write(warn(f"drop: skipping system path {root}") + "\n")
            continue
        ignore = args.exclude + (load_ignore(root) if os.path.isdir(root) else [])
        for path in walk(root, ignore, stats):
            try:
                findings += scan_file(os.path.normpath(path), args.max_size, stats)
            except Exception:  # one odd file must never abort the whole scan
                stats.errors += 1
    elapsed = time.time() - started

    shown = sorted((f for f in findings if RANK[f.severity] >= RANK[args.min_severity]),
                   key=lambda f: (-RANK[f.severity], f.path, f.line or 0, f.rule))
    if args.json:
        counts = Counter(f.severity for f in shown)
        print(json.dumps({
            "version": VERSION,
            "scanned": {"paths": roots, "files": stats.files, "skipped_binary": stats.binary,
                        "skipped_large": stats.large, "errors": stats.errors, "seconds": round(elapsed, 3)},
            "summary": {"score": exposure_score(shown), "min_severity": args.min_severity,
                        **{s: counts.get(s, 0) for s in SEVERITIES}},
            "findings": [f.to_json() for f in shown],
        }, indent=2))
    else:
        print_report(shown, len(findings) - len(shown), stats, elapsed, args)
    return 1 if shown else 0


def main(argv: Optional[List[str]] = None) -> int:
    for stream in (sys.stdout, sys.stderr):  # odd filenames must never crash printing
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, ValueError, OSError):
            pass
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.cmd == "scan":
            return run_scan(args)
        if args.cmd == "rules":
            print_rules()
        else:
            parser.print_help()
        return 0
    except KeyboardInterrupt:
        sys.stderr.write("\ndrop: interrupted\n")
        return 2
    except BrokenPipeError:  # e.g. `drop scan | head`: stop quietly
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        return 2


if __name__ == "__main__":
    sys.exit(main())
