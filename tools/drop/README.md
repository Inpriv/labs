# drop — what would hurt you if this leaked?

```
     _
  __| |_ __ ___  _ __
 / _` | '__/ _ \| '_ \
| (_| | | | (_) | |_) |
 \__,_|_|  \___/| .__/
                |_|
```

A local, offline scanner that finds files on **your own machine** that could
leak sensitive data, and tells you how bad it is and what to do about it.
Point it at a folder, a laptop home directory or a backup before you sync,
share, sell or lose it.

> Part of the [Inpriv Labs](https://github.com/Inpriv/labs) family:
> privacy by design, nothing phones home.

## Privacy guarantees

- **Fully offline.** drop contains no network code at all: no `socket`,
  `urllib` or `http` import, no telemetry, no update check. You can run it
  with networking disabled.
- **Read-only.** It never deletes, moves, edits, uploads or "auto-fixes"
  anything, and has no fix mode. It only reads the files it scans (plus
  `.dropignore`) and writes nothing but its report to stdout.
- **Secrets are never printed in full**, in the terminal or in JSON. Matches
  are masked on detection (`AKIA****XY`) and the raw value is never stored.
  The mask never reveals more than a third of the value, and nothing at
  all for values under 9 characters. Seed phrases are shown only as
  `12 words (hidden)`.
- **Pure standard library**, Python 3.8+, one file. Linux, macOS, Termux
  and Windows.

## Install

There is nothing to install: copy `drop.py` anywhere and run it.

```bash
curl -fsSLO https://raw.githubusercontent.com/Inpriv/labs/main/tools/drop/drop.py
python3 drop.py scan
```

Or from a checkout:

```bash
git clone https://github.com/Inpriv/labs.git
cd labs/tools/drop
python3 drop.py scan ~/Documents
```

Optional: `chmod +x drop.py && ln -s "$PWD/drop.py" ~/.local/bin/drop` to get a `drop` command.
On Windows, use `py drop.py scan`.

## Usage

```text
drop scan [PATH ...]            scan paths (default: current dir)
drop scan --home                scan common risky locations in the home dir
drop scan --json                machine-readable output
drop scan --min-severity high   only report high and critical (low|medium|high|critical)
drop scan --exclude GLOB        skip matching files/dirs (repeatable)
drop scan --max-size 5MB        skip content scanning of larger files (default 5MB)
drop rules                      list all detection rules
drop --version
```

Examples:

```bash
drop scan                                   # the current project
drop scan --home                            # ~/.ssh, ~/.aws, history files, Downloads, ...
drop scan ~/backup-usb --min-severity high  # only what really matters
drop scan . --exclude 'fixtures/' --exclude '*.log'
drop scan --json ~/Documents > drop-report.json
```

`--home` looks at these locations when they exist:
- key and token stores: `~/.ssh`, `~/.aws`, `~/.azure`, `~/.docker`, `~/.kube`,
  `~/.config/{gcloud,gh,hub,rclone}`, `~/.netrc`, `~/.npmrc`, `~/.pypirc`,
  `~/.git-credentials`, `~/.pgpass`
- wallet folders
- shell and REPL history, including PowerShell's `ConsoleHost_history.txt`
- Chromium and Firefox saved-login databases
- `Desktop`, `Documents` and `Downloads` (on Termux, `~/storage/downloads`)

Photo folders are left out because they are large. Run `drop scan ~/Pictures`
to check your photos for GPS tags.

### Sample output

```text
drop v0.1.0 · offline · read-only

CRITICAL (6)
  demo/home/.bash_history
    L3     history.secret         secret in shell / REPL history (GitHub token)  ghp_****ke
  demo/keys/id_ed25519
    -      file.private-key       SSH / PuTTY private key file (unencrypted)
  demo/notes/wallet.txt
    L2     secret.seed-phrase     possible wallet seed phrase (heuristic)  12 words (hidden)
  demo/project/.env
    L1     secret.aws-key         AWS access key id  AKIA****KE
  ...

MEDIUM (11)
  demo/notes/customers.csv
    L2     pii.credit-card        card number (Luhn-valid, heuristic)  4539****67
    L2     pii.iban               IBAN (mod-97 valid, heuristic)  PL61****74
  demo/photos/IMG_0001.jpg
    -      meta.gps-exif          photo with GPS location in EXIF (exact position is in the file)  ~52.2, 21.0
  ...

how to fix
  history.secret         Delete the line and rotate the secret; start such commands with a space (HISTCONTROL=ignorespace).
  file.private-key       Add a passphrase (ssh-keygen -p -f FILE); keep keys in ~/.ssh, never in projects or clouds.
  ...

------------------------------------------------------------
scanned 18 files in 0.01s · 1 binary · 0 over 5 MB · 0 unreadable
critical 6 · high 6 · medium 11 · low 2
exposure score 100/100
```

Findings are grouped by severity and then by file. `L3` is the line number,
and `-` means the finding is about the file itself (its name, permissions or
metadata). Colours turn off automatically when output isn't a terminal or
`NO_COLOR` is set.

## Exit codes (CI and pre-commit)

| code | meaning |
|------|---------|
| `0`  | nothing found at or above `--min-severity` |
| `1`  | findings at or above `--min-severity` |
| `2`  | error: bad arguments, a path that doesn't exist, interrupted |

GitHub Actions / any CI:

```yaml
- run: python3 tools/drop/drop.py scan --min-severity high
```

A minimal git pre-commit hook (`.git/hooks/pre-commit`) that checks the
files you are about to commit (their working-tree copies):

```sh
#!/bin/sh
files=$(git diff --cached --name-only --diff-filter=ACM)
[ -z "$files" ] || exec python3 ~/bin/drop.py scan --min-severity high $files
```

## JSON output

`--json` prints one object with a stable schema:

```json
{
  "version": "0.1.0",
  "scanned": {"paths": ["demo"], "files": 18, "skipped_binary": 1,
              "skipped_large": 0, "errors": 0, "seconds": 0.008},
  "summary": {"score": 100, "min_severity": "low",
              "low": 2, "medium": 11, "high": 6, "critical": 6},
  "findings": [
    {
      "rule": "secret.aws-key",
      "severity": "critical",
      "path": "demo/project/.env",
      "line": 1,
      "redacted_match": "AKIA****KE",
      "message": "AWS access key id",
      "fix": "Deactivate and rotate it in IAM, then switch to SSO / short-lived credentials."
    }
  ]
}
```

- `line` is `null` for file-level findings.
- `redacted_match` is `null` when there is nothing to show. It is **always
  masked**: raw secrets never reach the JSON.
- Findings are sorted by severity (critical first), then path, then line.

## Exposure score

A single 0–100 number so you can compare scans before and after a clean-up:

```
score = min(100, 25 × critical + 10 × high + 4 × medium + 1 × low)
```

One critical finding is already a quarter of the scale, and four max it out.
The score only counts findings that pass `--min-severity`.

## Ignoring things: `.dropignore` and `--exclude`

drop reads `.dropignore` from the root of each directory you scan. It uses
simple gitignore-like glob lines:

```gitignore
# whole-line comments and blank lines are ignored

# a bare pattern matches the name at any depth
*.log
# a trailing slash matches directories only
fixtures/
# a leading or inner slash anchors the pattern to the scan root
/build
docs/examples/*.env
```

`--exclude GLOB` takes the same syntax and can be repeated. Negation (`!`)
and `**` are not supported, but `*` also matches across `/`.

drop always skips:
- symlinks. They are never followed, so nothing outside the scan root is
  read. Whatever a link points to *inside* the root is scanned at its real
  location.
- `/proc`, `/sys` and `/dev`
- `node_modules`, `.git/objects`, `site-packages` and similar vendored or
  cache directories
- sockets, FIFOs and devices

## Rules

`drop rules` prints this list. Severities are defaults; a few findings
adjust them. Private keys are critical when unencrypted and high when
passphrase-protected. A seed phrase becomes critical when a nearby line
mentions seed, wallet or recovery. Anything found in shell history is at
least high.

**1. Sensitive filenames**

| rule | severity | matches |
|------|----------|---------|
| `file.private-key` | critical | `id_rsa`, `id_dsa`, `id_ecdsa`, `id_ed25519` (+`_sk`), `*.ppk` |
| `file.pkcs12` | high | `*.p12`, `*.pfx` |
| `file.crypto-wallet` | high | `wallet.dat`, Ethereum `UTC--*` keystores, Electrum `default_wallet` |
| `file.keystore` | high | `*.keystore`, `*.jks`, `*.bks` |
| `file.password-db` | medium | `*.kdbx`, `*.kdb` |
| `file.env` | high | `.env`, `.env.*`, `*.env`, `.envrc` (not `.env.example` / `.sample` / `.template` / `.dist`) |
| `file.credentials` | high | `.netrc`, `.git-credentials`, `.pgpass`, `.aws/credentials`, `.kube/config`, `kubeconfig`, gcloud ADC; `.npmrc`, `.pypirc`, `.my.cnf`, `.docker/config.json` *only if they contain credentials* |
| `file.vpn-config` | high | `*.ovpn` |
| `file.tfstate` | high | `*.tfstate`, `*.tfstate.backup` |
| `file.browser-logins` | high | Chromium `Login Data`, Firefox `logins.json` / `key4.db` (checked by name only, never opened) |
| `file.db-dump` | medium | `*.sql`, `*.sql.gz`, `*.dump` *with a dump-tool signature* (pg_dump, mysqldump, sqlite `.dump`, phpMyAdmin) |
| `file.backup` | medium | `*.bak`, `*.backup`, archives named like `*backup*`, `*bkp*`, `*dump*` |

`*.pem` and `*.key` files are judged by their **content** (`secret.private-key`),
so certificate bundles such as `cacert.pem` are not flagged.

**2. Secrets inside text files**

| rule | severity | what |
|------|----------|------|
| `secret.private-key` | critical | `-----BEGIN … PRIVATE KEY-----` followed by key material. Downgraded to high when the key is passphrase-protected (legacy `Proc-Type: 4,ENCRYPTED`, PKCS#8 `ENCRYPTED`, or an OpenSSH key whose cipher isn't `none`). |
| `secret.aws-key` | critical | `AKIA…` / `ASIA…` access key ids |
| `secret.github-token` | critical | `ghp_`, `gho_`, `ghu_`, `ghs_`, `ghr_`, `github_pat_` |
| `secret.gitlab-token` | critical | `glpat-…` |
| `secret.google-api-key` | high | `AIza…` |
| `secret.slack-token` | high | `xoxb-` / `xoxp-` … tokens, `hooks.slack.com` webhooks |
| `secret.stripe-key` | critical | `sk_live_` / `rk_live_` |
| `secret.ai-api-key` | critical | `sk-ant-…`, `sk-proj-…` |
| `secret.jwt` | medium | `eyJ….eyJ….…` |
| `secret.url-credentials` | high | `scheme://user:password@host` |
| `secret.assignment` | high | `password=`, `secret:`, `api_key =`, `DB_PASSWORD=`, `"client_secret": "…"` … |
| `secret.high-entropy` | medium | a random-looking string of 20+ chars right after `=`, `:` or a quote (Shannon entropy ≥ 4.5 bits/char, mixed case and digits) |
| `secret.seed-phrase` | high | 12/15/18/21/24 lowercase words that look like a BIP-39 mnemonic |

**3. Permissions** (POSIX only, skipped on Windows)

| rule | severity | what |
|------|----------|------|
| `perm.private-key` | high | a key or wallet file with `mode & 0o077` (group/others have access) |
| `perm.credentials` | medium | a `.env`, credential store, tfstate, … with `mode & 0o077` |
| `perm.world-writable` | medium | a world-writable config or dot-file (`mode & 0o002`) |

**4. Shell / REPL history**

| rule | severity | what |
|------|----------|------|
| `history.secret` | high+ | any secret above found in `.bash_history`, `.zsh_history`, fish, PowerShell `ConsoleHost_history.txt`, `.python_history`, `.mysql_history`, `.psql_history`, … plus command-line passwords such as `mysql -pSECRET`, `sshpass -p`, `curl -u user:pass` and `--password VALUE` |

**5. Unencrypted PII** (heuristics, validated wherever a checksum exists)

| rule | severity | what |
|------|----------|------|
| `pii.credit-card` | medium | 13–19 digits in 4-digit groups, a known card prefix, Luhn-valid |
| `pii.iban` | medium | IBAN, mod-97 validated |
| `pii.pesel` | low | Polish PESEL, checksum and encoded birth date validated |
| `pii.ssn` | low | `AAA-GG-SSSS` numbers (excluding the invalid 000 / 666 / 9xx areas) |
| `pii.credential-dump` | medium | 3+ lines of `email:password` (or `;` / `\|`) |

Each PII rule is reported once per file, at the first hit, with a count.

**6. Metadata leaks**

| rule | severity | what |
|------|----------|------|
| `meta.gps-exif` | medium | JPEG with GPS coordinates. EXIF is parsed by hand with `struct`, and only a ~11 km-coarse position is shown. |
| `meta.doc-author` | low | author in `.docx/.xlsx/.pptx` (`docProps/core.xml`), `.odt/.ods/.odp` (`meta.xml`) or the PDF `/Author` field (masked) |

## Limitations and false positives

drop is a quick local triage tool, not a forensic scanner. Known gaps:

- **Heuristics are heuristics.** PII, entropy and seed-phrase findings are
  labelled as such, and some tuning cost recall:
  - Seed phrases are only found as one line of 12–24 words. The words must
    look random: distinct, every word with a vowel, not in alphabetical order.
  - Card numbers must use 4-digit groups and must not sit inside a longer
    run of numbers.
  - Pure hex strings (commit ids, checksums) are never reported as
    high-entropy.
  - In source code (`.py`, `.js`, `.go`, …) only *quoted* literals count as
    hard-coded passwords, so `password = request.form["pw"]` is fine.
  - Values that look like placeholders or identifiers are ignored:
    `${VAR}`, `{{ x }}`, `changeme`, `your-key-here`, `access_token`,
    `no-such-flag`.
- **What it does not read:**
  - the inside of archives, compressed PDF streams, Office body text, and
    image formats other than JPEG (HEIC and PNG metadata are not parsed)
  - files larger than `--max-size`: those still get filename and
    permission checks, just no content scan
  - git history (`.git/objects` is skipped). Use a git-history secret
    scanner for that.
- **Permissions:** on WSL `/mnt/c` and some FUSE/Android mounts every file
  shows as `0777`, so `perm.*` findings there are noise. Use
  `--exclude` or `--min-severity`.
- **Encoding:** files are decoded as UTF-8 (UTF-16 with a BOM is
  recognised) with `errors="replace"`, and binary files (a NUL byte in the
  first 8 KB) are skipped. A file that can't be read is counted as
  "unreadable" and never stops the scan.
- **Found a false positive?** Add the path to `.dropignore`, raise
  `--min-severity`, or open an issue with a *fake* sample.

Measured on this repository and on a stock Linux `/etc`, `/usr/share`
(19k files) and the CPython standard library: this repo scans clean, and
the three system trees together produce about a dozen findings, several of
them real (a sample TLS key, a `.pfx` template, a published IBAN).

## Tests

```bash
cd tools/drop
python3 -m unittest -v test_drop
```

The tests are pure `unittest`. They cover the Luhn, IBAN and PESEL
validators, the entropy function, redaction, every rule family, EXIF
parsing, Office/PDF metadata, permissions, `.dropignore`, symlinks, exit
codes, and a check that no raw secret ever reaches the JSON. All fake
secrets are assembled at runtime from obviously fake fragments, so the test
file never contains a real-looking credential.

## License

MIT, same as the rest of Inpriv Labs.
