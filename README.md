# Hermes Foundational Memory

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

## Context that produced the spec: the Graphiti / schema post

This spec was written in response to encountering a common framing (exemplified by [Graphiti](https://github.com/getzep/graphiti) / Zep marketing): *"the more your agent remembers, the less it knows; the fix is schema discipline — constrain the output space with typed entities and edges before generation."* The question was: **is anything in that framing new relative to this work?**

The verdict, claim by claim:

### What the schema framing already overlaps with this work (often deeper here)

| Schema-framing claim | Where it already lives here |
|---|---|
| "Recall is the wrong target; the hard problem is what to forget / never store" | The thesis itself; plus *behavioral-state-decay*: "this is not a recall failure, it is a salience-at-the-right-moment failure." **Stronger here** — forgetting is an *intervention/timing* decision, not just an ingest/storage decision. |
| "It's a structure problem, not retrieval" | Same page: "more memory, bigger context, or better retrieval alone do not fix it." |
| Typed records / small closed type set ("start with 3–4 types") | NapMem ships a worked 4-type example: `fact \| event \| instruction \| preference`. → [memory-pyramid](https://github.com/ianpilon/memory-as-construction-LLM-wiki/blob/main/src/pages/memory-pyramid.mdx) |
| Dedup, contradiction/reconciliation, provenance | `memory-pyramid` (reconcile, dedup, merge, update stale) + all of [provenance-linking](https://github.com/ianpilon/memory-as-construction-LLM-wiki/blob/main/src/pages/provenance-linking.mdx). |
| "Constrain the output space before generation, not after" | Proactive Memory Agent Phase 1: output is "a sequence of bank edits, not a free-form summary… explicit and constrained" via predefined tool calls. The exact pattern, applied to memory-management tools. |
| Temporal resolution / preserving history on update | In embryo: "reconciliation preserves update history and source identifiers." |
| Graphiti = the product that does this | Already placed in the architecture map: Layer 1, *"Temporal knowledge graphs (Zep / Graphiti) already approximate this,"* verdict **Shippable today.** |

### What is genuinely new in the schema framing (the delta)

1. **The graph-schema micro-diagnosis** — "entity types collapse into generic labels; relationships flatten into a single `RELATES_TO`." This work diagnoses the failure at the *architectural* level (storage vs identity) and the *behavioral* level (state decay), but never articulates this specific graph-schema failure mode. Same root disease, different layer.
2. **Typed edges with source/target validity constraints** — an ontology where "if your schema has no edge connecting Project to Competitor, that relationship cannot exist in memory." **This is the one concrete mechanism not present here.** Provenance links here are *back-pointers* (record → source message), not a typed-relationship grammar with connection validity.
3. **The "10/10/10, start with 3–4" heuristic** — a phrasing; the worked NapMem example already embodies the principle.

### Where the schema framing is incomplete — and this work has the evidence

This is the load-bearing insight. The schema framing is implicitly binary: **schema vs. retrieval** ("constrain before generation… and retrieval precision follows"). The measured evidence here says that is a false floor:

- **NapMem**: same memory sources, navigation vs passive retrieval changes the outcome. Ingest structure held constant → the win is in *how memory is used*.
- **Proactive Memory Agent**: the win is the *decision whether to intervene at all*, independent of how well the bank is structured.
- **Behavioral state decay**: a failure mode no schema can touch, because the information is present and correctly structured but behaviorally inert.

Relative to the five-layer architecture, the schema framing lives **entirely in the encode layer** of the construction loop. The measured gains live in **reconstruct** (navigate) and **synthesize/act** (intervene). Schema discipline is **necessary but not sufficient** — it is the floor, not the fix.

> **Bottom line of the comparison:** operate one layer *above* the schema framing. Nothing in it contradicts this thesis; it is a single-layer restatement of the encode step, plus a graph-schema diagnosis and typed-edge mechanic worth borrowing. This spec borrows the closed-typed-set discipline (Section 3) but refuses to let ingest structure stand in for the access and intervention layers that actually carry the measured wins.

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
