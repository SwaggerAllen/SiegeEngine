#!/usr/bin/env bash
# siege-bootstrap.sh — set up SiegeEngine plugin content in the current project repo.
#
# Run from inside the project repo you want to drive with SiegeEngine
# in an environment where `/plugin install` isn't available.
#
# Usage:
#   # from a local checkout of siegeengine:
#   /path/to/siegeengine/siege-engine/scripts/siege-bootstrap.sh
#
#   # or fetched straight from GitHub:
#   curl -fsSL https://raw.githubusercontent.com/swaggerallen/siegeengine/main/siege-engine/scripts/siege-bootstrap.sh | bash
#
# What it does:
#   1. Verifies we're in a git repo.
#   2. pip-installs the `siege` CLI from the SiegeEngine repo (the
#      `[read]` extra — the skills run `python -m siege.cli` for both
#      reads and writes; there is no server in the generate loop).
#   3. Fetches `.claude-plugin/commands/`, `skills/`, and `agents/`
#      from the SiegeEngine repo and copies them into this repo as
#      `.claude/commands/`, `.claude/skills/`, `.claude/agents/` (the
#      on-disk paths Claude Code auto-discovers).
#   4. Appends a "Working with SiegeEngine" snippet to CLAUDE.md
#      (creates the file if absent) so the model sees the available
#      commands without /help.
#   5. Stages the changes for commit; does NOT commit or push (so you
#      review the diff first).
#
# Idempotent: safe to re-run. Overwrites the SiegeEngine-managed files
# with the latest from the repo; leaves your existing CLAUDE.md content
# alone except for the well-known section between sentinel markers.

set -euo pipefail

# ---------------- defaults ----------------

SIEGE_REPO_URL="${SIEGE_REPO_URL:-https://github.com/swaggerallen/siegeengine}"
SIEGE_REPO_REF="${SIEGE_REPO_REF:-main}"
DRY_RUN=0
VERBOSE=0

# ---------------- args ----------------

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo-url)
      SIEGE_REPO_URL="$2"; shift 2 ;;
    --repo-ref)
      SIEGE_REPO_REF="$2"; shift 2 ;;
    --dry-run)
      DRY_RUN=1; shift ;;
    --verbose)
      VERBOSE=1; shift ;;
    -h|--help)
      grep '^# ' "$0" | sed 's/^# //'
      exit 0 ;;
    *)
      echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

log() { printf '\033[1;34m[siege-bootstrap]\033[0m %s\n' "$*"; }
vlog() { (( VERBOSE )) && log "$@" || true; }
warn() { printf '\033[1;33m[siege-bootstrap warn]\033[0m %s\n' "$*" >&2; }
die() { printf '\033[1;31m[siege-bootstrap error]\033[0m %s\n' "$*" >&2; exit 1; }

# ---------------- preflight ----------------

[[ -d .git ]] || die "Not a git repo. cd into your project repo first."
command -v git >/dev/null || die "git not found on PATH."

PROJECT_ROOT="$(git rev-parse --show-toplevel)"
cd "$PROJECT_ROOT"
log "project root: $PROJECT_ROOT"

if (( DRY_RUN )); then
  warn "DRY RUN — no files will be written."
fi

# ---------------- fetch source ----------------

TMP_DIR="$(mktemp -d -t siege-bootstrap.XXXXXX)"
trap 'rm -rf "$TMP_DIR"' EXIT

log "fetching $SIEGE_REPO_URL@$SIEGE_REPO_REF"
git clone --quiet --depth 1 --branch "$SIEGE_REPO_REF" "$SIEGE_REPO_URL" "$TMP_DIR/siegeengine"

SRC_PLUGIN="$TMP_DIR/siegeengine/.claude-plugin"
[[ -d "$SRC_PLUGIN/commands" ]] || die "Source repo has no .claude-plugin/commands/ — wrong ref?"
[[ -d "$SRC_PLUGIN/skills"   ]] || die "Source repo has no .claude-plugin/skills/ — wrong ref?"

CMD_COUNT="$(find "$SRC_PLUGIN/commands" -maxdepth 1 -name '*.md' | wc -l | tr -d ' ')"
SKILL_COUNT="$(find "$SRC_PLUGIN/skills"  -mindepth 1 -maxdepth 1 -type d | wc -l | tr -d ' ')"
log "source has $CMD_COUNT commands + $SKILL_COUNT skills"

# ---------------- install the siege CLI ----------------
# The skills shell out to `python -m siege.cli` for every read (context
# bundles, state) and write (state JSON, ledgers, sha/nonce). Install
# from the repo we just cloned, with the `[read]` extra so the read
# subcommands' deps (pydantic, beautifulsoup4) come along.

SIEGE_PKG_DIR="$TMP_DIR/siegeengine/siege-engine"
GIT_INSTALL_HINT="pip install \"siege-engine[read] @ git+${SIEGE_REPO_URL}.git@${SIEGE_REPO_REF}#subdirectory=siege-engine\""

install_siege() {
  # Try, in order: `python3 -m pip`, `pip3`, `pip`; each plain first,
  # then with --user (covers PEP-668 externally-managed system pythons).
  local runner
  for runner in "python3 -m pip" "pip3" "pip"; do
    command -v "${runner%% *}" >/dev/null 2>&1 || continue
    if $runner install --quiet "${SIEGE_PKG_DIR}[read]" >/dev/null 2>&1 \
       || $runner install --quiet --user "${SIEGE_PKG_DIR}[read]" >/dev/null 2>&1; then
      return 0
    fi
  done
  return 1
}

if (( DRY_RUN )); then
  log "would pip-install the siege CLI ([read] extra) from $SIEGE_REPO_REF"
elif install_siege; then
  log "installed the siege CLI — \`python -m siege.cli\` is ready"
else
  warn "could not install the siege CLI (no working pip found)."
  warn "the skills need it — install it by hand:"
  warn "  $GIT_INSTALL_HINT"
fi

# ---------------- copy commands + skills ----------------

if (( DRY_RUN )); then
  log "would mirror $SRC_PLUGIN/{commands,skills} → .claude/"
else
  mkdir -p .claude/commands .claude/skills
  # rsync if available for nicer output, else cp -R
  if command -v rsync >/dev/null; then
    rsync -a --delete "$SRC_PLUGIN/commands/" .claude/commands/
    rsync -a --delete "$SRC_PLUGIN/skills/"   .claude/skills/
  else
    rm -rf .claude/commands .claude/skills
    mkdir -p .claude/commands .claude/skills
    cp -R "$SRC_PLUGIN/commands/." .claude/commands/
    cp -R "$SRC_PLUGIN/skills/."   .claude/skills/
  fi
  # Also bring over the per-tier subagents if present.
  if [[ -d "$SRC_PLUGIN/agents" ]]; then
    mkdir -p .claude/agents
    if command -v rsync >/dev/null; then
      rsync -a --delete "$SRC_PLUGIN/agents/" .claude/agents/
    else
      rm -rf .claude/agents && mkdir -p .claude/agents
      cp -R "$SRC_PLUGIN/agents/." .claude/agents/
    fi
  fi
  log "mirrored commands + skills + agents → .claude/"
fi

# ---------------- update CLAUDE.md (between sentinel markers) ----------------

START_MARKER="<!-- siege-bootstrap: BEGIN — do not edit by hand, re-run scripts/siege-bootstrap.sh -->"
END_MARKER="<!-- siege-bootstrap: END -->"
SNIPPET=$(cat <<'MD_EOF'

## Working with SiegeEngine

This repo has SiegeEngine wired up. The bootstrap `pip install`ed the
**`siege` CLI** (read + write) and mirrored `.claude/commands/` +
`.claude/skills/` so Claude Code can drive the build without
`/plugin install`. The skills run the CLI locally — there is no server
in the generate loop. If a skill reports `No module named siege`,
re-run `scripts/siege-bootstrap.sh`.

**Common commands**:

- `/scaffold` — bootstrap features → requirements → sysarch
- `/run_tier <tier>` — draft + review every pending scope at a tier
- `/mint_plan` — materialize the impl-tier phasing plan
- `/run_phase <n>` — build one phase's impl + fan-in slice
- `/regen_below <tier> <threshold>` — regen scopes below a score
- `/continue <batch_id>` — resume an interrupted batch
- `/status` — per-tier snapshot

Full cheat sheet: `https://siege.strutco.io/cheatsheet`. Source of
truth for the commands/skills lives at `swaggerallen/siegeengine`;
re-run `scripts/siege-bootstrap.sh` to pull the latest.

MD_EOF
)

if (( DRY_RUN )); then
  log "would write CLAUDE.md SiegeEngine section between sentinel markers"
else
  if [[ ! -f CLAUDE.md ]]; then
    {
      echo "# $(basename "$PROJECT_ROOT")"
      echo
      echo "$START_MARKER"
      echo "$SNIPPET"
      echo "$END_MARKER"
    } > CLAUDE.md
    log "created CLAUDE.md with SiegeEngine section"
  elif grep -qF "$START_MARKER" CLAUDE.md; then
    # Replace the existing block between markers with the new content.
    python3 - "$START_MARKER" "$END_MARKER" "$SNIPPET" <<'PY_EOF'
import pathlib, re, sys

start, end, snippet = sys.argv[1], sys.argv[2], sys.argv[3]
p = pathlib.Path("CLAUDE.md")
text = p.read_text(encoding="utf-8")
pattern = re.compile(
    re.escape(start) + r".*?" + re.escape(end),
    re.DOTALL,
)
new_block = f"{start}\n{snippet}\n{end}"
p.write_text(pattern.sub(new_block, text, count=1), encoding="utf-8")
PY_EOF
    log "refreshed SiegeEngine section in CLAUDE.md"
  else
    # No existing markers — append.
    {
      printf '\n%s\n%s\n%s\n' "$START_MARKER" "$SNIPPET" "$END_MARKER"
    } >> CLAUDE.md
    log "appended SiegeEngine section to CLAUDE.md"
  fi
fi

# ---------------- next steps ----------------

cat <<EOM

$(printf '\033[1;32m✓ SiegeEngine bootstrap complete\033[0m')

Next steps:
  1. Review the staged changes:
       git status
       git diff

  2. Commit + push when ready:
       git add .claude/ CLAUDE.md
       git commit -m "wire up SiegeEngine"
       git push

  3. Open this repo in Claude Code. The slash commands and skills are
     available without /plugin install.

  4. Cheat sheet: https://siege.strutco.io/cheatsheet
EOM
