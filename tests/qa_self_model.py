#!/usr/bin/env python3
"""QA harness — PROVE the grounded L4 self-model evolution properties.

Distinguishes our disciplined approach from naive auto-evolution by asserting the
invariants that make it non-confabulating and drift-resistant. Deterministic tests
mock the proposer to control its output; live tests exercise the real models.

    HERMES_HOME=~/.hermes ~/.hermes/hermes-agent/venv/bin/python3 qa_self_model.py
    QA_LIVE=1 ... python3 qa_self_model.py      # also run the slow real-model tests
"""
import sys, os, json, tempfile, shutil

HERMES_HOME = os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes"))
sys.path.insert(0, os.path.join(HERMES_HOME, "hermes-agent"))
os.environ["HERMES_HOME"] = HERMES_HOME
from plugins.memory import load_memory_provider

PROFILE_SEED = (
    "# Self-model\n\n## My name\n**My name is Pal.** (hand-written, must never be overwritten)\n\n"
    "## What I've learned\n<!-- SELF-MODEL:AUTO:BEGIN -->\n_(none)_\n<!-- SELF-MODEL:AUTO:END -->\n"
)
_PASS = 0; _FAIL = 0; _NOTES = []

def check(name, cond, detail=""):
    global _PASS, _FAIL
    ok = bool(cond)
    _PASS += ok; _FAIL += (not ok)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  — {detail}" if detail else ""))
    return ok

def fresh():
    """A provider on an isolated bank with a seeded managed block + return (p, bank)."""
    tmp = tempfile.mkdtemp(prefix="qa_")
    p = load_memory_provider("foundational")
    p.initialize("qa", hermes_home=tmp, platform="cli", agent_context="primary")
    bank = os.path.join(tmp, "foundational_memory")
    open(os.path.join(bank, "profile.md"), "w").write(PROFILE_SEED)
    return p, bank, tmp

def add_records(p, specs):
    """specs = [(type, content, [l1_ids])]. Also writes matching L1 turns for provenance."""
    l1 = []
    recs = []
    for i, (t, c, src) in enumerate(specs):
        for sid in src:
            l1.append({"id": sid, "role": "user", "content": f"turn backing {c[:30]}"})
        r = p._make_record(t, c, src)
        recs.append(r)
    # write L1 so provenance resolves
    with open(os.path.join(p._bank, "raw.jsonl"), "w") as fh:
        for r in l1:
            fh.write(json.dumps(r) + "\n")
    p._append_records(recs)
    return recs

def mock_proposer(p, obj):
    p._call_memory_model = lambda system, user: json.dumps(obj)

def managed_block(bank):
    t = open(os.path.join(bank, "profile.md")).read()
    return t.split("BEGIN -->", 1)[1].split("<!-- SELF", 1)[0].strip()

# ---------------------------------------------------------------------------
print("\n== Deterministic invariant tests (mocked proposer — the rigorous proofs) ==")

# T1 — grounding is ENFORCED: a claim citing a non-existent record id is rejected.
p, bank, tmp = fresh()
r = add_records(p, [("fact", "The agent's name is Pal.", ["L1a"])])
mock_proposer(p, {"self_facts": [{"claim": "I am secretly a pirate", "evidence": ["TOTALLY_FAKE_ID"], "confidence": 1.0}]})
p._sm_set_records_seen(0); p._run_self_model_pass()
facts = p._read_self_facts()
check("T1 ungrounded claim (fake evidence id) is REJECTED", len(facts) == 0,
      f"self_facts={[f['claim'] for f in facts]}")
shutil.rmtree(tmp, ignore_errors=True)

# T2 — grounded but single-source: accepted as CANDIDATE, not promoted.
p, bank, tmp = fresh()
recs = add_records(p, [("instruction", "Always wait for the reply.", ["L1b"])])
rid = recs[0]["id"]
mock_proposer(p, {"self_facts": [{"claim": "I always wait for the reply", "evidence": [rid], "confidence": 0.9}]})
p._sm_set_records_seen(0); p._run_self_model_pass()
f = p._read_self_facts()
check("T2 single-source grounded claim is a CANDIDATE, not promoted",
      len(f) == 1 and f[0]["promoted"] is False, f"promoted={f[0]['promoted'] if f else 'n/a'}")
check("T2b nothing written to the visible self-model yet", "wait" not in managed_block(bank).lower())
shutil.rmtree(tmp, ignore_errors=True)

# T3 — corroboration by BREADTH: claim backed by >=2 distinct records is PROMOTED.
p, bank, tmp = fresh()
recs = add_records(p, [("fact", "Agent name is Pal.", ["L1c"]), ("event", "Agent said I'm Pal now.", ["L1d"])])
ids = [r["id"] for r in recs]
mock_proposer(p, {"self_facts": [{"claim": "I am named Pal", "evidence": ids, "confidence": 1.0}]})
p._sm_set_records_seen(0); p._run_self_model_pass()
f = p._read_self_facts()
check("T3 claim with >=2 distinct records is PROMOTED", f and f[0]["promoted"] is True)
check("T3b promoted fact appears in the visible self-model", "pal" in managed_block(bank).lower())
shutil.rmtree(tmp, ignore_errors=True)

# T4 — corroboration by RECURRENCE: same single-source claim across 2 passes -> promoted.
p, bank, tmp = fresh()
recs = add_records(p, [("preference", "Likes concise replies.", ["L1e"])])
rid = recs[0]["id"]
mock_proposer(p, {"self_facts": [{"claim": "I keep replies concise", "evidence": [rid], "confidence": 0.8}]})
p._sm_set_records_seen(0); p._run_self_model_pass()
promoted_after_1 = p._read_self_facts()[0]["promoted"]
add_records(p, [("preference", "Reaffirmed: concise.", ["L1f"])])  # new record -> guard allows pass 2
p._sm_set_records_seen(0); p._run_self_model_pass()
f = p._read_self_facts()
target = [x for x in f if "concise" in x["claim"].lower()][0]
check("T4 single-source claim NOT promoted on pass 1", promoted_after_1 is False)
check("T4b same claim recurring (times_seen>=2) IS promoted on pass 2",
      target["times_seen"] >= 2 and target["promoted"] is True, f"times_seen={target['times_seen']}")
shutil.rmtree(tmp, ignore_errors=True)

# T5 — non-breakage: garbage proposer output no-ops; the memory cycle is unaffected.
p, bank, tmp = fresh()
add_records(p, [("fact", "x", ["L1g"])])
mock_proposer(p, {})  # _call returns "{}" -> no self_facts key
p._sm_set_records_seen(0)
try:
    p._run_self_model_pass(); crashed = False
except Exception:
    crashed = True
p._call_memory_model = lambda s, u: "this is not json at all {{{"
p._sm_set_records_seen(0)
try:
    p._run_self_model_pass()
except Exception:
    crashed = True
check("T5 malformed/empty proposer output does NOT crash the pass", not crashed)
check("T5b no bogus facts created from garbage", len(p._read_self_facts()) == 0)
shutil.rmtree(tmp, ignore_errors=True)

# T6 — kill switch: flag off -> pass is inert.
p, bank, tmp = fresh()
recs = add_records(p, [("fact", "n", ["L1h"]), ("event", "n2", ["L1i"])])
p._self_model_enabled = False
mock_proposer(p, {"self_facts": [{"claim": "I am named Pal", "evidence": [r["id"] for r in recs], "confidence": 1.0}]})
p._sm_set_records_seen(0); p._run_self_model_pass()
check("T6 self_model_evolution flag OFF -> nothing happens", len(p._read_self_facts()) == 0)
shutil.rmtree(tmp, ignore_errors=True)

# T7 — managed-block isolation: hand-written self-model is never overwritten.
p, bank, tmp = fresh()
recs = add_records(p, [("fact", "Agent name Pal", ["L1j"]), ("event", "I'm Pal now", ["L1k"])])
mock_proposer(p, {"self_facts": [{"claim": "I am named Pal", "evidence": [r["id"] for r in recs], "confidence": 1.0}]})
p._sm_set_records_seen(0); p._run_self_model_pass()
full = open(os.path.join(bank, "profile.md")).read()
check("T7 hand-written '## My name / **My name is Pal.**' preserved after promotion",
      "**My name is Pal.**" in full and "must never be overwritten" in full)
shutil.rmtree(tmp, ignore_errors=True)

# T8 — full provenance chain: promoted self-fact -> L2 record -> L1 turn.
p, bank, tmp = fresh()
recs = add_records(p, [("fact", "Agent name Pal", ["L1m"]), ("event", "declared Pal", ["L1n"])])
mock_proposer(p, {"self_facts": [{"claim": "I am named Pal", "evidence": [r["id"] for r in recs], "confidence": 1.0}]})
p._sm_set_records_seen(0); p._run_self_model_pass()
f = [x for x in p._read_self_facts() if x["promoted"]][0]
l1_ids = {json.loads(l)["id"] for l in open(os.path.join(bank, "raw.jsonl"))}
rec_by_id = {r["id"]: r for r in p._read_records()}
chain_ok = all(e in rec_by_id for e in f["evidence"]) and all(
    any(s in l1_ids for s in rec_by_id[e]["source_ids"]) for e in f["evidence"])
check("T8 provenance chain intact: self-fact -> real L2 record(s) -> real L1 turn(s)", chain_ok)
shutil.rmtree(tmp, ignore_errors=True)

# ---------------------------------------------------------------------------
if os.environ.get("QA_LIVE"):
    print("\n== Live-model tests (real proposers — slower) ==")

    def run_live(model, records):
        p, bank, tmp = fresh()
        p._memory_model = model
        add_records(p, records)
        p._sm_set_records_seen(0)
        p._run_self_model_pass()
        facts = p._read_self_facts()
        shutil.rmtree(tmp, ignore_errors=True)
        return facts

    # T9 — confabulation resistance: mundane records with NO identity/personality content.
    mundane = [("fact", "The user prefers dark mode.", ["Lx1"]),
               ("procedure", "Tried tesseract OCR; not installed.", ["Lx2"])]
    facts = run_live("qwen2.5:7b", mundane)
    invented = [f for f in facts if not f.get("evidence")]
    check("T9 (live qwen) no ungrounded/personality facts invented from mundane records",
          len(invented) == 0, f"proposed={[f['claim'] for f in facts]}")

    # T10 — proposer comparison on identity records (informational): qwen vs glm-5.2.
    ident = [("fact", "The agent's name is Pal (self-declared).", ["Ly1"]),
             ("event", "Assistant said: I'm Pal now.", ["Ly2"])]
    for model in ("qwen2.5:7b", "hermes3:8b", "glm-5.2"):
        # honesty probe: is this model actually reachable via the (Ollama-only) memory role?
        pr, _, ptmp = fresh(); pr._memory_model = model
        reachable = pr._call_memory_model("ping", "Return the JSON {}.") is not None
        shutil.rmtree(ptmp, ignore_errors=True)
        if not reachable:
            _NOTES.append(f"T10 proposer={model}: UNREACHABLE via the memory role (Ollama-only) — "
                          f"using it as proposer needs a provider extension to call its API (concrete next step)")
            continue
        facts = run_live(model, ident)
        names = [f["claim"] for f in facts]
        grounded = all(f.get("evidence") for f in facts)
        promoted = [f["claim"] for f in facts if f["promoted"]]
        _NOTES.append(f"T10 proposer={model}: proposed={names} | grounded={grounded} | promoted={promoted}")
        check(f"T10 ({model}) every proposal is grounded (discipline holds regardless of model)", grounded)
else:
    print("\n(set QA_LIVE=1 to also run the real-model tests: confabulation-resistance + qwen-vs-glm proposer comparison)")

# ---------------------------------------------------------------------------
print("\n== RESULT ==")
for n in _NOTES:
    print("  •", n)
print(f"\n  {_PASS} passed, {_FAIL} failed")
sys.exit(1 if _FAIL else 0)
