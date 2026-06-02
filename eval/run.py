"""Qualifier quality GATE.

Runs the Qualifier (with the configured LLM — Ollama/gemma4:e2b by default) over a
labelled dataset of company-page snippets and measures precision/recall against
the prospecting goal. Also reports the agentic failure modes the dataset targets:
hallucinated signals, non-company pages, and excluded/no-signal companies.

Usage:
    python -m eval.run            # uses default_config() goal/ICP
    python -m eval.run --threshold 55

GATE: keep precision >= 0.70 after any change to the Qualifier prompt.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from prospect.config import default_config
from prospect.engine import contacts as contacts_mod
from prospect.engine import qualifier
from prospect.llm.base import get_provider

DATASET = Path(__file__).parent / "dataset.jsonl"
GATE_PRECISION = 0.70


def load_dataset() -> list[dict]:
    rows = []
    for line in DATASET.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--threshold", type=int, default=None)
    args = ap.parse_args()

    cfg = default_config()
    threshold = args.threshold if args.threshold is not None else cfg.scoring.threshold
    llm = get_provider(cfg.llm, "strong")  # strong tier if configured, else light

    rows = load_dataset()
    tp = fp = tn = fn = 0
    hallucinations = 0  # not_company/no_signal that wrongly scored a verified signal high
    print(f"\nGATE — Qualifier @ threshold {threshold}  ({cfg.llm.provider}:{cfg.llm.model})\n")
    print(f"{'id':28} {'kind':12} {'exp':4} {'score':5} {'sig':3} {'verdict':8} result")
    print("-" * 78)

    for r in rows:
        c = contacts_mod.extract(r.get("text", ""), [], f"https://{(r.get('company') or 'x').lower().replace(' ','')}.example")
        ev = qualifier.evaluate(llm, cfg, r["text"], contacts=c, source_url="https://example.test")
        predicted = ev["score"] >= threshold
        expected = bool(r["expected_match"])
        if predicted and expected:
            tp += 1; res = "TP ✓"
        elif predicted and not expected:
            fp += 1; res = "FP ✗"
        elif not predicted and not expected:
            tn += 1; res = "TN ✓"
        else:
            fn += 1; res = "FN ✗"
        if r["kind"] in ("not_company", "no_signal") and predicted:
            hallucinations += 1
        print(f"{r['id']:28} {r['kind']:12} {str(expected):4} {ev['score']:<5} "
              f"{'Y' if ev['signal_verified'] else 'n':3} {ev['verdict']:8} {res}")

    precision = tp / (tp + fp) if (tp + fp) else 1.0
    recall = tp / (tp + fn) if (tp + fn) else 1.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    print("-" * 78)
    print(f"TP={tp} FP={fp} TN={tn} FN={fn}")
    print(f"Precision={precision:.2f}  Recall={recall:.2f}  F1={f1:.2f}")
    print(f"False positives on not-a-company / no-signal pages: {hallucinations}")

    passed = precision >= GATE_PRECISION
    print(f"\n{'✅ GATE PASSED' if passed else '❌ GATE FAILED'} "
          f"(precision {precision:.2f} {'>=' if passed else '<'} {GATE_PRECISION})\n")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
