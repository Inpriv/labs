#!/usr/bin/env python3
"""Tests for drop. Pure stdlib:  python -m unittest test_drop  (or python test_drop.py)

Every "secret" and PII value below is obviously fake and glued together from
fragments at runtime, so this file never contains anything that looks like a
live credential, and `drop scan` over this repository comes back clean.
"""

import base64
import contextlib
import hashlib
import io
import json
import os
import struct
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import drop  # noqa: E402

FAKE_AWS = "AKIA" + "FAKE" * 4
FAKE_GITHUB = "ghp" + "_" + "Fake" * 9                # prefix + 36 chars
FAKE_STRIPE = "sk_" + "live_" + "FAKE" * 6
FAKE_JWT = "eyJ" + "hbGciOiJIUzI1NiJ9" + ".eyJ" + "zdWIiOiJmYWtlIn0" + "." + "fakesignature00"
FAKE_PW = "Tr0ub4dor" + "-fake"
CARD = "4539 1488 " + "0343 6467"                     # Luhn-valid, made up
IBAN = "PL61 1090 1014 " + "0000 0712 1981 2874"      # mod-97 valid sample
PESEL = "440514" + "01359"                             # checksum-valid sample
SSN = "123-45-" + "6789"
KEY_BEGIN = "-----BEGIN " + "{}PRIVATE KEY-----"
KEY_END = "-----END " + "{}PRIVATE KEY-----"
# random-looking but derived from a fixed string, so tests are deterministic
RANDOM_TOKEN = base64.b64encode(hashlib.sha256(b"drop-test").digest()).decode().rstrip("=")
SEED_WORDS = " ".join(["absurd", "access", "abandon", "achieve", "absent", "account",   # random order,
                       "abuse", "ability", "accident", "absorb", "accuse", "abstract"])  # like a real seed


def openssh_key(cipher: bytes) -> str:
    """A fake openssh-key-v1 block whose header names `cipher` (b'none' = unencrypted)."""
    raw = b"openssh-key-v1\x00" + struct.pack(">I", len(cipher)) + cipher + b"\x00" * 60
    body = base64.b64encode(raw).decode()
    return "\n".join([KEY_BEGIN.format("OPENSSH "), body, KEY_END.format("OPENSSH "), ""])


def jpeg_with_gps(lat=(52, 13, 0), lon=(21, 0, 0), lat_ref=b"N", lon_ref=b"E") -> bytes:
    """Smallest JPEG-ish file with an EXIF APP1 holding a GPS IFD."""
    def entry(tag, typ, count, value4):
        return struct.pack("<HHI", tag, typ, count) + value4

    def rationals(dms):
        return b"".join(struct.pack("<II", v, 1) for v in dms)

    ifd0 = struct.pack("<H", 1) + entry(0x8825, 4, 1, struct.pack("<I", 26)) + struct.pack("<I", 0)
    gps = (struct.pack("<H", 4)
           + entry(1, 2, 2, lat_ref + b"\0\0\0") + entry(2, 5, 3, struct.pack("<I", 80))
           + entry(3, 2, 2, lon_ref + b"\0\0\0") + entry(4, 5, 3, struct.pack("<I", 104))
           + struct.pack("<I", 0))
    tiff = b"II*\0" + struct.pack("<I", 8) + ifd0 + gps + rationals(lat) + rationals(lon)
    app1 = b"Exif\0\0" + tiff
    return b"\xff\xd8\xff\xe1" + struct.pack(">H", len(app1) + 2) + app1 + b"\xff\xda\0\0\xff\xd9"


def rules_in(text, **kw):
    return [f.rule for f in drop.scan_text("fixture.txt", text, **kw)]


class Validators(unittest.TestCase):
    def test_luhn(self):
        self.assertTrue(drop.luhn_ok(CARD.replace(" ", "")))
        self.assertTrue(drop.luhn_ok("79927398713"))
        self.assertFalse(drop.luhn_ok(CARD.replace(" ", "")[:-1] + "8"))
        self.assertFalse(drop.luhn_ok("12ab"))

    def test_iban(self):
        self.assertTrue(drop.iban_ok("GB82 WEST " + "1234 5698 7654 32"))
        self.assertTrue(drop.iban_ok(IBAN.replace(" ", "")))
        self.assertFalse(drop.iban_ok("GB82 WEST " + "1234 5698 7654 33"))
        self.assertFalse(drop.iban_ok("not an iban"))

    def test_pesel(self):
        self.assertTrue(drop.pesel_ok(PESEL))
        self.assertFalse(drop.pesel_ok("44051401358"))   # bad checksum
        self.assertFalse(drop.pesel_ok("44150001352"))   # month 15 does not exist
        self.assertFalse(drop.pesel_ok("4405140135"))

    def test_entropy(self):
        self.assertEqual(drop.shannon_entropy(""), 0)
        self.assertEqual(drop.shannon_entropy("aaaa"), 0)
        self.assertAlmostEqual(drop.shannon_entropy("abcd"), 2.0)
        self.assertGreater(drop.shannon_entropy(RANDOM_TOKEN), drop.ENTROPY_THRESHOLD)
        self.assertLess(drop.shannon_entropy("thisIsAVeryLongButBoringName1"), drop.ENTROPY_THRESHOLD)

    def test_redact(self):
        self.assertEqual(drop.redact(FAKE_AWS), "AKIA****KE")
        self.assertEqual(drop.redact("hunter2hunter"), "hu****r")
        self.assertEqual(drop.redact("hunter2"), "****")
        for value in (FAKE_AWS, FAKE_GITHUB, "correct-horse-battery"):
            self.assertLessEqual(len(drop.redact(value).replace("*", "")), len(value) / 3)

    def test_parse_size(self):
        self.assertEqual(drop.parse_size("5MB"), 5 * 1024 * 1024)
        self.assertEqual(drop.parse_size("500k"), 500 * 1024)
        self.assertEqual(drop.parse_size("123"), 123)


class ContentRules(unittest.TestCase):
    def test_provider_tokens(self):
        text = f"aws = {FAKE_AWS}\ngh: {FAKE_GITHUB}\nstripe {FAKE_STRIPE}\nAuthorization: Bearer {FAKE_JWT}\n"
        self.assertEqual(sorted(rules_in(text)),
                         ["secret.aws-key", "secret.github-token", "secret.jwt", "secret.stripe-key"])

    def test_documentation_example_key_is_ignored(self):
        self.assertEqual(rules_in("AKIA" + "IOSFODNN7" + "EXAMPLE"), [])

    def test_private_key_encryption(self):
        found = drop.scan_text("k", openssh_key(b"none"))
        self.assertEqual([(f.rule, f.severity, f.detail) for f in found],
                         [("secret.private-key", "critical", "unencrypted")])
        found = drop.scan_text("k", openssh_key(b"aes256-ctr"))
        self.assertEqual([(f.rule, f.severity) for f in found], [("secret.private-key", "high")])
        legacy = (KEY_BEGIN.format("RSA ") + "\nProc-Type: 4,ENCRYPTED\n\n" + RANDOM_TOKEN + "\n"
                  + KEY_END.format("RSA "))
        self.assertEqual(drop.scan_text("k", legacy)[0].severity, "high")
        # a BEGIN line with no key material (docs, MIME tables) is not a key
        self.assertEqual(rules_in(f'<match value="{KEY_BEGIN.format("PGP ")}"/>'), [])

    def test_assignments_and_placeholders(self):
        self.assertEqual(rules_in(f"DB_PASSWORD={FAKE_PW}"), ["secret.assignment"])
        self.assertEqual(rules_in(f'"client_secret": "{FAKE_PW}"'), ["secret.assignment"])
        for harmless in ("password=${DB_PASSWORD}", "api_key: your-api-key-here", "secret = changeme",
                         "PASSWORD_MIN_LENGTH = 8", "token: {{ vault_token }}", "tokenizer = load()",
                         "password = xxxxxxxx", "token_type: access_token", "typedef token::kind_type",
                         "base-passwd: no-debconf-config", "prstoken = regproc",
                         "'EndToken' => 'https://github.com/o/r/issues'", 'password = request.form["pw"]'):
            self.assertEqual(rules_in(harmless), [], harmless)
        # in source code only quoted literals count
        self.assertEqual(rules_in("password = user_input_value", code=True), [])
        self.assertEqual(rules_in(f'password = "{FAKE_PW}"', code=True), ["secret.assignment"])

    def test_url_credentials(self):
        self.assertEqual(rules_in(f"postgres://admin:{FAKE_PW}@db.local/app"), ["secret.url-credentials"])
        self.assertEqual(rules_in("https://user:${PASS}@example.org"), [])

    def test_high_entropy(self):
        self.assertEqual(rules_in(f'signing_value = "{RANDOM_TOKEN}"'), ["secret.high-entropy"])
        self.assertEqual(rules_in(f"{RANDOM_TOKEN}"), [])                      # no assignment context
        self.assertEqual(rules_in('name = "thisIsAVeryLongButBoringName1"'), [])
        self.assertEqual(rules_in(f'integrity="sha512-{RANDOM_TOKEN}"'), [])

    def test_seed_phrase(self):
        self.assertEqual(rules_in(SEED_WORDS), ["secret.seed-phrase"])
        found = drop.scan_text("n", "my wallet seed:\n" + SEED_WORDS)
        self.assertEqual(found[0].severity, "critical")
        self.assertNotIn("abandon", found[0].shown)
        prose = "this is just a normal sentence that happens to have quite a few words in it"
        self.assertEqual(rules_in(prose), [])
        keywords = "syn keyword jamStatement break call dbms flush global include msg parms proc public"
        self.assertEqual(rules_in(keywords), [])                               # sorted, no vowels
        self.assertEqual(rules_in(" ".join(SEED_WORDS.split()[:11])), [])      # 11 words

    def test_pii(self):
        text = f"card {CARD}\niban {IBAN}\npesel {PESEL}\nssn {SSN}\n"
        self.assertEqual(sorted(rules_in(text)), ["pii.credit-card", "pii.iban", "pii.pesel", "pii.ssn"])
        self.assertEqual(rules_in(f"Jan Fake,{CARD},PL\n"), ["pii.credit-card"])  # CSV cell
        self.assertEqual(rules_in("card " + CARD[:-1] + "8"), [])               # fails Luhn
        self.assertEqual(rules_in("order 1234567890123"), [])                  # no card prefix
        self.assertEqual(rules_in('id="gradient3495-841-851-719"'), [])        # not 4-digit groups
        self.assertEqual(rules_in("card 4000 0000 0000 0002"), [])             # too few distinct digits
        self.assertEqual(rules_in("52BB " + CARD + " 5366"), [])                # inside a table of numbers

    def test_credential_dump(self):
        dump = "".join(f"user{i}@example.org:fakepass{i}\n" for i in range(5))
        self.assertEqual(rules_in(dump), ["pii.credential-dump"])
        self.assertEqual(rules_in("a@example.org:fakepass1\n"), [])

    def test_history(self):
        hist = f"ls\nmysql -u root -pFakePass123 app\nexport GITHUB_TOKEN={FAKE_GITHUB}\ncurl -u bob:$PASS x\n"
        found = drop.scan_text(".bash_history", hist, history=True)
        self.assertEqual([(f.rule, f.line) for f in found], [("history.secret", 2), ("history.secret", 3)])
        self.assertEqual(found[1].severity, "critical")


class FileLevel(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, rel, content, mode=None):
        path = os.path.join(self.dir, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(content.encode() if isinstance(content, str) else content)
        if mode is not None:
            os.chmod(path, mode)
        return path

    def scan_json(self, *extra):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = drop.main(["scan", self.dir, "--json", *extra])
        return code, json.loads(out.getvalue())

    def test_filenames(self):
        def names(p):
            return [r for r, _ in drop.check_names(p)]
        self.assertEqual(names("x/.env.production"), ["file.env"])
        self.assertEqual(names("x/.env.example"), [])
        self.assertEqual(names("home/.aws/credentials"), ["file.credentials"])
        self.assertEqual(names("x/credentials"), [])
        self.assertEqual(names("x/terraform.tfstate"), ["file.tfstate"])
        self.assertEqual(names("x/site-backup-2024.tar.gz"), ["file.backup"])
        self.assertEqual(names("x/id_ed25519.pub"), [])

    def test_gated_names(self):
        self.write("a/.npmrc", "save-exact=true\n")
        self.write("b/.npmrc", "//registry.npmjs.org/:_authToken=${NPM_TOKEN}\n")
        self.write("schema.sql", "CREATE TABLE users (id int);\n")
        self.write("migration.sql", "INSERT INTO settings VALUES (1);\n")
        self.write("dump.sql", "-- PostgreSQL database dump\nCOPY users (id) FROM stdin;\n")
        _, report = self.scan_json()
        flagged = {(os.path.basename(os.path.dirname(f["path"])), os.path.basename(f["path"]), f["rule"])
                   for f in report["findings"]}
        self.assertIn(("b", ".npmrc", "file.credentials"), flagged)
        self.assertNotIn(("a", ".npmrc", "file.credentials"), flagged)
        self.assertEqual({f[1] for f in flagged if f[2] == "file.db-dump"}, {"dump.sql"})

    def test_end_to_end_json_is_redacted(self):
        self.write("app/.env", f"AWS_ACCESS_KEY_ID={FAKE_AWS}\nDB_PASSWORD={FAKE_PW}\n")
        self.write("notes.txt", f"stripe: {FAKE_STRIPE}\n")
        self.write("node_modules/pkg/leak.txt", f"{FAKE_AWS}\n")     # always skipped
        self.write("vendor/leak.txt", f"{FAKE_AWS}\n")               # skipped via .dropignore
        self.write(".dropignore", "# local noise\nvendor/\n")
        code, report = self.scan_json()
        self.assertEqual(code, 1)
        self.assertEqual(set(report), {"version", "scanned", "summary", "findings"})
        rules = {(os.path.basename(f["path"]), f["rule"]) for f in report["findings"]}
        self.assertTrue({(".env", "file.env"), (".env", "secret.aws-key"), (".env", "secret.assignment"),
                         ("notes.txt", "secret.stripe-key")} <= rules)
        self.assertFalse(any("leak.txt" in f["path"] for f in report["findings"]))
        raw = json.dumps(report)
        for secret in (FAKE_AWS, FAKE_STRIPE, FAKE_PW):
            self.assertNotIn(secret, raw)
        for f in report["findings"]:
            self.assertEqual(set(f), {"rule", "severity", "path", "line", "redacted_match", "message", "fix"})

    def test_exit_codes_and_filters(self):
        self.write("readme.txt", "nothing to see here\n")
        self.assertEqual(self.scan_json()[0], 0)
        self.write("ids.txt", f"pesel {PESEL}\n")               # low severity only
        self.assertEqual(self.scan_json()[0], 1)
        code, report = self.scan_json("--min-severity", "high")
        self.assertEqual((code, report["findings"]), (0, []))
        code, report = self.scan_json("--exclude", "ids.txt")
        self.assertEqual(code, 0)
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(drop.main(["scan", os.path.join(self.dir, "missing")]), 2)

    def test_exif_gps(self):
        path = self.write("photo.jpg", jpeg_with_gps())
        lat, lon = drop.jpeg_gps(path)
        self.assertAlmostEqual(lat, 52.2167, places=3)
        self.assertAlmostEqual(lon, 21.0, places=3)
        south_west = self.write("sw.jpg", jpeg_with_gps(lat_ref=b"S", lon_ref=b"W"))
        self.assertLess(drop.jpeg_gps(south_west)[0], 0)
        self.assertIsNone(drop.jpeg_gps(self.write("plain.jpg", b"\xff\xd8\xff\xd9")))
        self.assertIsNone(drop.jpeg_gps(self.write("junk.jpg", b"\xff\xd8\xff\xe1\x00")))

    def test_document_author(self):
        path = os.path.join(self.dir, "report.docx")
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("docProps/core.xml",
                       "<cp:coreProperties><dc:creator>Jane Fakename</dc:creator></cp:coreProperties>")
        self.assertEqual(drop.office_author(path), "Jane Fakename")
        pdf = self.write("a.pdf", b"%PDF-1.4\n1 0 obj << /Author (Jane Fakename) >> endobj\n%%EOF")
        self.assertEqual(drop.pdf_author(pdf), "Jane Fakename")
        _, report = self.scan_json()
        self.assertNotIn("Jane Fakename", json.dumps(report))
        self.assertEqual(sorted(f["rule"] for f in report["findings"]), ["meta.doc-author"] * 2)

    @unittest.skipIf(os.name == "nt", "POSIX permissions")
    def test_permissions(self):
        key = self.write(".ssh/id_ed25519", openssh_key(b"none"), mode=0o644)
        self.write("app.conf", "debug = true\n", mode=0o666)
        found = drop.scan_file(key, 1 << 20, drop.Stats())
        self.assertEqual(sorted(f.rule for f in found), ["file.private-key", "perm.private-key"])
        self.assertEqual(found[0].severity, "critical")          # folded in from the content check
        os.chmod(key, 0o600)
        self.assertEqual([f.rule for f in drop.scan_file(key, 1 << 20, drop.Stats())], ["file.private-key"])
        conf = drop.scan_file(os.path.join(self.dir, "app.conf"), 1 << 20, drop.Stats())
        self.assertEqual([f.rule for f in conf], ["perm.world-writable"])

    def test_binary_and_large_files_are_skipped(self):
        self.write("blob.bin", b"\0" + FAKE_AWS.encode())
        self.write("big.txt", FAKE_AWS + "\n" + "x" * 5000)
        code, report = self.scan_json("--max-size", "1KB")
        self.assertEqual((code, report["findings"]), (0, []))
        self.assertEqual((report["scanned"]["skipped_binary"], report["scanned"]["skipped_large"]), (1, 1))

    @unittest.skipIf(os.name == "nt", "symlinks need privileges on Windows")
    def test_symlinks_are_not_followed(self):
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        target = os.path.join(outside.name, "secret.txt")
        with open(target, "w") as f:
            f.write(f"{FAKE_AWS}\n")
        os.symlink(target, os.path.join(self.dir, "link.txt"))
        os.symlink(outside.name, os.path.join(self.dir, "linkdir"))
        self.assertEqual(self.scan_json()[1]["findings"], [])


if __name__ == "__main__":
    unittest.main()
