"""FastAPI routes for agent session memory indexing, slicing, search, and evaluation."""

from __future__ import annotations

from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query

from app.core.config import get_settings
from app.core.database import (
    delete_session,
    get_session_detail,
    list_audit_logs,
    list_sessions,
    load_all_slices_by_strategy,
    load_session_title_map,
    upsert_session,
)
from app.models.schemas import (
    AuditLogEntry,
    EvalReportResponse,
    SearchComparisonResponse,
    SearchRequest,
    SessionCreateRequest,
    SessionDetail,
    SessionSummary,
)
from app.services.retrieval import (
    compare_retrieval_strategies,
    run_benchmark_evaluation,
)

router = APIRouter(prefix="/api")


@router.get("/health")
def health_check() -> dict:
    settings = get_settings()
    sessions = list_sessions(limit=100)
    total_sem_slices = sum(s.semantic_slice_count for s in sessions)
    total_tokens = sum(s.raw_token_count for s in sessions)
    return {
        "status": "ok",
        "app": settings.app_name,
        "version": settings.version,
        "environment": settings.environment,
        "indexed_sessions": len(sessions),
        "semantic_slices": total_sem_slices,
        "corpus_tokens": total_tokens,
    }


@router.get("/sessions", response_model=List[SessionSummary])
def get_sessions(
    repository: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> List[SessionSummary]:
    return list_sessions(repository_filter=repository, limit=limit, offset=offset)


@router.post("/sessions", response_model=SessionDetail, status_code=201)
def create_or_replace_session(payload: SessionCreateRequest) -> SessionDetail:
    return upsert_session(payload)


@router.get("/sessions/{session_id}", response_model=SessionDetail)
def get_session(session_id: str) -> SessionDetail:
    detail = get_session_detail(session_id)
    if not detail:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
    return detail


@router.delete("/sessions/{session_id}")
def remove_session(session_id: str) -> dict:
    removed = delete_session(session_id)
    if not removed:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
    return {"deleted": True, "session_id": session_id}


@router.post("/search", response_model=SearchComparisonResponse)
def execute_search(payload: SearchRequest) -> SearchComparisonResponse:
    sem_slices = load_all_slices_by_strategy("semantic_topic")
    fix_slices = load_all_slices_by_strategy("fixed_window")
    titles = load_session_title_map()
    return compare_retrieval_strategies(
        query=payload.query,
        semantic_slices=sem_slices,
        fixed_slices=fix_slices,
        session_titles=titles,
        slicing_strategy=payload.slicing_strategy,
        scoring_mode=payload.scoring_mode,
        top_k=payload.top_k,
        failure_boost=payload.failure_boost,
    )


@router.post("/eval/run", response_model=EvalReportResponse)
def execute_benchmark_eval(
    scoring_mode: str = Query(default="hybrid", pattern=r"^(hybrid|bm25|dense)$"),
) -> EvalReportResponse:
    sem_slices = load_all_slices_by_strategy("semantic_topic")
    fix_slices = load_all_slices_by_strategy("fixed_window")
    titles = load_session_title_map()
    return run_benchmark_evaluation(
        semantic_slices=sem_slices,
        fixed_slices=fix_slices,
        session_titles=titles,
        scoring_mode=scoring_mode,
    )


@router.get("/audit-logs", response_model=List[AuditLogEntry])
def get_audit_log_entries(limit: int = Query(default=30, ge=1, le=100)) -> List[AuditLogEntry]:
    return list_audit_logs(limit=limit)
