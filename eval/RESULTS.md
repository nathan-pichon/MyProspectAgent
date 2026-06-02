# Eval — Qualifier quality GATE

The GATE measures the Qualifier's precision/recall on a small labelled dataset of
company-page snippets (`dataset.jsonl`), scored against the default prospecting
goal (MongoDB-audit prospecting). It is the product's quality signature: **keep
precision ≥ 0.70 after any change to `prompts/qualifier.md` or `engine/qualifier.py`.**

Run it:

```bash
python -m eval.run                 # uses default_config() goal/ICP, Ollama gemma4:e2b
python -m eval.run --threshold 55
```

## Dataset design

12 examples covering the agentic failure modes the guardrails must catch:

- **match** (5) — real companies using MongoDB with a plausible audit need.
- **no_signal** (4) — real companies but no MongoDB (restaurant, Postgres-only
  SaaS, agency, ESN that merely *mentions* MongoDB) → must score low.
- **not_company** (3) — a listicle, the official MongoDB docs, and MongoDB Inc's
  own product page → must score ~0 (not-a-company / excluded-competitor gates).

## Baseline (Ollama `gemma4:e2b`, threshold 55)

| Metric | Value |
|---|---|
| Precision | **1.00** |
| Recall | **1.00** |
| F1 | **1.00** |
| False positives on not-a-company / no-signal | **0** |

The evidence-grounding guardrail (verbatim signal quotes verified against the
source text, with the Signal sub-score capped when no evidence survives) plus the
not-a-company / exclusion hard gates keep precision high even on a 2B model.

> Numbers reflect the local run on this machine; small models can vary slightly
> run-to-run. Re-run after prompt changes and keep precision ≥ 0.70.
