"""Foundational Memory — MemoryProvider plugin.

A worked implementation of the *Memory as Construction* spec
(github.com/ianpilon/hermes-foundational-memory): memory is a construction
process, not a store. The primary act is *selective intervention* — deciding
whether remembered state should influence the next action, INCLUDING the
decision to stay silent.

Architecture (spec §1): a memory-agent SIDECAR on top of a typed bank. The
action agent (Hermes) is unmodified. A cheaper local model (qwen2.5:7b) runs
in a memory-management role every N turns — NOT every turn.

The pyramid (spec §2):
  L1  raw.jsonl      — append-only transcript, highest fidelity, never edited
  L2  records.jsonl  — compact TYPED records (closed vocab + provenance + salience)
  L3  tracks/*.md    — topic tracks (markdown)          [stub — spec §7]
  L4  profile.md     — co-emergent self-model (markdown) [stub — spec §7]

Two phases run inside one background sidecar invocation (spec §3/§4):
  Phase 1  constrained bank management — typed saves, deletes, private status.
  Phase 2  selective intervention — ONE targeted reminder, or NULL (silence).

prefetch() never calls a model: it injects the sidecar's precomputed reminder
ONCE, then stays silent. This keeps the action turn's latency untouched and
makes "do nothing" the default (spec §4: exposing more memory actively hurts).

Local + zero-dependency (stdlib only): BM25-lite retrieval, Ollama via urllib.
No network beyond localhost, no API keys.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent.memory_provider import MemoryProvider

logger = logging.getLogger(__name__)

# Closed type set (spec §2 L2). The model PICKS from this — it never invents types.
MEMORY_TYPES = ("fact", "instruction", "preference", "event", "procedure")

_BANK_DIRNAME = "foundational_memory"
_L1_RAW = "raw.jsonl"
_L2_RECORDS = "records.jsonl"
_L3_TRACKS = "tracks"
_L4_PROFILE = "profile.md"
_STATUS = "status.json"        # private memory-agent self-view (spec §3, never shown to action agent)
_CURSOR = "cursor.json"        # how many L1 lines the sidecar has already processed
_CYCLES = "cycles.jsonl"       # append-only DECISION LOG: one entry per memory cycle (spoke vs silence)
_SELF_FACTS = "self_facts.jsonl"        # candidate self-model facts (+ corroboration counts)
_SELFMODEL_LOG = "self_model_log.jsonl" # log of self-model passes (for the viewer)
_SM_STATE = "self_model_state.json"     # records-processed cursor for the self-model pass
_SM_BEGIN = "<!-- SELF-MODEL:AUTO:BEGIN -->"   # profile.md managed-block markers
_SM_END = "<!-- SELF-MODEL:AUTO:END -->"
_SM_PROMOTE_TIMES = 2          # promote a self-fact after it recurs across this many cycles
                               # (OR is corroborated by >= 2 distinct L2 records)

_OLLAMA_CHAT = "http://127.0.0.1:11434/api/chat"

# Only these record types can trigger a proactive reminder — the ones that plausibly
# change the NEXT decision (spec §4). Facts/events inform on demand via search instead.
_INTERVENE_TYPES = {"instruction", "preference", "procedure"}


def _err(msg: str) -> str:
    return json.dumps({"error": msg})


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _tokenize(text: str) -> List[str]:
    return re.findall(r"[a-z0-9]+", (text or "").lower())


def _norm(s: str) -> str:
    """Normalize a claim for dedup/reconciliation."""
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def _bm25_lite(query: str, docs: List[str]) -> List[float]:
    """Zero-dependency relevance: normalized query-term overlap (spec §8 default)."""
    q = set(_tokenize(query))
    if not q:
        return [0.0] * len(docs)
    out = []
    for d in docs:
        toks = _tokenize(d)
        if not toks:
            out.append(0.0)
            continue
        overlap = sum(1 for t in toks if t in q)
        out.append(overlap / (1.0 + 0.001 * len(toks)))
    return out


# ---------------------------------------------------------------------------
# Tool schemas — NapMem-shape navigation + a constrained save (spec §3/§5)
# ---------------------------------------------------------------------------

SAVE_SCHEMA = {
    "name": "memory_save",
    "description": (
        "Save a durable TYPED record to the foundational memory bank. Pick 'type' from "
        "the fixed vocabulary only. Use for facts, standing instructions, user preferences, "
        "notable events, or a procedure (an attempt + its outcome)."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "type": {"type": "string", "enum": list(MEMORY_TYPES)},
            "content": {"type": "string", "description": "A single natural-language statement."},
        },
        "required": ["type", "content"],
    },
}

SEARCH_SCHEMA = {
    "name": "memory_search",
    "description": (
        "Search the typed memory bank (L2) by meaning/keywords and STOP when you have enough "
        "evidence. Returns the most relevant records with their type and provenance."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "top_k": {"type": "integer", "description": "Max records (default 5, max 20)."},
        },
        "required": ["query"],
    },
}

RECENT_SCHEMA = {
    "name": "memory_recent",
    "description": "List the most recently saved typed records (L2).",
    "parameters": {
        "type": "object",
        "properties": {"limit": {"type": "integer", "description": "How many (default 10, max 50)."}},
        "required": [],
    },
}


# ---------------------------------------------------------------------------
# Sidecar prompt (Phase 1 + Phase 2 in one constrained JSON emission)
# ---------------------------------------------------------------------------

_SIDECAR_SYSTEM = (
    "You are the MEMORY MANAGER for an agent named Hermes. You never talk to the user and you "
    "never see this text surfaced to them. You read recent conversation turns plus the current "
    "memory bank, and you emit ONLY a JSON object describing edits to the bank and at most one "
    "intervention.\n\n"
    "Memory is a construction process, not a store. Record only DECISION-RELEVANT, DURABLE items. "
    "Skip small talk, transient details, and anything already captured.\n\n"
    "HIGHEST PRIORITY to capture — never drop these:\n"
    "- STANDING INSTRUCTIONS the user gives about how you must behave ('always/never do X', "
    "formatting rules, tone rules) -> type 'instruction'.\n"
    "- Stable PREFERENCES ('I like/prefer/hate X') -> type 'preference'.\n"
    "- An attempt and its OUTCOME ('I tried X and it fixed/broke Y') -> type 'procedure'.\n"
    "- The AGENT's OWN self-declared identity — when the assistant states its name or who it is "
    "('I'm Pal now', 'my name is X') -> type 'fact', phrased as the agent's identity "
    "(e.g. 'The agent's name is Pal'), NOT as a user preference.\n"
    "A single turn can yield multiple saves. Extract EACH durable item separately.\n\n"
    "Example: user says 'always text me in lowercase, no emojis' -> "
    '{"type":"instruction","content":"Always reply in lowercase with no emojis"}.\n\n'
    "Output EXACTLY this JSON shape (no prose, no markdown):\n"
    "{\n"
    '  "saves": [{"type": "fact|instruction|preference|event|procedure", "content": "one statement"}],\n'
    '  "deletes": ["record_id_to_invalidate"],\n'
    '  "status": "one private sentence: your view of progress / open risks",\n'
    '  "intervention": null OR {"reminder": "one short targeted reminder for the NEXT reply", "reason": "why it changes the next decision"}\n'
    "}\n\n"
    "RULES:\n"
    "- 'type' MUST be one of: fact, instruction, preference, event, procedure. Never invent a type.\n"
    "- 'procedure' = an attempt and its outcome (a command that failed, a fix that worked, a ruled-out hypothesis).\n"
    "- Intervene ONLY when a remembered item is likely to change the next decision: a requirement about "
    "to be violated, a fact explaining the current observation, a past failed attempt not to repeat, a "
    "neglected open subgoal, a still-relevant diagnosis. Otherwise set \"intervention\": null.\n"
    "- Prefer null. Do NOT intervene with broad strategy or restate what's already visible. Exposing more "
    "memory hurts. Silence is usually correct.\n"
    "- Empty arrays are fine. Return valid JSON and nothing else."
)

_SELFMODEL_SYSTEM = (
    "You maintain the SELF-MODEL of an agent named Pal. You never talk to the user and this is "
    "never surfaced to them. From the agent's DURABLE MEMORY RECORDS (which are already "
    "evidence-grounded), propose only STABLE, IDENTITY-relevant facts about who the agent is IN "
    "THIS RELATIONSHIP: how it should behave, what it has been told it is, standing commitments, "
    "its name.\n\n"
    "ANTI-CONFABULATION RULES (strict):\n"
    "- Every self-fact MUST cite in \"evidence\" the record id(s) it derives from. NO evidence -> do NOT propose it.\n"
    "- Only durable identity/relationship facts. NEVER a personality narrative, invented traits, moods, "
    "or backstory. If the records don't support it, it does not exist.\n"
    "- Write each as a short first-person statement beginning with \"I \".\n"
    "- Cite ALL record ids that support a claim, not just one — breadth of evidence is what earns trust.\n"
    "- Prefer proposing nothing. An empty list is the correct, common answer.\n\n"
    "Output EXACTLY this JSON (no prose):\n"
    '{ "self_facts": [ {"claim": "I ...", "evidence": ["record_id", ...], "confidence": 0.0-1.0} ] }'
)


class FoundationalMemoryProvider(MemoryProvider):
    """Typed bank + qwen sidecar + silence-aware intervention."""

    def __init__(self) -> None:
        self._home: Optional[Path] = None
        self._bank: Optional[Path] = None
        self._session_id = ""
        self._lock = threading.Lock()
        self._cycle_lock = threading.Lock()   # prevent overlapping sidecar runs
        self._memory_model = "qwen2.5:7b"
        self._cycle_interval = 6
        self._turn = 0
        self._primary = True                   # skip writes/cycle for cron/subagent contexts
        self._pending_intervention: Optional[str] = None
        self._cycle_thread: Optional[threading.Thread] = None
        self._self_model_enabled = True     # L4 evolution; disable via foundational.json

    @property
    def name(self) -> str:
        return "foundational"

    def is_available(self) -> bool:
        return True

    # -- lifecycle -----------------------------------------------------------

    def initialize(self, session_id: str, **kwargs) -> None:
        self._session_id = session_id or ""
        home = kwargs.get("hermes_home")
        self._home = Path(home) if home else Path.home() / ".hermes"
        self._bank = self._home / _BANK_DIRNAME
        ctx = kwargs.get("agent_context", "primary")
        self._primary = ctx in ("primary", "", None)

        # optional config override
        try:
            cfg_path = self._home / "foundational.json"
            if cfg_path.exists():
                cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
                self._memory_model = cfg.get("memory_model") or self._memory_model
                self._cycle_interval = int(cfg.get("cycle_interval") or self._cycle_interval)
                if "self_model_evolution" in cfg:
                    self._self_model_enabled = bool(cfg.get("self_model_evolution"))
        except Exception:
            pass

        try:
            self._bank.mkdir(parents=True, exist_ok=True)
            (self._bank / _L3_TRACKS).mkdir(exist_ok=True)
            for f in (_L1_RAW, _L2_RECORDS):
                p = self._bank / f
                if not p.exists():
                    p.touch()
            profile = self._bank / _L4_PROFILE
            if not profile.exists():
                profile.write_text(
                    "# Agent self-model (L4 — stub)\n\n"
                    "_Co-emergent self-model. Evolves; not 'solved'. Do not fake it._\n",
                    encoding="utf-8",
                )
        except Exception as e:
            logger.warning("foundational: bank init failed: %s", e)
        logger.info("foundational memory active — bank=%s model=%s cycle=%d ctx=%s",
                    self._bank, self._memory_model, self._cycle_interval, ctx)

    def system_prompt_block(self) -> str:
        block = (
            "# Foundational Memory (construction, not storage)\n"
            "You have a typed memory bank. Access is NAVIGATION, not a fixed pipeline: use "
            "`memory_search`/`memory_recent` and STOP when you have enough evidence. Use "
            "`memory_save` for a durable fact/instruction/preference/event/procedure — type is a "
            "fixed vocabulary, never invent one. A background memory process also curates this bank "
            "and may hand you a single relevant reminder; re-inflate what you recall against the "
            "current task and don't restate what's already visible."
        )
        # Surface the L4 self-model so the agent knows its own standing (spec §2 L4).
        selfmodel = self._read_self_model()
        if selfmodel:
            block += "\n\n" + selfmodel
        return block

    def _read_self_model(self, cap: int = 1800) -> str:
        """Return the L4 profile text, minus the placeholder stub, capped for the prompt."""
        if not self._bank:
            return ""
        try:
            text = (self._bank / _L4_PROFILE).read_text(encoding="utf-8").strip()
        except Exception:
            return ""
        # Skip the inert initial stub — only surface a real, seeded self-model.
        if not text or "L4 — stub" in text:
            return ""
        return text[:cap]

    # -- L1 write + Phase-1 trigger -----------------------------------------

    def sync_turn(self, user_content: str, assistant_content: str, *, session_id: str = "") -> None:
        if not self._bank or not self._primary:
            return
        sid = session_id or self._session_id
        ts = _now_iso()
        rows = [
            {"id": uuid.uuid4().hex, "role": "user", "content": user_content,
             "session_id": sid, "timestamp": ts},
            {"id": uuid.uuid4().hex, "role": "assistant", "content": assistant_content,
             "session_id": sid, "timestamp": ts},
        ]
        try:
            with self._lock, (self._bank / _L1_RAW).open("a", encoding="utf-8") as fh:
                for r in rows:
                    fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.debug("foundational: L1 append failed: %s", e)

        self._turn += 1
        if self._turn % max(1, self._cycle_interval) == 0:
            self._spawn_cycle()

    # -- Phase 2: intervention (precomputed by sidecar; injected ONCE) -------

    def prefetch(self, query: str, *, session_id: str = "") -> str:
        """Inject the sidecar's precomputed reminder once, then go silent.

        No model call on the action-turn critical path. `null` from the sidecar
        (the common case) means this returns "" — silence, the default.
        """
        with self._lock:
            reminder = self._pending_intervention
            self._pending_intervention = None
        if not reminder:
            return ""
        return f"## Memory — relevant reminder\n{reminder}"

    # -- Sidecar (Phase 1 + Phase 2) ----------------------------------------

    def _spawn_cycle(self) -> None:
        if self._cycle_thread and self._cycle_thread.is_alive():
            return
        self._cycle_thread = threading.Thread(
            target=self._run_memory_cycle, name="foundational-cycle", daemon=True)
        self._cycle_thread.start()

    def _run_memory_cycle(self) -> None:
        """Read new L1 turns + bank, ask qwen for constrained edits + one intervention.

        Every cycle is recorded to the DECISION LOG (cycles.jsonl) — including the
        outcome (committed / model_unreachable / unparseable) and, when committed,
        whether Phase 2 spoke or stayed silent. That log is what the live viewer
        charts: the silences are only visible because they're written down here.
        """
        if not self._bank or not self._primary:
            return
        if not self._cycle_lock.acquire(blocking=False):
            return
        started = time.monotonic()
        started_iso = _now_iso()
        try:
            new_lines, start_idx, end_idx = self._unprocessed_l1()
            if not new_lines:
                return
            recent = self._format_l1(new_lines)
            bank = self._format_bank_for_prompt()
            user_msg = (
                f"CURRENT MEMORY BANK (L2 records):\n{bank}\n\n"
                f"NEW CONVERSATION TURNS since last cycle:\n{recent}\n\n"
                "Emit the JSON now."
            )
            base = {
                "started": started_iso,
                "window": {"from": start_idx, "to": end_idx, "turns": len(new_lines)},
                "model": self._memory_model,
            }
            dur = lambda: int((time.monotonic() - started) * 1000)
            raw = self._call_memory_model(_SIDECAR_SYSTEM, user_msg)
            if raw is None:
                # model unreachable; leave cursor so we retry next cycle
                self._log_cycle({**base, "outcome": "model_unreachable",
                                 "decision": None, "duration_ms": dur()})
                return
            plan = self._parse_plan(raw)
            if plan is None:
                logger.debug("foundational: sidecar returned unparseable JSON; skipping")
                self._advance_cursor(end_idx)  # don't reprocess the same window forever
                self._log_cycle({**base, "outcome": "unparseable",
                                 "decision": None, "duration_ms": dur()})
                return
            src_ids = [json.loads(l).get("id") for l in new_lines if l.strip()]
            summary = self._apply_plan(plan, src_ids)
            self._advance_cursor(end_idx)
            self._log_cycle({**base, "outcome": "committed", "duration_ms": dur(), **summary})
            try:
                self._run_self_model_pass()   # L4 evolution — isolated, gated, never breaks the cycle
            except Exception as e:
                logger.debug("foundational: self-model pass failed: %s", e)
        except Exception as e:
            logger.debug("foundational: memory cycle failed: %s", e)
        finally:
            self._cycle_lock.release()

    def _log_cycle(self, entry: Dict[str, Any]) -> None:
        """Append one cycle event to the decision log (cycles.jsonl)."""
        if not self._bank:
            return
        try:
            row = {"id": uuid.uuid4().hex, "ts": _now_iso(), **entry}
            with self._lock, (self._bank / _CYCLES).open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.debug("foundational: cycle log write failed: %s", e)

    # -- L4 self-model evolution (grounded, conservative, drift-resistant) ----

    def _read_self_facts(self) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        try:
            with (self._bank / _SELF_FACTS).open(encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        try:
                            out.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue
        except FileNotFoundError:
            pass
        return out

    def _write_self_facts(self, facts: List[Dict[str, Any]]) -> None:
        try:
            with self._lock, (self._bank / _SELF_FACTS).open("w", encoding="utf-8") as fh:
                for f in facts:
                    fh.write(json.dumps(f, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.debug("foundational: write self_facts failed: %s", e)

    def _sm_records_seen(self) -> int:
        try:
            return int(json.loads((self._bank / _SM_STATE).read_text()).get("records_seen", 0))
        except Exception:
            return 0

    def _sm_set_records_seen(self, n: int) -> None:
        try:
            (self._bank / _SM_STATE).write_text(json.dumps({"records_seen": n}), encoding="utf-8")
        except Exception:
            pass

    def _run_self_model_pass(self) -> None:
        """Propose grounded self-model facts from L2 records; promote the corroborated ones.

        Discipline that defeats confabulation/drift:
          - Every proposed claim MUST cite real L2 record ids; ungrounded claims are rejected here,
            not by the model's goodwill.
          - Self-facts derive from L2 records (already evidence-backed) — never raw free text — so
            the chain to evidence is: self-fact -> L2 record -> L1 turn.
          - A claim is PROMOTED into the visible self-model only when corroborated: it recurs across
            >= _SM_PROMOTE_TIMES cycles, OR is backed by >= 2 distinct records.
          - It edits ONLY the marked block in profile.md; hand-written self-model text is untouched.
          - Runs only when new records exist (cheap) and never crashes the cycle.
        """
        if not (self._bank and self._primary and self._self_model_enabled):
            return
        records = self._read_records()
        if not records:
            return
        if len(records) <= self._sm_records_seen():
            return  # no new grounded material since last pass

        valid_ids = {r.get("id") for r in records}
        rec_lines = "\n".join(f"- id={r.get('id')} [{r.get('type')}] {r.get('content')}"
                              for r in records[-40:])
        current = "\n".join(f"- {f['claim']}" for f in self._read_self_facts()
                            if f.get("promoted")) or "(none yet)"
        user = (f"DURABLE MEMORY RECORDS (already evidence-grounded):\n{rec_lines}\n\n"
                f"CURRENT PROMOTED SELF-FACTS:\n{current}\n\nEmit the JSON now.")
        raw = self._call_memory_model(_SELFMODEL_SYSTEM, user)
        if raw is None:
            return
        plan = self._parse_plan(raw)
        if not isinstance(plan, dict):
            return

        # accept only grounded proposals (evidence must be REAL record ids)
        proposed = []
        for sf in (plan.get("self_facts") or []):
            if not isinstance(sf, dict):
                continue
            claim = str(sf.get("claim", "")).strip()
            ev = [e for e in (sf.get("evidence") or []) if e in valid_ids]
            if not claim or not ev:
                continue  # ungrounded -> reject by construction
            try:
                conf = float(sf.get("confidence", 0.5))
            except Exception:
                conf = 0.5
            proposed.append({"claim": claim, "evidence": ev, "confidence": conf})

        # reconcile into self_facts.jsonl (corroboration counting)
        facts = self._read_self_facts()
        by_norm = {_norm(f["claim"]): f for f in facts}
        for p in proposed:
            k = _norm(p["claim"])
            if k in by_norm:
                f = by_norm[k]
                f["times_seen"] = f.get("times_seen", 1) + 1
                f["last_seen"] = _now_iso()
                f["evidence"] = sorted(set(f.get("evidence", []) + p["evidence"]))[:8]
                f["confidence"] = max(f.get("confidence", 0.0), p["confidence"])
            else:
                nf = {"id": uuid.uuid4().hex, "claim": p["claim"], "evidence": p["evidence"][:8],
                      "confidence": p["confidence"], "times_seen": 1,
                      "first_seen": _now_iso(), "last_seen": _now_iso(), "promoted": False}
                facts.append(nf)
                by_norm[k] = nf

        # promotion: corroborated = recurred enough OR backed by >= 2 distinct records
        promoted = []
        for f in facts:
            corr = (f.get("times_seen", 1) >= _SM_PROMOTE_TIMES
                    or len(set(f.get("evidence", []))) >= 2)
            f["promoted"] = bool(corr)
            if f["promoted"]:
                promoted.append(f)

        self._write_self_facts(facts)
        self._render_self_model(promoted)
        self._sm_set_records_seen(len(records))
        self._log_self_model(len(proposed), len(promoted))
        if promoted:
            logger.info("foundational: self-model — %d promoted / %d proposed", len(promoted), len(proposed))

    def _render_self_model(self, promoted: List[Dict[str, Any]]) -> None:
        """Write promoted self-facts into profile.md's managed block; preserve everything else."""
        try:
            text = (self._bank / _L4_PROFILE).read_text(encoding="utf-8")
        except Exception:
            return
        if _SM_BEGIN not in text or _SM_END not in text:
            return  # no managed block -> never touch a hand-written file
        if promoted:
            body = "\n".join(
                f"- {f['claim']}  _(evidence: {', '.join(e[:8] for e in list(f.get('evidence', []))[:3])})_"
                for f in sorted(promoted, key=lambda x: -x.get("confidence", 0.0)))
        else:
            body = "_(nothing promoted yet — grounded self-facts will appear here as they recur)_"
        pre = text.split(_SM_BEGIN)[0]
        post = text.split(_SM_END, 1)[1]
        new = f"{pre}{_SM_BEGIN}\n{body}\n{_SM_END}{post}"
        try:
            (self._bank / _L4_PROFILE).write_text(new, encoding="utf-8")
        except Exception as e:
            logger.debug("foundational: render self-model failed: %s", e)

    def _log_self_model(self, proposed: int, promoted: int) -> None:
        try:
            row = {"id": uuid.uuid4().hex, "ts": _now_iso(), "kind": "self_model",
                   "proposed": proposed, "promoted": promoted}
            with self._lock, (self._bank / _SELFMODEL_LOG).open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def on_session_end(self, messages: List[Dict[str, Any]]) -> None:
        """Run a final cycle to capture the tail of the session (spec §7 Phase-1 target)."""
        try:
            self._run_memory_cycle()
        except Exception:
            pass

    # -- sidecar helpers -----------------------------------------------------

    def _call_memory_model(self, system: str, user: str) -> Optional[str]:
        """Call local Ollama with forced JSON output. Returns content or None on failure."""
        payload = {
            "model": self._memory_model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.2, "num_ctx": 8192},
        }
        try:
            req = urllib.request.Request(
                _OLLAMA_CHAT, data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=120) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            return (body.get("message") or {}).get("content", "")
        except Exception as e:
            logger.debug("foundational: memory model call failed: %s", e)
            return None

    @staticmethod
    def _parse_plan(raw: str) -> Optional[Dict[str, Any]]:
        try:
            plan = json.loads(raw)
        except json.JSONDecodeError:
            m = re.search(r"\{.*\}", raw, re.DOTALL)
            if not m:
                return None
            try:
                plan = json.loads(m.group(0))
            except json.JSONDecodeError:
                return None
        return plan if isinstance(plan, dict) else None

    def _apply_plan(self, plan: Dict[str, Any], source_ids: List[str]) -> Dict[str, Any]:
        """Apply the sidecar's plan; return a summary of what changed (for the decision log)."""
        summary: Dict[str, Any] = {
            "saved": 0, "saved_types": [], "deleted": 0,
            "decision": "silent", "reminder": None, "reason": None, "status": None,
        }

        # 1) forgetting (invalidation) — spec §3 memory_delete; scaffold-gated + observable.
        #    The proposer names ids AND a reason; the scaffold tombstones (never hard-drops),
        #    refuses evidence-cited records, and never touches L1. Reason + refusals flow into
        #    the cycle log so forgetting is as observable as silence (NOVELTY.md §3).
        del_ids = set(x for x in (plan.get("deletes") or []) if isinstance(x, str))
        if del_ids:
            reason = str(plan.get("delete_reason", "")).strip() or "sidecar plan (no reason given)"
            res = self._forget_records(del_ids, reason)
            summary["deleted"] = len(res["forgotten"])
            summary["forgotten_ids"] = res["forgotten"]
            summary["forget_refused"] = res["refused"]     # evidence-protected → surfaced, not silent
            summary["forget_reason"] = reason if res["forgotten"] else None

        # 2) saves — typed, deduped, with provenance
        existing = {r.get("content", "").strip().lower() for r in self._read_records()}
        new_records = []
        for s in (plan.get("saves") or []):
            if not isinstance(s, dict):
                continue
            rtype = str(s.get("type", "")).strip().lower()
            content = str(s.get("content", "")).strip()
            if rtype not in MEMORY_TYPES or not content:
                continue
            if content.lower() in existing:   # dedup (reconciliation, minimal form)
                continue
            existing.add(content.lower())
            new_records.append(self._make_record(rtype, content, source_ids))
        if new_records:
            self._append_records(new_records)
            summary["saved"] = len(new_records)
            summary["saved_types"] = [r["type"] for r in new_records]

        # 3) private status (self-model proto — NEVER shown to the action agent)
        status = plan.get("status")
        if isinstance(status, str) and status.strip():
            self._write_status(status.strip())
            summary["status"] = status.strip()

        # 4) Phase 2: queue at most one intervention (or stay silent)
        iv = plan.get("intervention")
        reminder = reason = None
        if isinstance(iv, dict):
            reminder = str(iv.get("reminder", "")).strip() or None
            reason = str(iv.get("reason", "")).strip() or None
        if reminder:
            with self._lock:
                self._pending_intervention = reminder
            summary.update(decision="intervened", reminder=reminder, reason=reason)
            logger.info("foundational: intervention queued: %s", reminder[:80])
        else:
            logger.debug("foundational: sidecar chose silence")
        return summary

    # -- L1 cursor / formatting ---------------------------------------------

    def _read_l1_lines(self) -> List[str]:
        try:
            with (self._bank / _L1_RAW).open("r", encoding="utf-8") as fh:
                return fh.readlines()
        except FileNotFoundError:
            return []

    def _cursor_value(self) -> int:
        try:
            return int(json.loads((self._bank / _CURSOR).read_text()).get("processed", 0))
        except Exception:
            return 0

    def _advance_cursor(self, idx: int) -> None:
        try:
            (self._bank / _CURSOR).write_text(json.dumps({"processed": idx}), encoding="utf-8")
        except Exception:
            pass

    def _unprocessed_l1(self):
        lines = self._read_l1_lines()
        start = self._cursor_value()
        if start > len(lines):
            start = 0
        window = lines[start:]
        # cap window to keep the sidecar prompt bounded
        MAX = 40
        if len(window) > MAX:
            window = window[-MAX:]
            start = len(lines) - MAX
        return window, start, len(lines)

    @staticmethod
    def _format_l1(lines: List[str]) -> str:
        out = []
        for l in lines:
            try:
                r = json.loads(l)
                out.append(f"[{r.get('role')}] {str(r.get('content',''))[:500]}")
            except Exception:
                continue
        return "\n".join(out) if out else "(none)"

    def _format_bank_for_prompt(self, limit: int = 40) -> str:
        recs = self._read_records()[-limit:]
        if not recs:
            return "(empty)"
        return "\n".join(f"- id={r.get('id')} [{r.get('type')}] {r.get('content')}" for r in recs)

    # -- L2 record I/O -------------------------------------------------------

    def _make_record(self, rtype: str, content: str, source_ids: List[str]) -> Dict[str, Any]:
        return {
            "id": uuid.uuid4().hex,
            "type": rtype,
            "content": content,
            "source_ids": [s for s in source_ids if s][:8],
            "created": _now_iso(),
            "last_accessed": _now_iso(),
            "valid_until": None,
            "access_count": 0,
            "salience": {"valence": 0.0, "arousal": 0.0},
        }

    def _read_records(self, include_forgotten: bool = False) -> List[Dict[str, Any]]:
        if not self._bank:
            return []
        out: List[Dict[str, Any]] = []
        try:
            with (self._bank / _L2_RECORDS).open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        try:
                            out.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue
        except FileNotFoundError:
            pass
        if include_forgotten:
            return out
        # Tombstoned records are WITHHELD from construction (search/recent/retrieval,
        # self-model evidence) but retained on disk — forgetting reshapes the working
        # set, it does not erase. (spec §3/§4; NOVELTY.md "memory as construction")
        return [r for r in out if not r.get("forgotten")]

    def _append_records(self, records: List[Dict[str, Any]]) -> None:
        try:
            with self._lock, (self._bank / _L2_RECORDS).open("a", encoding="utf-8") as fh:
                for r in records:
                    fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.debug("foundational: append records failed: %s", e)

    def _cited_record_ids(self) -> set:
        """L2 record ids currently load-bearing as self-model evidence — UN-FORGETTABLE.
        Forgetting one of these would sever the self-fact -> L2 -> L1 chain that
        NOVELTY.md guarantees "impossible by construction". The scaffold protects it;
        we do NOT trust the proposer not to ask."""
        cited: set = set()
        for f in self._read_self_facts():
            cited.update(f.get("evidence", []) or [])
        return cited

    def _forget_records(self, ids: set, reason: str = "") -> Dict[str, Any]:
        """Explicit forgetting as CONSTRUCTION, not destruction (spec §3 memory_delete).

        Scaffold-gated and reversible: records are tombstoned (marked ``forgotten``),
        not dropped, so they leave the working set but stay auditable and recoverable.
        L1 (raw.jsonl) is NEVER touched — it remains the ground truth anything can be
        rebuilt from. Records cited as self-model evidence are REFUSED. The LLM proposes
        the ids; the scaffold decides what is permissible. Returns a summary for the log."""
        if not ids:
            return {"forgotten": [], "refused": []}
        protected = self._cited_record_ids()
        recs = self._read_records(include_forgotten=True)
        forgotten: List[str] = []
        refused: List[str] = []
        changed = False
        for r in recs:
            rid = r.get("id")
            if rid not in ids or r.get("forgotten"):
                continue
            if rid in protected:                 # scaffold disposes: evidence chain is load-bearing
                refused.append(rid)
                continue
            r["forgotten"] = {"ts": _now_iso(), "reason": (reason or "unspecified")[:200]}
            forgotten.append(rid)
            changed = True
        if changed:
            try:
                with self._lock, (self._bank / _L2_RECORDS).open("w", encoding="utf-8") as fh:
                    for r in recs:                # rewrite L2 in place; tombstones retained on disk
                        fh.write(json.dumps(r, ensure_ascii=False) + "\n")
            except Exception as e:
                logger.debug("foundational: forget failed: %s", e)
                return {"forgotten": [], "refused": refused, "error": str(e)}
        return {"forgotten": forgotten, "refused": refused}

    def _recent_l1_ids(self, n: int = 2) -> List[str]:
        lines = self._read_l1_lines()[-n:]
        ids = []
        for l in lines:
            try:
                ids.append(json.loads(l)["id"])
            except Exception:
                continue
        return ids

    def _write_status(self, status: str) -> None:
        try:
            (self._bank / _STATUS).write_text(
                json.dumps({"status": status, "updated": _now_iso()}, indent=2), encoding="utf-8")
        except Exception:
            pass

    # -- tools (agent-facing navigation) ------------------------------------

    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        return [SAVE_SCHEMA, SEARCH_SCHEMA, RECENT_SCHEMA]

    def handle_tool_call(self, tool_name: str, args: Dict[str, Any], **kwargs) -> str:
        if not self._bank:
            return _err("foundational memory not initialized")

        if tool_name == "memory_save":
            rtype = (args.get("type") or "").strip().lower()
            content = (args.get("content") or "").strip()
            if rtype not in MEMORY_TYPES:
                return _err(f"type must be one of {list(MEMORY_TYPES)}")
            if not content:
                return _err("content is required")
            rec = self._make_record(rtype, content, self._recent_l1_ids())
            self._append_records([rec])
            return json.dumps({"result": "saved", "id": rec["id"], "type": rtype})

        if tool_name == "memory_search":
            query = (args.get("query") or "").strip()
            if not query:
                return _err("query is required")
            top_k = max(1, min(int(args.get("top_k", 5) or 5), 20))
            records = self._read_records()
            if not records:
                return json.dumps({"results": [], "note": "bank is empty"})
            scores = _bm25_lite(query, [r.get("content", "") for r in records])
            ranked = sorted(zip(records, scores), key=lambda x: x[1], reverse=True)
            hits = [{"id": r["id"], "type": r.get("type"), "content": r.get("content"),
                     "source_ids": r.get("source_ids", []), "score": round(s, 3)}
                    for r, s in ranked[:top_k] if s > 0]
            return json.dumps({"results": hits, "count": len(hits)})

        if tool_name == "memory_recent":
            limit = max(1, min(int(args.get("limit", 10) or 10), 50))
            records = self._read_records()[-limit:][::-1]
            items = [{"id": r["id"], "type": r.get("type"), "content": r.get("content"),
                      "created": r.get("created")} for r in records]
            return json.dumps({"results": items, "count": len(items)})

        return _err(f"unknown tool: {tool_name}")

    # -- config surface ------------------------------------------------------

    def get_config_schema(self) -> List[Dict[str, Any]]:
        return [
            {"key": "memory_model", "description": "Local model for the memory-agent role",
             "default": "qwen2.5:7b"},
            {"key": "cycle_interval", "description": "Run the memory cycle every N turns",
             "default": "6"},
        ]

    def save_config(self, values: Dict[str, Any], hermes_home: str) -> None:
        try:
            path = Path(hermes_home) / "foundational.json"
            existing: Dict[str, Any] = {}
            if path.exists():
                existing = json.loads(path.read_text(encoding="utf-8"))
            existing.update({k: v for k, v in values.items() if v not in (None, "")})
            path.write_text(json.dumps(existing, indent=2), encoding="utf-8")
        except Exception as e:
            logger.warning("foundational: save_config failed: %s", e)

    def shutdown(self) -> None:
        t = self._cycle_thread
        if t and t.is_alive():
            t.join(timeout=5.0)


def register(ctx) -> None:
    """Plugin entry point — register the provider with Hermes."""
    ctx.register_memory_provider(FoundationalMemoryProvider())
