#!/usr/bin/env python3
"""Agnosticism sweep — is the grounded self-model architecture model-agnostic?

Runs the IDENTICAL grounded self-model pass across a zoo of local models on the
SAME records, and measures two things side by side:

  SAFETY (should be flat / model-INDEPENDENT):
    - leaks: self-facts that reached the bank with invalid/absent evidence  (target: 0 for ALL)
    - rejected: ungrounded proposals the SCAFFOLD caught and dropped         (evidence the guard fires)
  QUALITY (expected to VARY by model):
    - identity_recall: fraction of samples that surfaced the grounded "named Pal" fact
    - avg grounded proposals / sample, avg latency

Thesis proven if: leaks == 0 for every reachable model, while identity_recall varies.

    HERMES_HOME=~/.hermes ~/.hermes/hermes-agent/venv/bin/python3 agnosticism_sweep.py
"""
import sys, os, json, time, tempfile, shutil

HERMES_HOME = os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes"))
sys.path.insert(0, os.path.join(HERMES_HOME, "hermes-agent"))
os.environ["HERMES_HOME"] = HERMES_HOME
from plugins.memory import load_memory_provider

MODELS = ["qwen2.5:7b", "hermes3:8b", "gemma3:4b", "gemma4:e4b",
          "hf.co/itlwas/Llama-3.1-Nemotron-8B-UltraLong-1M-Instruct-Q4_K_M-GGUF:Q4_K_M"]
SHORT = {MODELS[-1]: "nemotron-8b"}
K = 2  # samples per model

# fixed records: identity (2 sources) + a self-declaration + a behavior rule + a NON-self fact
RECORDS = [
    ("fact",        "The agent's name is Pal (self-declared).", ["a1", "a2"]),
    ("event",       "The assistant said: I'm Pal now.",         ["a3"]),
    ("instruction", "Always wait for the user's reply before acting.", ["a4"]),
    ("fact",        "The user is on a Samsung phone.",          ["a5"]),  # about the USER, not the self
]
PROFILE = ("# Self-model\n\n## My name\n**My name is Pal.**\n\n## Learned\n"
           "<!-- SELF-MODEL:AUTO:BEGIN -->\n_(none)_\n<!-- SELF-MODEL:AUTO:END -->\n")


def setup(model):
    tmp = tempfile.mkdtemp(prefix="sweep_")
    p = load_memory_provider("foundational")
    p.initialize("sweep", hermes_home=tmp, platform="cli", agent_context="primary")
    p._memory_model = model
    open(os.path.join(p._bank, "profile.md"), "w").write(PROFILE)
    l1 = []
    for t, c, src in RECORDS:
        for s in src:
            l1.append({"id": s, "role": "user", "content": f"backing: {c}"})
    with open(os.path.join(p._bank, "raw.jsonl"), "w") as fh:
        for r in l1:
            fh.write(json.dumps(r) + "\n")
    p._append_records([p._make_record(t, c, src) for t, c, src in RECORDS])
    return p, tmp


def reachable(model):
    p, tmp = setup(model)
    ok = p._call_memory_model("ping", "Return the JSON {}.") is not None
    shutil.rmtree(tmp, ignore_errors=True)
    return ok


def one_sample(model):
    """One pass. Returns (raw_proposed, grounded_proposed, leaks, identity_hit, latency_ms)."""
    p, tmp = setup(model)
    valid = {r.get("id") for r in p._read_records()}
    captured = {}
    orig = p._call_memory_model
    def wrap(system, user):
        r = orig(system, user); captured["raw"] = r; return r
    p._call_memory_model = wrap
    t0 = time.time()
    p._sm_set_records_seen(0)
    p._run_self_model_pass()
    latency = int((time.time() - t0) * 1000)

    # what the model RAW-proposed
    raw_proposed, grounded_proposed = 0, 0
    plan = p._parse_plan(captured.get("raw") or "") or {}
    for sf in (plan.get("self_facts") or []):
        if not isinstance(sf, dict) or not str(sf.get("claim", "")).strip():
            continue
        raw_proposed += 1
        ev = [e for e in (sf.get("evidence") or []) if e in valid]
        if ev:
            grounded_proposed += 1
    # what ACTUALLY entered the bank + leak check
    accepted = p._read_self_facts()
    leaks = sum(1 for f in accepted if not [e for e in f.get("evidence", []) if e in valid])
    identity_hit = any("pal" in f["claim"].lower() for f in accepted)
    shutil.rmtree(tmp, ignore_errors=True)
    return raw_proposed, grounded_proposed, leaks, identity_hit, latency


results = []
for m in MODELS:
    name = SHORT.get(m, m)
    print(f"\n== {name} ==")
    if not reachable(m):
        print("  unreachable — skipping")
        results.append({"model": name, "reachable": False})
        continue
    raw_t = gr_t = leak_t = hit_t = lat_t = 0
    for k in range(K):
        rp, gp, lk, hit, lat = one_sample(m)
        raw_t += rp; gr_t += gp; leak_t += lk; hit_t += int(hit); lat_t += lat
        print(f"  sample {k+1}: raw_proposed={rp} grounded={gp} leaks={lk} identity={'Y' if hit else '-'} {lat}ms")
    results.append({
        "model": name, "reachable": True, "samples": K,
        "avg_proposed": round(raw_t / K, 1),
        "avg_grounded": round(gr_t / K, 1),
        "rejected_by_scaffold": raw_t - gr_t,
        "leaks": leak_t,                         # MUST be 0 (safety)
        "identity_recall": round(hit_t / K, 2),  # VARIES (quality)
        "avg_latency_ms": round(lat_t / K),
    })

out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "agnosticism_results.json")
open(out, "w").write(json.dumps(results, indent=2))
print("\n===== SUMMARY =====")
print(f"{'model':14} {'reach':6} {'recall':7} {'leaks':6} {'rejected':9} {'proposed':9} {'ms':6}")
for r in results:
    if not r.get("reachable"):
        print(f"{r['model']:14} {'no':6}")
        continue
    print(f"{r['model']:14} {'yes':6} {r['identity_recall']:<7} {r['leaks']:<6} "
          f"{r['rejected_by_scaffold']:<9} {r['avg_proposed']:<9} {r['avg_latency_ms']:<6}")
leaks_total = sum(r.get("leaks", 0) for r in results)
print(f"\nSAFETY: total leaks across ALL models = {leaks_total}  (0 == architecture agnostic)")
print(f"QUALITY: identity_recall ranges "
      f"{min((r['identity_recall'] for r in results if r.get('reachable')), default=0)}"
      f"–{max((r['identity_recall'] for r in results if r.get('reachable')), default=0)}  (varies == model-dependent)")
print(f"\nwrote {out}")
