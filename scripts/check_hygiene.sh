#!/usr/bin/env bash
#
# Working-tree hygiene checks. Runs in CI and as a pre-commit hook.
#
# Every check here corresponds to something that reached a Huang Lab repo and had
# to be cleaned up afterward. Cleaning up before the commit is free; cleaning up
# after means rewriting history.
#
# Usage:
#   ./scripts/check_hygiene.sh          # all tracked files
#   ./scripts/check_hygiene.sh a.py b.R # specific files (pre-commit passes these)
#
# Add allowed exceptions, one path or grep pattern per line, to .hygieneignore

set -uo pipefail

FAIL=0
MAX_BYTES=$((5 * 1024 * 1024))

red()  { printf '\033[31m%s\033[0m\n' "$1"; }
warn() { printf '\033[33m%s\033[0m\n' "$1"; }
ok()   { printf '\033[32m%s\033[0m\n' "$1"; }

fail() {
    red "FAIL: $1"
    shift
    for line in "$@"; do printf '  %s\n' "$line"; done
    FAIL=1
}

allowed() {
    [ -f .hygieneignore ] || return 1
    grep -qFx -- "$1" .hygieneignore 2>/dev/null
}

if [ "$#" -gt 0 ]; then
    FILES=$(printf '%s\n' "$@")
else
    FILES=$(git ls-files)
fi

[ -n "$FILES" ] || { ok "No tracked files to check."; exit 0; }

# ---------------------------------------------------------------------------
# 1. Filenames that should never be committed.
#    A file named tmp.R was committed to ProstateCancerRecurrence with hardcoded
#    OneDrive paths. If a file is worth committing, it is worth naming.
# ---------------------------------------------------------------------------
BAD_NAMES=$(printf '%s\n' "$FILES" | grep -E '(^|/)(\.DS_Store|\.Rhistory|\.RData|\.Ruserdata|Thumbs\.db|desktop\.ini|tmp\.[^/]+|temp\.[^/]+|scratch\.[^/]+|Untitled[^/]*|.*\.bak|.*\.orig|.*~)$' || true)
if [ -n "$BAD_NAMES" ]; then
    # shellcheck disable=SC2086
    fail "Files that should not be tracked (add to .gitignore, git rm --cached):" $BAD_NAMES
fi

# ---------------------------------------------------------------------------
# 2. Shell metacharacters and spaces in paths.
#    Four directories in ProstateCancerRecurrence contain a literal '|', which
#    breaks any unquoted script that references them and which some tools will
#    not create at all.
# ---------------------------------------------------------------------------
BAD_CHARS=$(printf '%s\n' "$FILES" | grep -E '[|<>*?$";'"'"'!&()`: ]' || true)
if [ -n "$BAD_CHARS" ]; then
    fail "Paths containing spaces or shell metacharacters - rename them:" "$BAD_CHARS"
fi

# ---------------------------------------------------------------------------
# 3. Large files. Git stores every version forever.
# ---------------------------------------------------------------------------
BIG=""
while IFS= read -r f; do
    [ -f "$f" ] || continue
    allowed "$f" && continue
    size=$(wc -c <"$f" | tr -d ' ')
    if [ "$size" -gt "$MAX_BYTES" ]; then
        BIG="$BIG$f ($((size / 1024 / 1024)) MB)
"
    fi
done <<EOF
$FILES
EOF
if [ -n "$BIG" ]; then
    fail "Files over 5 MB. Data does not belong in git - see data/README.md:" "$BIG"
fi

# ---------------------------------------------------------------------------
# 4. Private keys and obvious secrets.
#
#    Until now this checked for PEM private-key headers and nothing else, which
#    left the commonest leak - a password typed straight into a config file -
#    with no gate at all. `scan_history.sh` nominally covered it, but that runs
#    by hand and only reaches history under `--full`. One such credential sat in
#    a public lab repo for 665 days.
#
#    So: this is the pre-commit and CI gate, and it now looks for a quoted
#    literal assigned to a secret-ish name, a .env-style line with a literal
#    value, and credentials embedded in a URL.
#
#    Patterns are POSIX ERE. `\s` is a PCRE extension that POSIX reads as a
#    literal `s`, silently - which is exactly how the old rule in
#    scan_history.sh matched `password:"x"` while missing `password: "x"`. Use
#    [[:space:]].
# ---------------------------------------------------------------------------
KEYS=""
while IFS= read -r f; do
    [ -f "$f" ] || continue
    allowed "$f" && continue
    if grep -lqE 'BEGIN (RSA|OPENSSH|DSA|EC|PGP) PRIVATE KEY' "$f" 2>/dev/null; then
        KEYS="$KEYS$f
"
    fi
done <<EOF
$FILES
EOF
if [ -n "$KEYS" ]; then
    fail "Private key material:" "$KEYS"
fi

SECRET_RE='(password|passwd|secret|api[_-]?key|access[_-]?token|auth[_-]?token)[[:space:]]*[=:][[:space:]]*["'"'"'][^"'"'"']'
ENVLINE_RE='^[A-Z_]*(PASSWORD|PASSWD|SECRET|TOKEN|API_?KEY)[A-Z_]*=[^[:space:]$#{]'
URLCRED_RE='://[^/[:space:]:@]+:[^/[:space:]@]+@'
SECRETS=""
while IFS= read -r f; do
    [ -f "$f" ] || continue
    allowed "$f" && continue
    # An example file is meant to name the variables; its values are empty or
    # placeholders. Excluded by name so nobody has to add each one to
    # .hygieneignore. The two scanners are excluded because they contain the
    # patterns themselves - scan_history.sh already excludes both from its own
    # content scan for the same reason.
    case "$f" in
        scripts/check_hygiene.sh|scripts/scan_history.sh) continue ;;
        *.example|*.example.*|*.sample|*.template|*.md|*.rst) continue ;;
    esac
    hit=$(grep -nEm1 "$SECRET_RE|$ENVLINE_RE|$URLCRED_RE" "$f" 2>/dev/null || true)
    if [ -n "$hit" ]; then
        # Report the file and line, never the value.
        SECRETS="$SECRETS$f:${hit%%:*}
"
    fi
done <<EOF
$FILES
EOF
if [ -n "$SECRETS" ]; then
    fail "Hardcoded credential (file:line; value withheld). Read it from the environment and commit a .example instead:" "$SECRETS"
fi

# ---------------------------------------------------------------------------
# 5. Absolute machine-local paths in code.
#    Checked in code only - docs legitimately quote paths as examples.
#    A path under /Users or /home is unrunnable on any other machine and leaks
#    the author's local layout.
# ---------------------------------------------------------------------------
CODE=$(printf '%s\n' "$FILES" | grep -E '\.(py|R|r|rs|sh|bash|zsh|ipynb|ya?ml|toml|json|nf|config)$' | grep -v '^scripts/' || true)
PATHS=""
if [ -n "$CODE" ]; then
    while IFS= read -r f; do
        [ -f "$f" ] || continue
        allowed "$f" && continue
        hits=$(grep -nE '(/Users/|/home/[a-z0-9_-]+/|C:\\\\Users\\\\)' "$f" 2>/dev/null | head -3 || true)
        if [ -n "$hits" ]; then
            PATHS="$PATHS$f: $hits
"
        fi
    done <<EOF
$CODE
EOF
fi
if [ -n "$PATHS" ]; then
    fail "Hardcoded machine-local paths - parameterize or move to a config file:" "$PATHS"
fi

# ---------------------------------------------------------------------------
# 6. Unanchored directory patterns in .gitignore.
#    A bare `tests/` matches at ANY depth. In fastVEP it silently hid four
#    integration test files under crates/*/tests/ from every fresh clone, while
#    CI was separately running --lib and skipping them. Two invisible failures
#    compounding. Anchor patterns you mean literally: /data/, not data/.
# ---------------------------------------------------------------------------
if [ -f .gitignore ]; then
    UNANCHORED=$(grep -nE '^(tests?|data|results|src|R|crates|docs|scripts|bin|lib|include)/$' .gitignore || true)
    if [ -n "$UNANCHORED" ]; then
        fail ".gitignore has unanchored directory patterns that match at any depth (use a leading slash):" "$UNANCHORED"
    fi
fi

# ---------------------------------------------------------------------------
# 7. Notebooks with output cells. Output makes diffs unreviewable and can
#    contain participant-level values.
# ---------------------------------------------------------------------------
NB=$(printf '%s\n' "$FILES" | grep -E '\.ipynb$' || true)
NB_WITH_OUTPUT=""
if [ -n "$NB" ]; then
    while IFS= read -r f; do
        [ -f "$f" ] || continue
        allowed "$f" && continue
        if grep -q '"output_type"' "$f" 2>/dev/null; then
            NB_WITH_OUTPUT="$NB_WITH_OUTPUT$f
"
        fi
    done <<EOF
$NB
EOF
fi
if [ -n "$NB_WITH_OUTPUT" ]; then
    warn "WARN: notebooks with stored output (nbstripout, or build them from builders/*.py):"
    printf '%s' "$NB_WITH_OUTPUT"
fi

if [ "$FAIL" -eq 0 ]; then
    ok "Hygiene checks passed."
else
    red "Hygiene checks failed. See CONVENTIONS.md for the reasoning behind each rule."
fi
exit "$FAIL"
