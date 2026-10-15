# Product development plan

Each round completes one feature or repair. Future items are planned, not implemented claims.

## Current round

session-memory-topic-slicing-search

## Roadmap

### session-memory-topic-slicing-search — Semantic Topic Slicing & Hybrid Retrieval Engine for Agent Session Memory

Status: done

Acceptance:
- Ingest multi-session agent trajectories with verbatim turns, timestamps, tool calls, and failure markers persisted in SQLite
- Deterministic semantic topic boundary slicer that segments agent sessions by topic transition and failure episodes rather than fixed token windows
- Hybrid sparse (BM25) + dense (TF-IDF SVD / cosine n-gram vector) retrieval engine with failure-turn survival weighting and token efficiency estimator comparing against raw grep line scans
- FastAPI endpoints and React + TypeScript workbench UI to create/import session trajectories, inspect topic slices, run comparative retrieval (Topic vs Fixed-Window, Hybrid vs Sparse), and export results

Implementation: `backend/app/main.py`, `backend/app/core/config.py`, `backend/app/core/database.py`, `backend/app/models/schemas.py`, `backend/app/services/slicer.py`, `backend/app/services/retrieval.py`, `backend/app/api/routes.py`, `frontend/src/api/client.ts`, `frontend/src/App.tsx`, `frontend/src/components/CorpusPanel.tsx`, `frontend/src/components/SearchComparePanel.tsx`, `frontend/src/components/EvalGatePanel.tsx`

Tests: `backend/tests/test_engine_and_api.py`, `frontend/src/App.test.tsx`

### preregistered-retrieval-eval-gates — Preregistered Retrieval Evaluation & Mask-Integrity Gate Verification

Status: planned

Acceptance:
- Freeze preregistered evaluation criteria (Recall@1, MRR, failure-turn recall, majority-class baseline, Wilson 95% confidence intervals, paired McNemar comparison)
- Self-mask / fill_diagonal candidate exclusion detector that catches candidate-pool self-exclusion bugs
- Separate self-report and independent recompute artifacts with explicit measured/inferred/unverifiable claim labels

### ingest-admission-governor-simulator — Per-Shard Memory Admission Governor & Decorrelated Backoff Simulator

Status: planned

Acceptance:
- Simulate multi-index bulk ingest against parent RSS vs per-shard admission watermarks
- Compute target concurrency pushback headers and decorrelated jitter ramp schedules to prevent synchronized 32->1->32 concurrency collapses
- Check memory headroom before background drain-free thread spawns and fall back to inline drop under pressure

### decision-flywheel-writeback-audit — Decision Flywheel Cache Write-Back & Latency Probe Diagnostics

Status: planned

Acceptance:
- Audit tiered decision cache write-back behavior across BM25 history vote vs hosted fallback tiers
- Pre-flight capability latency probe for exists/columnar query lanes before catalog finalization walks

### oidc-keycloak-auth-and-llm-advisory — Keycloak OIDC PKCE Authentication & Opt-In Multi-Provider LLM Grounded Advisory

Status: planned

Acceptance:
- OIDC authorization-code + PKCE authentication flow with Keycloak realm configuration and role-based access control
- Opt-in server-side LLM advisory adapter supporting OpenAI-compatible, Anthropic, and Gemini endpoints with strict grounding on retrieved slices

