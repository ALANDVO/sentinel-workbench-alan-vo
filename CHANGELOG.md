# Changelog

## 1.1.0 — work-in-progress checkpoint

Partial code published for continued development. Known issues: STATUS.md.

## 1.0.0 — work-in-progress checkpoint

Partial code published for continued development. Known issues: STATUS.md.

All notable changes to `sentinel-workbench-alan-vo` are documented in this file.

## [1.0.0] - 2026-10-15

### Added
- Created incremental development roadmap (`feature-plan.json`, `PLAN.md`, `STATUS.md`).
- Implemented `session-memory-topic-slicing-search`:
  - SQLite-backed persistence (`backend/app/core/database.py`) for multi-session agent trajectories, verbatim turns, failure episode metadata, and audit logs.
  - Deterministic semantic topic boundary and failure-recovery slicer (`backend/app/services/slicer.py`) paired against a fixed-token-window baseline chunker.
  - Hybrid sparse (BM25) + dense (character/word n-gram cosine similarity) retrieval engine (`backend/app/services/retrieval.py`) with failure-turn retention weighting and token efficiency estimation against raw `grep` line scans.
  - Reproducible evaluation runner reporting Recall@1, Mean Reciprocal Rank (MRR), Wilson 95% confidence intervals, and candidate self-mask (`fill_diagonal`) sanity verification.
  - React + TypeScript + Vite workbench frontend (`frontend/src/App.tsx`) with trajectory ingestion, slice inspection, comparative search, and evaluation artifact export.
