# Foundational Memory (Hermes memory provider)

A worked implementation of the *Memory as Construction* spec
([hermes-foundational-memory](https://github.com/ianpilon/hermes-foundational-memory)).
Memory is a **construction process, not a store**: the primary act is *selective
intervention* — deciding whether remembered state should influence the next action,
**including the decision to stay silent.**

## Status: Phase 1 + Phase 2 live

Live now:
- **L1 raw transcript** — every turn appended to `foundational_memory/raw.jsonl` (never edited).
- **L2 typed records** — `foundational_memory/records.jsonl`, closed vocabulary
  (`fact | instruction | preference | event | procedure`) + provenance (`source_ids` → L1)
  + salience fields.
- **Navigation tools** (NapMem shape): `memory_save`, `memory_search`, `memory_recent`.
  Zero-dependency BM25-lite retrieval — no embeddings, no network.
- **Phase 1 — sidecar cycle:** every `cycle_interval` turns (default 6), a background thread
  invokes `qwen2.5:7b` (Ollama, forced JSON) to emit *constrained* bank edits — typed saves
  (deduped, with provenance), deletes, and a private status. A cursor tracks processed L1 turns.
  Also runs on `on_session_end`. Off the action-turn critical path.
- **Phase 2 — selective intervention:** the sidecar precomputes at most ONE targeted reminder
  (or `null`). `prefetch()` injects it **once**, then goes silent — no model call on the
  action turn. `null` = silence, the default.
- Guards: skips writes/cycle for non-primary contexts (cron/subagent); never crashes a turn
  on Ollama failure.

Stubbed (research frontier, per spec §7 — do not fake):
- **L3 topic tracks** / **L4 self-model** evolution.
- Trained navigation/intervention policy (spec's GRPO graduation target). Currently prompted.

## Files written under the bank
`raw.jsonl` (L1) · `records.jsonl` (L2) · `status.json` (private self-view) ·
`cursor.json` (L1 processed cursor) · `cycles.jsonl` (decision log — one entry per memory
cycle: outcome, what it saved, spoke-vs-silence + why, duration) · `tracks/` (L3 stub) ·
`profile.md` (L4 stub)

### `cycles.jsonl` entry shape
`{ id, ts, started, duration_ms, model, window:{from,to,turns},
   outcome: committed|model_unreachable|unparseable,
   saved, saved_types[], deleted,
   decision: silent|intervened|null, reminder, reason, status }`
This is the feed the live viewer charts — the silences are only visible because they're recorded here.

The built-in `MEMORY.md` / `USER.md` baseline stays active underneath — this provider is additive.

## Storage
`$HERMES_HOME/foundational_memory/`
- `raw.jsonl` (L1) · `records.jsonl` (L2) · `tracks/` (L3, stub) · `profile.md` (L4, stub)

## Config
`$HERMES_HOME/foundational.json` (optional):
- `memory_model` — local memory-role model (default `qwen2.5:7b`)
- `cycle_interval` — run the memory cycle every N turns (default `6`)

## Activate / deactivate
Set `memory.provider: foundational` in `~/.hermes/config.yaml` (or via `hermes plugins`),
then restart the gateway. To revert: clear `memory.provider` and restart. Nothing here
removes the built-in baseline.
