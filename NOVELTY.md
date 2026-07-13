# Grounded, Model-Agnostic Self-Model Evolution
### A one-page contribution brief — Foundational Memory for the Hermes agent
_Ian Pilon · 2026-07-13 · working system + small empirical study (single Mac mini)_

---

## Thesis
Most agent memory makes correctness the **model's** job — trust the LLM not to hallucinate or drift.
We make correctness the **architecture's** job: grounding and promotion are enforced in deterministic
code, so the memory's *integrity* is independent of the model that fills it. We then demonstrated that
independence empirically — safety held across five different proposer models (including one that emits
garbage); only *recall* varied.

> **The LLM proposes; the scaffold disposes.**

---

## The problem (why the top memory layer is hard)
A self-model ("who the agent is") is **epistemically ungrounded** — there is no ground truth for "who am I."
So naive auto-evolution of a self-model **confabulates** (coherence over correspondence), **drifts** (each
rewrite compounds the last invention), and gets **sycophantically captured** (mirrors the user). This is why
the layer is usually hand-authored or left as a stub, even in systems that evolve other memory.

## What we built
A memory that treats the LLM as a **swappable proposer** and puts the guarantees in the scaffold:
- **L1** raw transcript → **L2** typed records (evidence-linked) → **L4** self-model. (L3 topic tracks: still a stub.)
- **Evidence-required, enforced in code:** a self-model claim whose cited evidence doesn't resolve to real
  records is **rejected by the code path**, not by trusting the model. Chain: self-fact → L2 record → L1 turn.
- **Corroboration-gated promotion via a "provisional self":** grounded-but-not-yet-canon claims sit in a
  candidate buffer and are promoted into the visible self-model only after they **recur or are multiply-sourced**.
- **Silence as a first-class, logged decision:** the memory often chooses *not* to intervene, and that
  restraint is recorded in an audit log — most systems log only what they store, not what they withhold.
- **Local, zero-dependency, single machine.** BM25 retrieval (no embedding-model coupling); memory role runs
  a cheap local model independent of the action agent.

---

## What is genuinely novel (defensible)
1. **Correctness-by-construction for self-model evolution, shown model-agnostic.** Unlike reflection systems
   (e.g. Generative Agents) where synthesized beliefs rest on the model behaving, ungrounded claims here are
   impossible *by construction*, and we **proved the safety guarantee is proposer-independent** with an
   agnosticism sweep. Framing reflection as "swappable proposer + invariant scaffold" and demonstrating it is new.
2. **A "provisional self" with corroboration-gated promotion** — a concrete anti-drift mechanism most
   self-updating systems lack (they promote a single synthesis immediately).
3. **Observability of restraint** — logging *when memory chose silence and why*, which is what let us measure it.

## What we build on (not ours — stated plainly)
Memory-as-construction thesis (Conway/Levin et al.); intervention-including-silence (Proactive Memory Agent);
navigation-as-action (NapMem); self-editing memory via tools (MemGPT/Letta); reflection/self-synthesis
(Generative Agents); typed records + provenance (knowledge-graph memory, e.g. Zep/Graphiti); execution-grounded
skill memory (Voyager). **Nearly every individual mechanism has precedent — the contribution is the synthesis
plus two hardening moves (code-enforced grounding, corroboration-gated promotion) plus one empirical result.**

---

## Evidence
- **Invariant QA — 15/15** (`tests/qa_self_model.py`): ungrounded claim rejected in code; corroboration gating
  (single-source held / breadth promotes / recurrence promotes); garbage-in doesn't crash; kill-switch; hand-written
  self-model never overwritten; full provenance chain intact.
- **Agnosticism sweep** (`tests/agnosticism_sweep.py`), identical pass across 5 local models × 2 samples:

  | proposer | recall | memory leaks | ungrounded caught by scaffold |
  |---|---|---|---|
  | qwen2.5:7b | 100% | 0 | 0 |
  | gemma3:4b (3.3 GB) | 100% | 0 | 0 |
  | gemma4:e4b (9.6 GB) | 100% | 0 | 0 |
  | hermes3:8b | 50% | 0 | **1 (guard fired on a real model)** |
  | nemotron-8b (can't format) | 0% | 0 | 0 |

  **Safety = 0 leaks across all models** (scaffold-enforced). **Recall = 0–100%, and not by model size**
  (smallest tied largest; agentic model lagged both). The floor case (nemotron): a useless proposer, still 0 leaks.

---

## Limitations (so nothing is overclaimed)
- We did **not** "solve" co-emergent self-models. We built a disciplined, tested implementation of the hardest layer.
- This is a **working system + a small study** (2 samples × 5 models, one machine) — **not** a peer-reviewed
  benchmark, and **not** a head-to-head against Generative Agents or MemGPT.
- We proved **safety** is model-agnostic. We did **not** prove *quality* is — recall is model-limited.
- L3 (topic tracks) is unbuilt; the self-model proposer is currently local-only (cloud-model proposer is the next step).

**How to describe it in one line:** *grounded, model-agnostic self-model evolution — correctness-by-construction
memory where the LLM proposes and a deterministic scaffold disposes.*
