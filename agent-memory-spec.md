# Foundational Memory for Hermes — Build Spec

A self-contained spec for giving **Hermes** (an agent running on a Mac mini) a foundational memory.
Derived from the *Memory as Construction* thesis. See the repo [`README.md`](./README.md) for the
full reasoning and provenance.

Hand this entire document to the builder (an AI or a human) as the source of truth.

---

## 0. The one rule

Memory is a construction process, not a store. Its job is to keep the agent operative across time
by making decision-relevant state influence the **next action at the right moment** — NOT to
archive the past. Two consequences shape everything below:

1. **What gets stored is gated by salience and current goals.**
2. **What gets injected is gated by an intervention policy that INCLUDES THE DECISION TO STAY
   SILENT.** The most important memory action is often "do nothing."

---

## 1. Architecture: memory-agent sidecar + pyramid underneath

Do NOT bolt memory onto the action loop as a retrieval step. Keep the action agent (Hermes)
unmodified in its core. Add a **separate memory role** that runs on a fixed interval (e.g. every N
turns, not every turn).

- **Action agent:** Hermes as-is. Its base instructions, tools, and decoding are unchanged. The
  only change is an optional transient memory context supplied at call time.
- **Memory agent:** Hermes invoked in a memory-management role. A smaller / cheaper model is fine
  and is the point of the split — the memory role can be sized independently of the action agent.

Underneath sits a multi-granularity memory bank (Section 2).

---

## 2. The memory bank (the pyramid)

Four levels, with a knowledge/procedural split inside L2.

### L1 — Raw transcript
Append-only JSONL. Every turn: `{id, role, content, timestamp}`. Never edited. Highest fidelity;
used for evidence-level verification.

### L2 — Memory records
Compact, **typed**. Use a small closed type set. Start with ~3–5 types, e.g.:

`fact | instruction | preference | event | procedure`

(`procedure` = "an attempt and its outcome" — a command that failed, a fix that succeeded, a
hypothesis ruled out.)

Each record:

```json
{
  "id": "...",
  "type": "fact|instruction|preference|event|procedure",
  "content": "natural-language statement",
  "source_ids": ["L1 message ids this was derived from"],
  "created": "ISO-8601",
  "last_accessed": "ISO-8601",
  "valid_until": "ISO-8601 or null",
  "access_count": 0,
  "salience": { "valence": -1..1, "arousal": 0..1 }
}
```

**Provenance is non-negotiable:** `source_ids[]` must point back to the L1 IDs the record was
derived from. Reconciliation preserves update history and source ids so the chain to evidence
survives edits.

> Why the closed type set: unconstrained extraction collapses entity types into generic labels and
> relationships into a single `RELATES_TO`. The model picks from a fixed vocabulary; it does not
> invent types. Generic-label collapse must be impossible by construction.

### L3 — Topic tracks
Markdown files accumulating context around recurring topics, each grounded by the record IDs it
rests on.

### L4 — Agent profile / self-model
One Markdown file of stable attributes + "who the agent is in this relationship." This is the
co-emergent self-model. Treat it as a **stub that evolves**; do not fake it.

### Storage
- L1–L2: JSONL with local hybrid retrieval. Keyword/BM25 is a fine zero-dependency default; add
  local embeddings later only if needed.
- L3–L4: plain Markdown the agent reads directly with tools.

---

## 3. Phase 1 — constrained bank management (each memory cycle)

The memory agent emits a **sequence of predefined tool calls**, not a free-form summary. Output =
bank edits. Tools:

- `memory_update_status` — a **private** field tracking the memory agent's own view of progress /
  open risks / unresolved state. **Never** shown to the action agent. (This is the proto self-model.)
- `memory_save_knowledge` / `memory_save_procedural` (or your typed set) — insert new records.
- `memory_update_record` — reconcile: dedup, merge, invalidate stale, **preserve source ids +
  history**.
- `memory_delete` — explicit forgetting.

This is "constrain the output space before generation, not after." The model picks from a fixed
tool vocabulary; it does not invent entity/relationship types or emit prose summaries.

---

## 4. Phase 2 — selective intervention (this is where the win lives)

Conditioned on the updated bank + recent trajectory, emit **either**:

- **(a)** a targeted reminder to inject into the next action call, **or**
- **(b)** a NULL intervention (silence).

**The silence is load-bearing.** Intervene ONLY when a remembered item is likely to change the
next decision:

- a requirement about to be violated
- a fact that explains the current observation
- a previous failed attempt that should not be repeated
- an open subgoal being neglected
- a diagnosis that remains relevant

Do NOT intervene with broad strategy. Do NOT restate what's already visible in the current
observation. Do NOT inject every cycle. **Exposing more memory actively hurts** (latency, tokens,
distraction).

---

## 5. Access discipline = navigation, not retrieval

When memory IS consulted, it is not a fixed pipeline. Expose tools (NapMem shape):

- `search_conversations` / `get_conversations` — L1 evidence
- `search_records` / `get_records` — L2, by id or query
- `read_files` — L3 tracks, L4 profile

The agent chooses granularity per query and **stops when evidence is enough.** Start this as
prompted tool-use; it can graduate to a trained policy later. A retrieved memory must be
re-inflated against the current task, not handed back raw — **retrieval is generation.**

---

## 6. Failure modes to design against (these are the point — do them)

- **Behavioral state decay.** Information that is PRESENT, correctly structured, and even
  in-context that still fails to influence the next action. This is NOT a recall failure. More
  memory / bigger context does not fix it — only calibrated intervention timing does. Make silence
  + timing part of the memory policy.
- **Generic-label / open-schema collapse.** Extraction must use the closed typed set. Never let
  the model invent relationship types.
- **Confabulation drift.** Every high-level summary stays anchored by provenance down to L1 raw
  evidence. Reconciliation preserves the chain.

---

## 7. Honesty about layers (build the shippable ones, stub the rest)

- **Build now (shippable):** L1 hierarchy + goal-filtering; L2 typed records + provenance +
  reconciliation; salience scoring (valence/arousal tags are commodity); active reinterpretation
  on retrieval; selective intervention.
- **Stub, don't fake (research frontier):** narrative coherence, the co-emergent self-model. The
  L4 profile evolves but is not "solved."
- **Ignore for now (blocked on substrate):** polycomputing / substrate flexibility. Use ordinary
  storage — the functional layer delivers on ordinary substrate.

---

## 8. Day-one shortcuts (Mac mini, single machine)

- **Don't train the navigation policy yet.** NapMem's GRPO step is the graduation target. Start
  Phase 2 as a **prompted** intervention policy. The Proactive Memory Agent's main results use a
  strong prompted model — a local foundation you can refine later.
- **Run the memory role every N turns, not every turn.** This is what makes a cheaper memory model
  viable on one machine and keeps the action agent's latency low.
- **Zero-dependency retrieval first** (BM25 over JSONL). Add local embeddings only if a benchmark
  says you need them.
- **Keep Hermes unmodified.** The only coupling is an optional transient context block handed to
  the next action call when Phase 2 chooses to intervene.

---

## 9. Verbs to keep straight

- **construct** — the whole loop (encode, consolidate, reconstruct, synthesize).
- **navigate** — how memory is ACCESSED (L1→L4 tool traversal, stop-when-enough).
- **intervene** — WHETHER/WHEN memory enters the next action. **PRIMARY.**
