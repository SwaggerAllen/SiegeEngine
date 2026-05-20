#!/usr/bin/env bash
# siege-bootstrap.sh — set up SiegeEngine plugin content in the current project repo.
#
# Run from inside the project repo you want to drive with SiegeEngine
# from mobile Claude Code (where `/plugin install` doesn't work).
#
# Usage:
#   # via curl (recommended — Claude can run this for you):
#   curl -fsSL https://siege.strutco.io/bootstrap.sh | bash
#
#   # or with options:
#   curl -fsSL https://siege.strutco.io/bootstrap.sh | \
#     bash -s -- --mcp-url https://siege.strutco.io/siege_mcp/mcp
#
#   # or from a local checkout of siegeengine:
#   /path/to/siegeengine/scripts/siege-bootstrap.sh
#
# What it does:
#   1. Verifies we're in a git repo.
#   2. Writes `.mcp.json` with the MCP server URL + a $SIEGE_TOKEN
#      placeholder Claude Code will substitute from the env at request
#      time.
#   3. Fetches `.claude-plugin/commands/` and `.claude-plugin/skills/`
#      from the SiegeEngine repo and copies them into this repo as
#      `.claude/commands/` and `.claude/skills/` (the on-disk paths
#      mobile CC auto-discovers).
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
MCP_URL="${MCP_URL:-https://siege.strutco.io/siege_mcp/mcp}"
DRY_RUN=0
VERBOSE=0

# ---------------- args ----------------

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mcp-url)
      MCP_URL="$2"; shift 2 ;;
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
command -v git  >/dev/null || die "git not found on PATH."
command -v curl >/dev/null || die "curl not found on PATH."

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

# ---------------- write .mcp.json ----------------

MCP_JSON='{
  "mcpServers": {
    "siegeengine": {
      "url": "'"$MCP_URL"'",
      "transport": "http",
      "headers": {
        "Authorization": "Bearer ${SIEGE_TOKEN}"
      }
    }
  }
}
'

if (( DRY_RUN )); then
  log "would write .mcp.json (mcp_url=$MCP_URL, bearer=\$SIEGE_TOKEN)"
else
  if [[ -f .mcp.json ]] && ! grep -q '"siegeengine"' .mcp.json; then
    warn ".mcp.json exists and doesn't have a siegeengine entry — leaving it alone."
    warn "merge this snippet by hand:"
    echo "$MCP_JSON" >&2
  else
    echo "$MCP_JSON" > .mcp.json
    log "wrote .mcp.json (auth via \$SIEGE_TOKEN env var)"
  fi
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

This repo has SiegeEngine wired up. The `.mcp.json` connects to the
hosted MCP server; `.claude/commands/` and `.claude/skills/` ship the
slash commands and skills locally so mobile Claude Code can use them
without `/plugin install`.

**One-time setup**: export a SiegeEngine JWT in your shell env so the
MCP server accepts your requests:

```bash
export SIEGE_TOKEN=<your token from siege.strutco.io>
```

**Common commands**:

- `/scaffold` — bootstrap features → requirements → sysarch
- `/run_tier <tier>` — draft + review every absent scope at a tier
- `/mint_plan` — materialize the impl-tier phasing plan
- `/run_phase <n>` — build one phase's impl + fan-in slice
- `/regen_below <tier> <threshold>` — regen scopes below a score
- `/continue <batch_id>` — resume an interrupted batch
- `/status` — per-tier snapshot

Full cheat sheet: `https://siege.strutco.io/cheatsheet`. Source of
truth for the commands/skills lives at `swaggerallen/siegeengine`;
re-run `scripts/siege-bootstrap.sh` (or `curl …/bootstrap.sh | bash`)
to pull the latest.

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
  1. Export your JWT (one-time per shell, or add to ~/.bashrc / ~/.zshrc):
       export SIEGE_TOKEN=<get yours from siege.strutco.io>

  2. Review the staged changes:
       git status
       git diff

  3. Commit + push when ready:
       git add .mcp.json .claude/ CLAUDE.md
       git commit -m "wire up SiegeEngine (mobile-CC friendly)"
       git push

  4. Open this repo in mobile Claude Code. The MCP tools, slash
     commands, and skills will be available without /plugin install.

  5. Cheat sheet: https://siege.strutco.io/cheatsheet
EOM
