"""Pydantic schemas for Sentinel Workbench."""

from __future__ import annotations

from typing import List, Literal, Optional
from pydantic import BaseModel, Field


class SessionTurnInput(BaseModel):
    turn_index: int = Field(..., ge=0, description="Zero-based index of the turn in the session")
    role: Literal["agent", "tool", "user", "system"] = Field(default="agent")
    timestamp: str = Field(..., min_length=1, description="ISO-8601 UTC timestamp")
    command_or_tool: str = Field(default="", description="Tool or command executed in this turn")
    content: str = Field(..., min_length=1, description="Verbatim turn content or log output")
    is_failure: bool = Field(default=False, description="Whether this turn recorded an error or failed attempt")
    error_code: Optional[str] = Field(default=None, description="Optional structured error code or signal")


class SessionCreateRequest(BaseModel):
    session_id: str = Field(..., min_length=2, max_length=120, pattern=r"^[a-zA-Z0-9._-]+$")
    title: str = Field(..., min_length=3, max_length=200)
    repository: str = Field(default="workspace/default", min_length=1, max_length=160)
    environment_tag: str = Field(default="staging", min_length=1, max_length=64)
    turns: List[SessionTurnInput] = Field(..., min_length=1)
    target_window_tokens: int = Field(default=55, ge=20, le=500)
    topic_drift_threshold: float = Field(default=0.22, ge=0.05, le=0.85)


class SliceRecord(BaseModel):
    slice_id: str
    session_id: str
    strategy: Literal["semantic_topic", "fixed_window"]
    slice_index: int
    start_turn: int
    end_turn: int
    turn_count: int
    token_count: int
    has_failure_turn: bool
    failure_turn_count: int
    dominant_terms: List[str]
    boundary_reason: str
    text: str


class SessionSummary(BaseModel):
    session_id: str
    title: str
    repository: str
    environment_tag: str
    turn_count: int
    failure_turn_count: int
    raw_token_count: int
    semantic_slice_count: int
    fixed_slice_count: int
    created_at: str


class SessionDetail(SessionSummary):
    turns: List[SessionTurnInput]
    semantic_slices: List[SliceRecord]
    fixed_slices: List[SliceRecord]


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=2, max_length=400, description="Situation or imperative agent query")
    slicing_strategy: Literal["semantic_topic", "fixed_window"] = Field(default="semantic_topic")
    scoring_mode: Literal["hybrid", "bm25", "dense"] = Field(default="hybrid")
    top_k: int = Field(default=5, ge=1, le=25)
    failure_boost: float = Field(default=0.25, ge=0.0, le=1.0)


class SearchHit(BaseModel):
    rank: int
    slice_id: str
    session_id: str
    session_title: str
    strategy: str
    start_turn: int
    end_turn: int
    score: float
    bm25_score: float
    dense_score: float
    failure_bonus: float
    has_failure_turn: bool
    boundary_reason: str
    dominant_terms: List[str]
    token_count: int
    snippet: str


class SearchComparisonResponse(BaseModel):
    query: str
    scoring_mode: str
    selected_strategy: str
    hits: List[SearchHit]
    counterpart_strategy: str
    counterpart_hits: List[SearchHit]
    corpus_total_tokens: int
    grep_matched_line_tokens: int
    retrieved_top1_tokens: int
    token_reduction_ratio_vs_corpus: float
    token_reduction_ratio_vs_grep: float


class EvalCaseResult(BaseModel):
    case_id: str
    situation_query: str
    expected_session_id: str
    expected_turn_index: int
    requires_failure_context: bool
    semantic_top1_slice_id: Optional[str]
    semantic_hit_at_1: bool
    semantic_reciprocal_rank: float
    fixed_top1_slice_id: Optional[str]
    fixed_hit_at_1: bool
    fixed_reciprocal_rank: float


class EvalReportResponse(BaseModel):
    benchmark_name: str
    num_queries: int
    scoring_mode: str
    semantic_recall_at_1: float
    semantic_recall_ci95_low: float
    semantic_recall_ci95_high: float
    semantic_mrr: float
    fixed_window_recall_at_1: float
    fixed_window_recall_ci95_low: float
    fixed_window_recall_ci95_high: float
    fixed_window_mrr: float
    failure_turn_retention_rate: float
    mean_token_reduction_vs_grep: float
    candidate_mask_integrity_ok: bool
    diagonal_mask_bug_simulated_recall: float
    cases: List[EvalCaseResult]


class AuditLogEntry(BaseModel):
    id: int
    action: str
    entity_id: str
    details: str
    created_at: str
