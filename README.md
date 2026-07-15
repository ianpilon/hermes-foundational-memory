# Hermes Foundational Memory

> 🛠️ **Update — this spec is now implemented, tested, and running.** See **[IMPLEMENTATION.md](./IMPLEMENTATION.md)** for the working provider, the live viewer, the invariant QA (17/17), and a 5-model **model-agnosticism proof** (0 memory leaks across every proposer; recall model-dependent). Everything below remains the original thesis and reasoning, unchanged.
>
> 🔒 **Update (2026-07-15) — forgetting discipline.** Deletion is now scaffold-gated: records cited as self-model evidence are **un-forgettable**, forgetting is a **reversible, L1-preserving, logged tombstone** (not a hard delete by the proposer), and the *reason* for forgetting is recorded like silence already is. This closed a real hole — an audit found the old delete path had fired one record away from un-grounding the agent's own "I am Pal" self-model. The governance lens was inspired by [Sanna](https://github.com/sanna-ai) (the idea — gate actions at the boundary, make decisions observable — not its receipt/constitution machinery). Details in [IMPLEMENTATION.md → *Forgetting discipline*](./IMPLEMENTATION.md#forgetting-discipline-2026-07-15).

A paste-ready spec for giving **Hermes** (an agent running on a Mac mini) a foundational memory — derived from and grounded in the *Memory as Construction* thesis.

This repo exists to **preserve the context** that produced the spec, so it isn't lost when a chat session closes. The spec itself is in [`agent-memory-spec.md`](./agent-memory-spec.md). Everything below is the reasoning behind it.

---

## TL;DR

Don't build "memory." Build a **Proactive Memory Agent sitting on top of a NapMem-style pyramid.**

That composition is explicitly endorsed by the architecture this is derived from: the pyramid is the long-term store, the proactive memory agent sits on top and decides *whether* any of it enters the next decision. It is also the most tractable on a single Mac mini, because the action agent (Hermes) stays unmodified and the memory role can be a cheaper model run on a fixed interval.

The foundational commitment is not "ingest better" — it is "**give the agent a bank it edits with tools, plus an intervention policy that includes silence.**"

---

## Where this comes from

This spec is a worked application of two prior repos:

| Repo | Role |
|---|---|
| [`memory-as-construction-LLM-wiki`](https://github.com/ianpilon/memory-as-construction-LLM-wiki) | The thesis and its evidence base: a wiki synthesizing Conway (psychology), Levin (biology), Youssef (engineering principles), NapMem (measured action space), the Proactive Memory Agent (measured intervention), and Bongard & Levin (substrate). |
| [`agent-memory-architecture`](https://github.com/ianpilon/agent-memory-architecture) | The five-layer reference architecture with a build-feasibility verdict for each layer. |

**The thesis:** *Memory is not storage to be retrieved; it is the construction process by which an agent persists across time.* "Construction" is the umbrella verb (Conway). It specializes as *interpret* (Levin), *build identity* (Youssef), *navigate* (NapMem), and *intervene* (Proactive Memory Agent).

**The verbs to keep straight** (these are not synonyms of "retrieve"):

- **construct** — the whole loop: encode, consolidate, reconstruct, synthesize.
- **navigate** — *how* memory is accessed (traversing levels, stopping when enough evidence is gathered).
- **intervene** — *whether/when* remembered state enters the next action. **This is primary.**

---

## Why this shape, and not a vector store + RAG

Because the measured evidence in the source work says the wins live in **access discipline**, not ingest structure:

- **NapMem (Xu et al., 2026).** Same memory sources, swapping passive retrieval for learned navigation measurably *drops* accuracy when removed. The win is in *how the agent uses memory*, holding data constant. → [source summary](https://github.com/ianpilon/memory-as-construction-LLM-wiki/blob/main/src/pages/source-napmem.mdx)
- **Proactive Memory Agent (Wu et al., 2026).** A separate memory agent decides whether to inject a reminder or stay silent. Its ablation shows **selective intervention beats passive full-bank exposure *and* always-on injection.** The win is the *decision not to intervene*; exposing more memory can actively hurt. → [source summary](https://github.com/ianpilon/memory-as-construction-LLM-wiki/blob/main/src/pages/source-proactive-memory.mdx)
- **Behavioral state decay.** The failure mode both prior sources miss: information that is *present, correctly structured, and even in-context* that still fails to influence the next action. This is **not a recall failure and not a structure failure** — it is a *timing/control* failure. No schema fixes it; only calibrated intervention does. → [page](https://github.com/ianpilon/memory-as-construction-LLM-wiki/blob/main/src/pages/behavioral-state-decay.mdx)

A vector store + RAG optimizes the ingest/retrieve axis and addresses none of these. That is why the foundation below is an *intervention policy on top of an editable, typed bank*, not a retrieval pipeline.

---

## What to build vs. stub vs. ignore

Directly from the five-layer verdict ledger:

| Build now (shippable) | Stub, don't fake (research frontier) | Ignore for now (blocked on substrate) |
|---|---|---|
| Hierarchy + goal-filtering (L1) | Narrative coherence | Polycomputing / substrate flexibility |
| Typed records + provenance + reconciliation (L2) | Co-emergent self-model (the L4 profile evolves but is not "solved") | Use ordinary storage — the functional layer delivers on ordinary substrate |
| Salience scoring (commodity classifiers) | | |
| Active reinterpretation on retrieval | | |
| **Selective intervention** | | |

> _Update (2026-07): the co-emergent self-model (L4) has since been implemented under a grounding discipline — see [IMPLEMENTATION.md](./IMPLEMENTATION.md). It evolves, but is still not "solved." (Conversely, of the "build now" items, salience scoring remains a neutral stub in the implementation.)_

---

## Files

- [`agent-memory-spec.md`](./agent-memory-spec.md) — the paste-ready spec. Hand this to the builder (an AI or a human). It is self-contained.
- [`LICENSE`](./LICENSE) — MIT, matching the source repos.

---

## Sources (the lineage this is built on)

- **Conway (2005)** — the Self-Memory System (psychology). Hierarchy, working-self goal-gating, coherence vs correspondence.
- **Levin (2024)** — self-improvising, substrate-agnostic memory (biology). Bowtie re-inflation, no single substrate, memories-as-agents.
- **Youssef (2026)** — five principles AI memory lacks (engineering principles).
- **NapMem / Xu et al. (2026)** — memory as a structured action space; first *measured* source. Navigation beats passive retrieval with sources held constant.
- **Proactive Memory Agent / Wu et al. (2026)** — memory as intervention; selective intervention (incl. silence) beats full-bank exposure and always-on injection.
- **Bongard & Levin (2023)** — polycomputing; the substrate-flexibility question (not exercised in this spec).

Full detail and all inter-page reasoning live in the [wiki](https://github.com/ianpilon/memory-as-construction-LLM-wiki). The layered verdicts live in the [architecture repo](https://github.com/ianpilon/agent-memory-architecture).

---

## License

MIT — see [LICENSE](./LICENSE).

---
Derived by Ian Pilon from the *Memory as Construction* thesis.
