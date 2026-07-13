#!/usr/bin/env bash
# Foundational Memory — installer for a Hermes instance.
# Idempotent: safe to re-run. Installs the provider, seeds the L4 self-model,
# flips memory.provider, verifies discovery, and restarts the gateway.
#
# Usage:
#   ./install.sh                      # uses HERMES_HOME=~/.hermes
#   HERMES_HOME=~/.hermes-b ./install.sh
#
# Assumes: a working Hermes instance (hermes CLI on PATH, hermes-agent venv),
# Ollama running, and the memory-role model available (default qwen2.5:7b).

set -euo pipefail
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
BUNDLE_DIR="$(cd "$(dirname "$0")" && pwd)"
MEM_MODEL="${MEM_MODEL:-qwen2.5:7b}"
CYCLE="${CYCLE:-6}"

say(){ printf '\033[1;36m==>\033[0m %s\n' "$*"; }
warn(){ printf '\033[1;33m[warn]\033[0m %s\n' "$*"; }
die(){ printf '\033[1;31m[fail]\033[0m %s\n' "$*" >&2; exit 1; }

# --- 0. sanity ---------------------------------------------------------------
say "HERMES_HOME = $HERMES_HOME"
[ -d "$HERMES_HOME" ] || die "HERMES_HOME not found. Install/boot Hermes first."
PY="$HERMES_HOME/hermes-agent/venv/bin/python3"
[ -x "$PY" ] || PY="$(command -v python3)" || die "no python3 found"
command -v hermes >/dev/null 2>&1 || warn "hermes CLI not on PATH (needed for gateway restart)."

# --- 1. dependency: Ollama + memory-role model -------------------------------
if curl -sf http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
  if ! curl -s http://127.0.0.1:11434/api/tags | grep -q "\"$MEM_MODEL\""; then
    say "pulling memory-role model $MEM_MODEL (first time only)…"
    ollama pull "$MEM_MODEL" || warn "could not pull $MEM_MODEL — pull it manually."
  else
    say "memory-role model $MEM_MODEL present."
  fi
else
  warn "Ollama not reachable on :11434 — the Phase-1 sidecar needs it. Start Ollama."
fi

# --- 2. install the plugin ---------------------------------------------------
say "installing provider -> $HERMES_HOME/plugins/foundational/"
mkdir -p "$HERMES_HOME/plugins/foundational"
cp -a "$BUNDLE_DIR/plugins/foundational/." "$HERMES_HOME/plugins/foundational/"

# --- 3. seed the L4 self-model BEFORE first run (so provider won't stub it) ---
mkdir -p "$HERMES_HOME/foundational_memory/tracks"
if [ ! -s "$HERMES_HOME/foundational_memory/profile.md" ] || grep -q "L4 — stub" "$HERMES_HOME/foundational_memory/profile.md" 2>/dev/null; then
  say "seeding L4 self-model (profile.md)"
  cp -a "$BUNDLE_DIR/profile.seed.md" "$HERMES_HOME/foundational_memory/profile.md"
else
  say "profile.md already seeded — leaving as-is."
fi

# --- 4. optional per-instance config -----------------------------------------
cat > "$HERMES_HOME/foundational.json" <<JSON
{
  "memory_model": "$MEM_MODEL",
  "cycle_interval": $CYCLE
}
JSON
say "wrote foundational.json (memory_model=$MEM_MODEL, cycle_interval=$CYCLE)"

# --- 5. flip memory.provider via the real config API (safe merge) ------------
say "setting memory.provider = foundational"
HERMES_HOME="$HERMES_HOME" "$PY" - <<'PYCFG'
import os, sys
sys.path.insert(0, os.path.join(os.environ["HERMES_HOME"], "hermes-agent"))
from hermes_cli.config import load_config, save_config
cfg = load_config()
cfg.setdefault("memory", {})
cfg["memory"]["provider"] = "foundational"
# ensure built-in baseline stays on (foundational is additive)
cfg["memory"].setdefault("memory_enabled", True)
cfg["memory"].setdefault("user_profile_enabled", True)
save_config(cfg)
print("   memory.provider ->", load_config().get("memory", {}).get("provider"))
PYCFG

# --- 6. verify discovery + load ----------------------------------------------
say "verifying plugin discovery…"
HERMES_HOME="$HERMES_HOME" "$PY" - <<'PYVER'
import os, sys
sys.path.insert(0, os.path.join(os.environ["HERMES_HOME"], "hermes-agent"))
from plugins.memory import discover_memory_providers, load_memory_provider
names = [n for n,_,_ in discover_memory_providers()]
assert "foundational" in names, f"NOT discovered; saw {names}"
p = load_memory_provider("foundational")
assert p and p.name == "foundational", "load failed"
print("   discovered + loaded OK; tools:", [t["name"] for t in p.get_tool_schemas()])
PYVER

# --- 7. restart gateway (if this instance runs one) --------------------------
if command -v hermes >/dev/null 2>&1; then
  say "restarting gateway to load the provider…"
  hermes gateway restart >/dev/null 2>&1 || warn "gateway restart failed (start it manually if this instance uses SMS)."
  sleep 8
  hermes gateway status 2>&1 | sed -n '1,2p' || true
fi

say "DONE. Foundational memory installed on $HERMES_HOME."
echo "Next: start a NEW session (/new) before testing — Hermes freezes a session's system prompt at creation."
