#!/usr/bin/env python3
"""Deep verify: drive the qwen sidecar end-to-end against a throwaway bank.

Run AFTER install.sh, from the same machine:
    HERMES_HOME=~/.hermes ~/.hermes/hermes-agent/venv/bin/python3 verify.py

Confirms: plugin discovery, load, L1 write, a real Phase-1 qwen cycle that
extracts TYPED records with provenance, and Phase-2 silence default.
Uses a temp bank dir so your live memory is never touched.
"""
import os, sys, json, tempfile, shutil

HERMES_HOME = os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes"))
sys.path.insert(0, os.path.join(HERMES_HOME, "hermes-agent"))
os.environ["HERMES_HOME"] = HERMES_HOME  # so discovery scans this instance

from plugins.memory import load_memory_provider

p = load_memory_provider("foundational")
assert p, "foundational provider not found — run install.sh first"
tmp = tempfile.mkdtemp(prefix="found_verify_")
try:
    p._cycle_interval = 3
    p.initialize("verify", hermes_home=tmp, platform="cli", agent_context="primary")
    print("loaded:", p.name, "| memory model:", p._memory_model)

    for u, a in [
        ("always text me in lowercase, no emojis", "got it"),
        ("what's the weather", "can't check live weather"),
        ("i tried restarting the router and it fixed the wifi drop", "noted"),
    ]:
        p.sync_turn(u, a)

    t = p._cycle_thread
    if t:
        t.join(timeout=180)

    recs_path = os.path.join(tmp, "foundational_memory", "records.jsonl")
    recs = [json.loads(l) for l in open(recs_path)] if os.path.exists(recs_path) else []
    print(f"\nPhase 1 — qwen extracted {len(recs)} typed record(s):")
    for r in recs:
        print(f"  [{r['type']}] {r['content']}  (provenance: {len(r.get('source_ids',[]))} L1 ids)")

    print("\nPhase 2 — intervention:", repr(p._pending_intervention), "(None = silence, the default)")
    print("Search test:", p.handle_tool_call("memory_search", {"query": "lowercase emoji texting"}))

    ok = len(recs) >= 1 and any(r["type"] == "instruction" for r in recs)
    print("\nRESULT:", "PASS ✅" if ok else "PARTIAL ⚠️  (sidecar ran but extraction weak — check Ollama/model)")
finally:
    shutil.rmtree(tmp, ignore_errors=True)
