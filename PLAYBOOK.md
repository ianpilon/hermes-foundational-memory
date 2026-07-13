# Foundational Memory — Install Playbook (per Mac mini)

Repeatable procedure to put the **foundational memory** architecture on a fresh Hermes
instance. Copy this whole folder to the new mini and run one script.

Bundle contents:
- `install.sh` — idempotent installer (does everything below).
- `verify.py` — drives the real qwen sidecar end-to-end.
- `plugins/foundational/` — the exact working provider code (`__init__.py`, `plugin.yaml`, `README.md`).
- `profile.seed.md` — the L4 self-model seed.

---

## Part 0 — Prerequisites (base Hermes, done per your existing setup)

This playbook installs **memory only**. It assumes the mini already has a working Hermes:
- `hermes` CLI on PATH, and the agent at `~/.hermes/hermes-agent/` (venv inside).
- `HERMES_HOME` = `~/.hermes` (or wherever you point it).
- **Ollama running** with the memory-role model. Default `qwen2.5:7b` (installer pulls it if missing).
- Your action brain configured (DeepSeek cloud in this fleet — unaffected by memory).

If the base isn't up yet, stand it up first per your own fleet runbook
(model config, Twilio/SMS, cloudflared tunnel, launchd) — this playbook covers the memory layer only.

> **Transport note (per new mini):** memory is independent of how you reach the agent. But a
> NEW mini that should receive SMS needs its OWN public entry point — a distinct cloudflared
> hostname → its gateway:8080 — and SMS routing works one-number → one-webhook, so multiple
> minis can't share a single Twilio number simultaneously. That's a base-Hermes concern, not a
> memory one. This playbook does not touch it.

---

## Part 1 — Install (the one command)

```bash
# copy this folder to the new mini (USB, scp, git — your call), then:
cd foundational-memory-install
chmod +x install.sh
./install.sh
```

Override defaults if needed:
```bash
HERMES_HOME=~/.hermes-b MEM_MODEL=qwen2.5:7b CYCLE=6 ./install.sh
```

**What `install.sh` does (idempotent — safe to re-run):**
1. Checks `HERMES_HOME`, finds the venv python.
2. Ensures Ollama is up and the memory-role model is pulled.
3. Copies `plugins/foundational/` into `$HERMES_HOME/plugins/`.
4. Seeds `foundational_memory/profile.md` with the L4 self-model **before first run**
   (so the provider doesn't write its empty stub).
5. Writes `$HERMES_HOME/foundational.json` (`memory_model`, `cycle_interval`).
6. Sets `memory.provider: foundational` via the real config API (safe merge; keeps the
   built-in MEMORY.md/USER.md baseline on — foundational is **additive**).
7. Verifies the plugin is discovered + loads (3 tools).
8. Restarts the gateway (if this instance runs one).

---

## Part 2 — Verify

**Files + config (fast):** the installer already runs discovery/load checks.

**Real sidecar (deep):**
```bash
HERMES_HOME=~/.hermes ~/.hermes/hermes-agent/venv/bin/python3 verify.py
```
Expect `PASS ✅` with ≥1 typed record, including an `[instruction]` extracted by qwen, plus
`Phase 2 — intervention: None (silence)`.

**Live over SMS/CLI:**
1. **Start a NEW session first** — text `/new` (or `/reset`). *Critical:* Hermes freezes a
   session's system prompt at creation, so an existing session won't show new memory/self-model.
2. Tell it a durable fact: *"always bill me on Fridays."*
3. `/new` again, then ask: *"when do you bill me?"* → it should recall via the typed bank.
4. Ask: *"what memory system do you run on and what's not built yet?"* → it should describe
   L1/L2 + the qwen sidecar as live and name L3/L4/trained-policy as the frontier.

---

## Part 3 — Rollback

```bash
# revert to built-in memory:
#   edit $HERMES_HOME/config.yaml -> memory.provider: ''
# then:
hermes gateway restart
```
The built-in MEMORY.md/USER.md were never disabled, so rollback is clean. To fully remove:
`rm -rf $HERMES_HOME/plugins/foundational $HERMES_HOME/foundational_memory $HERMES_HOME/foundational.json`.

---

## Part 4 — Live viewer (optional)

A browser dashboard that shows the bank live: the construction funnel, typed records with
provenance, the self-model, and the **decision-log timeline** (every memory cycle, spoke vs
silent). A tiny always-on control server serves it on-demand behind a Start/Stop, password-protected.

**Install (local, always-on control):**
```bash
cd viewer && chmod +x install-viewer.sh && ./install-viewer.sh
```
This copies `app.py`/`app.html` to `$HERMES_HOME/viewer/`, writes + loads the `com.hermes.fmviewer`
LaunchAgent (RunAtLoad + KeepAlive), and prints the local URL + password location.

- **Local URL:** `http://127.0.0.1:8748/memory/`
- **Password:** `cat $HERMES_HOME/.fm_token` (auto-generated, 32-char; username = anything)
- Starts **stopped**; press **Start** to serve the bank, **Stop** to stop serving it (data is not
  served while stopped, even to an authed client).

**Remote access (per-machine, manual — needs your cloudflared tunnel):**
Serve it under a PATH on your already-working host so you don't fight any Cloudflare apex redirect.
In `~/.cloudflared/config.yml`, add — ABOVE your main host rule:
```yaml
ingress:
  - hostname: <your-host>          # e.g. hermes.voiceclaw.ca
    path: ^/memory
    service: http://localhost:8748
  - hostname: <your-host>          # your existing gateway rule
    service: http://localhost:8080
  - service: http_status:404
```
Then restart cloudflared: `launchctl kickstart -k gui/$(id -u)/com.hermes.cloudflared`.
Reachable at `https://<your-host>/memory/` (Basic Auth over the tunnel's HTTPS).
> A dedicated `memory.<domain>` subdomain also works IF your Cloudflare account has no
> apex/forwarding Page Rule catching it — the path-on-working-host route avoids that entirely.

**Uninstall the viewer:** `launchctl bootout gui/$(id -u)/com.hermes.fmviewer && rm ~/Library/LaunchAgents/com.hermes.fmviewer.plist`, remove the cloudflared path rule, and restart cloudflared.

---

## What you get (architecture recap)

Memory = a construction process, not a store. Bank at `$HERMES_HOME/foundational_memory/`:
- **L1** `raw.jsonl` — append-only transcript.
- **L2** `records.jsonl` — TYPED records (`fact|instruction|preference|event|procedure`) + provenance→L1 + salience.
- **Phase 1 sidecar** — `qwen2.5:7b` curates the bank every `cycle_interval` turns (background; also on session end).
- **Phase 2** — at most one silence-aware reminder via `prefetch()`; `null` = silence (default).
- Tools: `memory_save`, `memory_search`, `memory_recent`.
- **Frontier / not built:** L3 topic tracks, L4 self-model auto-evolution, trained navigation/intervention policy.

---

## Fleet tips (5 minis)

- **Same variable, every box:** this bundle is the constant. Only `HERMES_HOME`, `MEM_MODEL`,
  `CYCLE` change per box (via env vars).
- **Version the bundle:** if you tweak the provider, bump `plugin.yaml` `version:` and re-copy —
  `install.sh` overwrites the plugin dir, so re-running upgrades in place.
- **A/B box:** to keep one mini on DEFAULT memory as a control, just don't run this on it
  (or roll back Part 3). Everything else identical → clean comparison.
- **Clean baseline:** on a mini that inherited another's state, wipe before testing:
  `rm -f $HERMES_HOME/state.db* $HERMES_HOME/memories/MEMORY.md $HERMES_HOME/memories/USER.md $HERMES_HOME/foundational_memory/*.jsonl`
