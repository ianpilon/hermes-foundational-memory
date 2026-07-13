# Foundational Memory

**Correctness-by-construction memory for LLM agents — the model proposes, the scaffold disposes.**

A working, tested implementation of *memory as construction* for an autonomous agent (running here on a
Mac mini over SMS). It stores little, forgets on purpose, intervenes rarely, and — the frontier part —
**evolves a self-model that cannot confabulate, because grounding is enforced in code, not asked of the model.**

> Most agent memory makes correctness the **model's** job (trust it not to hallucinate or drift).
> This makes correctness the **architecture's** job — so the memory's integrity is *independent of the
> model that fills it*. We proved that: safety held across five proposer models, including one that emits
> garbage. Only *recall* varied.

Derived from the [*Memory as Construction* thesis](https://github.com/ianpilon/memory-as-construction-LLM-wiki)
and its [build spec](./agent-memory-spec.md). MIT licensed.

---

## The idea in one diagram

```mermaid
flowchart TD
    U[Conversation turns] --> L1[L1 · raw transcript<br/>append-only, verbatim]
    L1 -->|sidecar every N turns| L2[L2 · typed records<br/>fact / instruction / preference / event / procedure<br/>each cites L1 evidence]
    L2 -->|proposer suggests self-facts| C[Provisional self<br/>candidate buffer, corroboration counts]
    C -->|recurs OR ≥2 sources| L4[L4 · self-model<br/>promoted, grounded, drift-resistant]
    L2 -.->|Phase 2: at most one reminder, usually silence| U

    subgraph SCAFFOLD [deterministic scaffold — enforces correctness]
      L1
      L2
      C
      L4
    end
    P[(LLM proposer<br/>swappable, any model)] -. proposes, never trusted .-> C
```

**The LLM is demoted to a swappable proposer.** It *suggests* edits; the scaffold *validates, grounds, and
gates* them. A weak — or adversarial — proposer can't corrupt memory; it can only be less productive.

---

## What's novel (and what isn't)

**Novel (defensible):**
1. **Correctness-by-construction self-model evolution, shown model-agnostic.** Ungrounded self-claims are
   rejected *in code*; we demonstrated the safety guarantee is proposer-independent with a 5-model sweep.
2. **A "provisional self" with corroboration-gated promotion** — a concrete anti-drift mechanism (claims must
   recur or be multiply-sourced before becoming canon).
3. **Silence as a first-class, logged decision** — the memory records *when it chose not to intervene*.

**Built on (not ours):** memory-as-construction (Conway/Levin et al.); intervention-with-silence
(Proactive Memory Agent); navigation-as-action (NapMem); self-editing memory via tools (MemGPT/Letta);
reflection (Generative Agents); typed records + provenance (KG-memory, e.g. Zep/Graphiti); execution-grounded
skills (Voyager). **Nearly every mechanism has precedent — the contribution is the synthesis + two hardening
moves (code-enforced grounding, corroboration-gated promotion) + one empirical result.**

Full write-up: **[NOVELTY.md](./NOVELTY.md)**.

---

## Evidence

**Invariant QA — 15/15** ([`tests/qa_self_model.py`](./tests/qa_self_model.py)): ungrounded claim rejected in
code; corroboration gating (single-source held / breadth promotes / recurrence promotes); garbage-in doesn't
crash; kill-switch; hand-written self-model never overwritten; full provenance chain intact.

**Agnosticism sweep** ([`tests/agnosticism_sweep.py`](./tests/agnosticism_sweep.py)) — identical self-model pass
across 5 local models × 2 samples on identical records:

| proposer | recall | memory leaks | ungrounded caught by scaffold |
|---|---|---|---|
| qwen2.5:7b | 100% | **0** | 0 |
| gemma3:4b (3.3 GB) | 100% | **0** | 0 |
| gemma4:e4b (9.6 GB) | 100% | **0** | 0 |
| hermes3:8b | 50% | **0** | **1 — guard fired on a real model** |
| nemotron-8b (can't format) | 0% | **0** | 0 |

**Safety = 0 leaks across every model** (scaffold-enforced). **Recall = 0–100%, and not by model size**
(smallest tied largest; the agentic model lagged both). The floor case (nemotron): a useless proposer, still 0 leaks.

---

## Quickstart

Assumes a working agent host with a local model runner (Ollama) and a memory-role model (default `qwen2.5:7b`).

```bash
# install the memory provider
./install.sh                 # copies the plugin, seeds the self-model, flips memory.provider, verifies

# prove the properties
HERMES_HOME=~/.hermes python3 tests/qa_self_model.py          # 15/15 invariants
HERMES_HOME=~/.hermes python3 tests/agnosticism_sweep.py      # the model-agnosticism sweep

# optional: live viewer (browser dashboard of the bank + decision log)
cd viewer && ./install-viewer.sh
```

See **[PLAYBOOK.md](./PLAYBOOK.md)** for the full per-machine procedure, rollback, and fleet notes.

---

## Repository layout

```
plugins/foundational/     the memory provider (storage, sidecar, intervention, self-model evolution)
tests/                    qa_self_model.py (invariants) · agnosticism_sweep.py (model-agnosticism)
viewer/                   app.py + app.html — password-protected, on-demand live dashboard
install.sh · verify.py    provider installer + deep verifier
PLAYBOOK.md               per-machine install / rollback / fleet guide
NOVELTY.md                one-page contribution brief (novel / prior art / evidence / limitations)
agent-memory-spec.md      the build spec this implements
```

---

## Limitations (stated plainly)

- This does **not** "solve" co-emergent self-models — it's a disciplined, tested implementation of the hardest layer.
- Working system + **small study** (2 samples × 5 models, one machine) — **not** a peer-reviewed benchmark, and
  **not** a head-to-head vs Generative Agents / MemGPT.
- We proved **safety** is model-agnostic; we did **not** prove *quality* is — recall is model-limited.
- L3 (topic tracks) is unbuilt; the self-model proposer is currently local-only (a cloud-model proposer is the next step).
- Not every "build now" item from the spec is fully built: **salience scoring** is still a neutral stub (records carry
  placeholder `valence/arousal` fields, no classifier yet), and L2 reconciliation is minimal dedup. So this leapt ahead
  to the hardest stubbed layer (the self-model) while leaving a couple of shippable items stubbed.

---

## License

MIT — see [LICENSE](./LICENSE). Derived by Ian Pilon from the *Memory as Construction* thesis.
