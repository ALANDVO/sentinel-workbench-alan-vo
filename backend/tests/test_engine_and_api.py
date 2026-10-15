"""End-to-end unit and API tests for Sentinel Workbench."""

from __future__ import annotations

from pathlib import Path
from fastapi.testclient import TestClient
import pytest

from app.core.database import init_db
from app.main import create_app
from app.models.schemas import SessionTurnInput
from app.services.retrieval import (
    estimate_grep_tokens,
    rank_slices,
    wilson_confidence_interval,
)
from app.services.slicer import (
    build_fixed_window_slices,
    build_semantic_topic_slices,
    tokenize_terms,
)


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    db_file = str(tmp_path / "test_sentinel.db")
    monkeypatch.setenv("SENTINEL_DB_PATH", db_file)
    init_db(db_file)
    app = create_app()
    return TestClient(app)


def test_health_and_seed_corpus(client: TestClient) -> None:
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["app"] == "sentinel-workbench-alan-vo"
    assert body["indexed_sessions"] >= 4
    assert body["semantic_slices"] >= 8
    assert body["corpus_tokens"] > 100


def test_semantic_slicer_preserves_failure_recovery_pair() -> None:
    turns = [
        SessionTurnInput(
            turn_index=0,
            role="agent",
            timestamp="2026-10-10T10:00:00Z",
            command_or_tool="git status",
            content="Checking repository workspace branch cleanliness and local modified files.",
            is_failure=False,
        ),
        SessionTurnInput(
            turn_index=1,
            role="tool",
            timestamp="2026-10-10T10:01:00Z",
            command_or_tool="git diff",
            content="Verified workspace branch cleanliness with zero untracked build files.",
            is_failure=False,
        ),
        SessionTurnInput(
            turn_index=2,
            role="tool",
            timestamp="2026-10-10T10:05:00Z",
            command_or_tool="pytest backend/tests",
            content="Database migration failed with SQLite OperationalError locked table on concurrent writer.",
            is_failure=True,
            error_code="SQLITE_LOCKED",
        ),
        SessionTurnInput(
            turn_index=3,
            role="agent",
            timestamp="2026-10-10T10:06:00Z",
            command_or_tool="pytest backend/tests",
            content="Resolved SQLite OperationalError locked table by enabling WAL journal mode on connection.",
            is_failure=False,
        ),
    ]
    sem_slices = build_semantic_topic_slices("sess-unit", turns, target_window_tokens=40, topic_drift_threshold=0.22)
    fix_slices = build_fixed_window_slices("sess-unit", turns, target_window_tokens=25)

    assert len(sem_slices) == 2
    failure_slice = next(s for s in sem_slices if s.has_failure_turn)
    assert failure_slice.start_turn == 2
    assert failure_slice.end_turn == 3
    assert len(fix_slices) >= 2


def test_create_get_and_delete_session_workflow(client: TestClient) -> None:
    payload = {
        "session_id": "sess-custom-debug-99",
        "title": "Redis TLS Handshake Failure & Cert Chain Rotation",
        "repository": "org/cache-router",
        "environment_tag": "production",
        "target_window_tokens": 50,
        "topic_drift_threshold": 0.22,
        "turns": [
            {
                "turn_index": 0,
                "role": "tool",
                "timestamp": "2026-10-12T08:00:00Z",
                "command_or_tool": "redis-cli --tls ping",
                "content": "TLS handshake failed with x509 certificate signed by unknown authority on cache-node-3.",
                "is_failure": True,
                "error_code": "TLS_X509_UNKNOWN_CA",
            },
            {
                "turn_index": 1,
                "role": "agent",
                "timestamp": "2026-10-12T08:02:00Z",
                "command_or_tool": "kubectl create secret generic redis-ca",
                "content": "Rotated intermediate CA bundle secret and verified redis-cli TLS ping succeeded.",
                "is_failure": False,
            },
        ],
    }
    create_resp = client.post("/api/sessions", json=payload)
    assert create_resp.status_code == 201
    created = create_resp.json()
    assert created["session_id"] == "sess-custom-debug-99"
    assert created["failure_turn_count"] == 1
    assert len(created["semantic_slices"]) >= 1

    detail_resp = client.get("/api/sessions/sess-custom-debug-99")
    assert detail_resp.status_code == 200
    assert detail_resp.json()["title"] == payload["title"]

    search_resp = client.post(
        "/api/search",
        json={
            "query": "TLS handshake failed x509 unknown authority on redis cache",
            "slicing_strategy": "semantic_topic",
            "scoring_mode": "hybrid",
            "top_k": 3,
            "failure_boost": 0.25,
        },
    )
    assert search_resp.status_code == 200
    search_data = search_resp.json()
    assert len(search_data["hits"]) >= 1
    assert search_data["hits"][0]["session_id"] == "sess-custom-debug-99"
    assert search_data["token_reduction_ratio_vs_grep"] > 1.0

    del_resp = client.delete("/api/sessions/sess-custom-debug-99")
    assert del_resp.status_code == 200
    assert del_resp.json()["deleted"] is True

    missing_resp = client.get("/api/sessions/sess-custom-debug-99")
    assert missing_resp.status_code == 404


def test_list_sessions_filtering_and_pagination(client: TestClient) -> None:
    filtered = client.get("/api/sessions?repository=org/search-engine")
    assert filtered.status_code == 200
    items = filtered.json()
    assert len(items) == 2
    assert all(item["repository"] == "org/search-engine" for item in items)

    paged = client.get("/api/sessions?limit=2&offset=1")
    assert paged.status_code == 200
    assert len(paged.json()) == 2


def test_search_bm25_and_dense_modes(client: TestClient) -> None:
    for mode in ("bm25", "dense", "hybrid"):
        resp = client.post(
            "/api/search",
            json={
                "query": "thread xerj-drain-free panicked failed to allocate alternative stack ENOMEM",
                "slicing_strategy": "semantic_topic",
                "scoring_mode": mode,
                "top_k": 4,
                "failure_boost": 0.25,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["scoring_mode"] == mode
        assert data["hits"][0]["session_id"] == "sess-memtable-abort-02"
        assert data["counterpart_strategy"] == "fixed_window"


def test_search_fixed_window_primary_selection(client: TestClient) -> None:
    resp = client.post(
        "/api/search",
        json={
            "query": "decision flywheel write-back freezes after 12 cached answers",
            "slicing_strategy": "fixed_window",
            "scoring_mode": "hybrid",
            "top_k": 3,
            "failure_boost": 0.2,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["selected_strategy"] == "fixed_window"
    assert data["counterpart_strategy"] == "semantic_topic"
    assert len(data["hits"]) > 0


def test_benchmark_evaluation_and_mask_integrity(client: TestClient) -> None:
    resp = client.post("/api/eval/run?scoring_mode=hybrid")
    assert resp.status_code == 200
    report = resp.json()
    assert report["num_queries"] == 6
    assert report["semantic_recall_at_1"] > report["fixed_window_recall_at_1"]
    assert report["semantic_recall_at_1"] >= 0.80
    assert report["candidate_mask_integrity_ok"] is True
    assert report["diagonal_mask_bug_simulated_recall"] == 0.0
    assert report["mean_token_reduction_vs_grep"] > 2.0


def test_candidate_exclusion_mask_reproduces_zero_recall(client: TestClient) -> None:
    detail = client.get("/api/sessions/sess-auth-rollout-01").json()
    from app.models.schemas import SliceRecord

    slices = [SliceRecord(**s) for s in detail["semantic_slices"]]
    all_ids = {s.slice_id for s in slices}
    masked = rank_slices(
        "deploy failed with 401 audience mismatch",
        slices,
        {"sess-auth-rollout-01": detail["title"]},
        exclude_slice_ids=all_ids,
    )
    assert masked == []


def test_malformed_session_input_rejected(client: TestClient) -> None:
    bad_payload = {
        "session_id": "invalid id with spaces!",
        "title": "Short",
        "turns": [],
    }
    resp = client.post("/api/sessions", json=bad_payload)
    assert resp.status_code == 422


def test_delete_nonexistent_session_returns_404(client: TestClient) -> None:
    resp = client.delete("/api/sessions/does-not-exist-000")
    assert resp.status_code == 404


def test_wilson_confidence_interval_bounds_and_zero_total() -> None:
    assert wilson_confidence_interval(0, 0) == (0.0, 0.0)
    low, high = wilson_confidence_interval(5, 6)
    assert 0.40 <= low <= 0.85
    assert 0.85 <= high <= 1.0


def test_tokenizer_and_grep_estimator_edge_cases() -> None:
    terms = tokenize_terms("the and HTTP/401 error_code=AUTH_401")
    assert "the" not in terms
    assert "http/401" in terms
    assert estimate_grep_tokens("", [], 500) == 500


def test_audit_log_records_operations(client: TestClient) -> None:
    resp = client.get("/api/audit-logs?limit=10")
    assert resp.status_code == 200
    logs = resp.json()
    assert len(logs) >= 4
    assert any("seed_session_indexed" in entry["action"] for entry in logs)
