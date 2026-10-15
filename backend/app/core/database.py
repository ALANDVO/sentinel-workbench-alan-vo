"""SQLite persistence layer and seed corpus loader for Sentinel Workbench."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Dict, List, Optional

from app.core.config import get_settings
from app.models.schemas import (
    AuditLogEntry,
    SessionCreateRequest,
    SessionDetail,
    SessionSummary,
    SessionTurnInput,
    SliceRecord,
)
from app.services.slicer import (
    build_fixed_window_slices,
    build_semantic_topic_slices,
    count_whitespace_tokens,
    format_slice_text,
)


SEED_SESSIONS: List[SessionCreateRequest] = [
    SessionCreateRequest(
        session_id="sess-auth-rollout-01",
        title="Staging Gateway OIDC Rollout & 401 Audience Mismatch Recovery",
        repository="org/gateway-proxy",
        environment_tag="staging",
        target_window_tokens=45,
        topic_drift_threshold=0.22,
        turns=[
            SessionTurnInput(
                turn_index=0,
                role="agent",
                timestamp="2026-10-04T09:10:00Z",
                command_or_tool="kubectl rollout status deployment/gateway",
                content="Inspecting staging gateway pod readiness and TLS ingress certificate bindings before enabling OIDC token verification.",
                is_failure=False,
            ),
            SessionTurnInput(
                turn_index=1,
                role="tool",
                timestamp="2026-10-04T09:11:12Z",
                command_or_tool="kubectl logs deployment/gateway",
                content="Ingress TLS listener active on 8443; upstream health check passing against auth discovery endpoint.",
                is_failure=False,
            ),
            SessionTurnInput(
                turn_index=2,
                role="tool",
                timestamp="2026-10-04T09:14:05Z",
                command_or_tool="deploy-gateway --env staging",
                content="Deploy failed again with HTTP 401 Unauthorized: JWT audience claim mismatch (expected api://staging-gateway, received account-console) during OIDC token introspection.",
                is_failure=True,
                error_code="AUTH_401_AUDIENCE_MISMATCH",
            ),
            SessionTurnInput(
                turn_index=3,
                role="agent",
                timestamp="2026-10-04T09:15:30Z",
                command_or_tool="deploy-gateway --set oidc.audience=api://staging-gateway",
                content="Resolved staging 401 deploy failure by aligning Keycloak client audience mapper to api://staging-gateway and re-running rollout verification.",
                is_failure=False,
            ),
            SessionTurnInput(
                turn_index=4,
                role="agent",
                timestamp="2026-10-04T09:22:00Z",
                command_or_tool="prometheus-query http_request_duration_seconds",
                content="Auditing p99 latency histograms and connection pool idle eviction metrics across edge worker nodes.",
                is_failure=False,
            ),
        ],
    ),
    SessionCreateRequest(
        session_id="sess-memtable-abort-02",
        title="Index Engine Memtable Drain Thread SIGABRT Under RSS Pressure",
        repository="org/search-engine",
        environment_tag="production-canary",
        target_window_tokens=45,
        topic_drift_threshold=0.22,
        turns=[
            SessionTurnInput(
                turn_index=0,
                role="agent",
                timestamp="2026-10-05T14:00:00Z",
                command_or_tool="cargo bench --bench segment_merge",
                content="Profiling segment compaction throughput across 6,168 open shards with elevated process memory ceiling.",
                is_failure=False,
            ),
            SessionTurnInput(
                turn_index=1,
                role="tool",
                timestamp="2026-10-05T14:03:20Z",
                command_or_tool="vmstat -s",
                content="Process RSS reached 95,400 MB as per-segment caches remained pinned awaiting background merge retirement.",
                is_failure=False,
            ),
            SessionTurnInput(
                turn_index=2,
                role="tool",
                timestamp="2026-10-05T14:05:11Z",
                command_or_tool="xerj-server --data-dir /var/lib/index",
                content="Process died exit 134 SIGABRT: thread xerj-drain-free panicked failed to allocate an alternative stack Cannot allocate memory os error 12 ENOMEM during std::thread::Builder::spawn with panic=abort.",
                is_failure=True,
                error_code="SIGABRT_134_DRAIN_FREE_ENOMEM",
            ),
            SessionTurnInput(
                turn_index=3,
                role="agent",
                timestamp="2026-10-05T14:08:45Z",
                command_or_tool="patch engine/src/memtable.rs",
                content="Mitigated SIGABRT by checking memory governor headroom before spawning xerj-drain-free thread and dropping retired Arc segments inline when near ENOMEM watermark.",
                is_failure=False,
            ),
        ],
    ),
    SessionCreateRequest(
        session_id="sess-ingest-breaker-03",
        title="Multi-Index Bulk Ingest Breaker Oscillation & Finalize Exists Probe Scan",
        repository="org/search-engine",
        environment_tag="benchmark",
        target_window_tokens=45,
        topic_drift_threshold=0.22,
        turns=[
            SessionTurnInput(
                turn_index=0,
                role="agent",
                timestamp="2026-10-08T11:20:00Z",
                command_or_tool="autoindex ingest --corpus cve-records",
                content="Starting multi-index bulk ingestion of 402,695 CVE JSON records across 118 staging index sets.",
                is_failure=False,
            ),
            SessionTurnInput(
                turn_index=1,
                role="tool",
                timestamp="2026-10-08T12:10:00Z",
                command_or_tool="autoindex ingest --status",
                content="Throughput degraded to 34 items/s: 6,728 memory circuit breaker trips at 16GB watermark caused bulk concurrency to yo-yo 32 to 1 to 32 across synchronized clients.",
                is_failure=True,
                error_code="MEM_BREAKER_429_OSCILLATION",
            ),
            SessionTurnInput(
                turn_index=2,
                role="agent",
                timestamp="2026-10-08T12:25:00Z",
                command_or_tool="autoindex configure --admission per-shard",
                content="Added per-shard admission control and server target-concurrency pushback headers with decorrelated client backoff jitter to stabilize bulk ingest throughput.",
                is_failure=False,
            ),
            SessionTurnInput(
                turn_index=3,
                role="agent",
                timestamp="2026-10-08T14:30:00Z",
                command_or_tool="autoindex finalize-catalog --resume",
                content="Running catalog generation read-back walk after reindexing run-id generation across catalog documents.",
                is_failure=False,
            ),
            SessionTurnInput(
                turn_index=4,
                role="tool",
                timestamp="2026-10-08T15:40:00Z",
                command_or_tool="autoindex finalize-catalog --trace-queries",
                content="Finalize catalog resume stalled brute-scanning 3.4s per ax_file term + exists probe query with zero hits (2,619 empty probes) on server missing columnar exists fast path.",
                is_failure=True,
                error_code="SLOW_EXISTS_PROBE_BRUTE_SCAN",
            ),
            SessionTurnInput(
                turn_index=5,
                role="agent",
                timestamp="2026-10-08T15:55:00Z",
                command_or_tool="autoindex preflight-probe --check-exists-lane",
                content="Added pre-phase one-query latency probe to detect missing columnar exists fast path at minute zero and route zero-hit probes through bitmap index.",
                is_failure=False,
            ),
        ],
    ),
    SessionCreateRequest(
        session_id="sess-flywheel-cache-04",
        title="Decision Flywheel Write-Back Freeze & Eval Diagonal Mask Bug",
        repository="org/eval-harness",
        environment_tag="evaluation",
        target_window_tokens=45,
        topic_drift_threshold=0.22,
        turns=[
            SessionTurnInput(
                turn_index=0,
                role="agent",
                timestamp="2026-10-09T16:00:00Z",
                command_or_tool="python replay_decisions.py --fill 2000",
                content="Running Banking77 decision flywheel replay to populate 2,000 hosted answers into history index.",
                is_failure=False,
            ),
            SessionTurnInput(
                turn_index=1,
                role="tool",
                timestamp="2026-10-09T16:12:00Z",
                command_or_tool="python inspect_flywheel_cache.py",
                content="Decision flywheel write-back froze after caching only 12 of 2,000 fill answers because /_decide answered from tier-1 BM25 history vote without persisting tier-2/tier-3hosted write-backs.",
                is_failure=True,
                error_code="FLYWHEEL_WRITEBACK_FREEZE",
            ),
            SessionTurnInput(
                turn_index=2,
                role="agent",
                timestamp="2026-10-09T16:20:00Z",
                command_or_tool="patch services/decision_flywheel.py",
                content="Fixed decision flywheel write-back policy so every hosted fill and low-margin history decision persists to the history index until support threshold stabilizes.",
                is_failure=False,
            ),
            SessionTurnInput(
                turn_index=3,
                role="agent",
                timestamp="2026-10-09T17:05:00Z",
                command_or_tool="pytest benchmarks/test_retrieval_eval.py",
                content="Preparing paired McNemar retrieval evaluation matrix across session memory embeddings.",
                is_failure=False,
            ),
            SessionTurnInput(
                turn_index=4,
                role="tool",
                timestamp="2026-10-09T17:08:00Z",
                command_or_tool="python run_eval_matrix.py",
                content="Retrieval benchmark evaluation returned constant zero hits across all queries because similarity matrix fill_diagonal mask accidentally excluded gold positive pairs from the candidate pool.",
                is_failure=True,
                error_code="EVAL_DIAGONAL_MASK_ZERO_HITS",
            ),
            SessionTurnInput(
                turn_index=5,
                role="agent",
                timestamp="2026-10-09T17:15:00Z",
                command_or_tool="patch benchmarks/run_eval_matrix.py",
                content="Removed candidate self-exclusion fill_diagonal mask on query-to-corpus rectangular matrix and added automated pre-eval mask sanity gate.",
                is_failure=False,
            ),
        ],
    ),
]


def _connect(db_path: Optional[str] = None) -> sqlite3.Connection:
    resolved = db_path or get_settings().db_path
    if resolved != ":memory:":
        path_obj = Path(resolved)
        path_obj.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(resolved)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Optional[str] = None) -> None:
    with _connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                repository TEXT NOT NULL,
                environment_tag TEXT NOT NULL,
                turn_count INTEGER NOT NULL,
                failure_turn_count INTEGER NOT NULL,
                raw_token_count INTEGER NOT NULL,
                semantic_slice_count INTEGER NOT NULL,
                fixed_slice_count INTEGER NOT NULL,
                turns_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS slices (
                slice_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                strategy TEXT NOT NULL,
                slice_index INTEGER NOT NULL,
                start_turn INTEGER NOT NULL,
                end_turn INTEGER NOT NULL,
                turn_count INTEGER NOT NULL,
                token_count INTEGER NOT NULL,
                has_failure_turn INTEGER NOT NULL,
                failure_turn_count INTEGER NOT NULL,
                dominant_terms_json TEXT NOT NULL,
                boundary_reason TEXT NOT NULL,
                text TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                details TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        row = conn.execute("SELECT COUNT(*) AS cnt FROM sessions").fetchone()
        if row and int(row["cnt"]) == 0:
            for seed in SEED_SESSIONS:
                _upsert_session_in_tx(conn, seed, action_label="seed_session_indexed")


def _upsert_session_in_tx(
    conn: sqlite3.Connection,
    payload: SessionCreateRequest,
    action_label: str = "session_indexed",
) -> SessionDetail:
    ordered_turns = sorted(payload.turns, key=lambda x: x.turn_index)
    full_text = format_slice_text(ordered_turns)
    raw_tokens = count_whitespace_tokens(full_text)
    failure_count = sum(1 for t in ordered_turns if t.is_failure)

    sem_slices = build_semantic_topic_slices(
        session_id=payload.session_id,
        turns=ordered_turns,
        target_window_tokens=payload.target_window_tokens,
        topic_drift_threshold=payload.topic_drift_threshold,
    )
    fix_slices = build_fixed_window_slices(
        session_id=payload.session_id,
        turns=ordered_turns,
        target_window_tokens=payload.target_window_tokens,
    )

    now_iso = datetime.now(timezone.utc).isoformat()
    turns_serialized = json.dumps([t.model_dump() for t in ordered_turns])

    conn.execute("DELETE FROM slices WHERE session_id = ?", (payload.session_id,))
    conn.execute(
        """
        INSERT OR REPLACE INTO sessions (
            session_id, title, repository, environment_tag,
            turn_count, failure_turn_count, raw_token_count,
            semantic_slice_count, fixed_slice_count, turns_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            payload.session_id,
            payload.title,
            payload.repository,
            payload.environment_tag,
            len(ordered_turns),
            failure_count,
            raw_tokens,
            len(sem_slices),
            len(fix_slices),
            turns_serialized,
            now_iso,
        ),
    )

    for sl in sem_slices + fix_slices:
        conn.execute(
            """
            INSERT INTO slices (
                slice_id, session_id, strategy, slice_index,
                start_turn, end_turn, turn_count, token_count,
                has_failure_turn, failure_turn_count, dominant_terms_json,
                boundary_reason, text
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                sl.slice_id,
                sl.session_id,
                sl.strategy,
                sl.slice_index,
                sl.start_turn,
                sl.end_turn,
                sl.turn_count,
                sl.token_count,
                1 if sl.has_failure_turn else 0,
                sl.failure_turn_count,
                json.dumps(sl.dominant_terms),
                sl.boundary_reason,
                sl.text,
            ),
        )

    conn.execute(
        """
        INSERT INTO audit_logs (action, entity_id, details, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (
            action_label,
            payload.session_id,
            f"Indexed {len(ordered_turns)} turns ({failure_count} failures) into {len(sem_slices)} semantic slices and {len(fix_slices)} fixed slices",
            now_iso,
        ),
    )

    return SessionDetail(
        session_id=payload.session_id,
        title=payload.title,
        repository=payload.repository,
        environment_tag=payload.environment_tag,
        turn_count=len(ordered_turns),
        failure_turn_count=failure_count,
        raw_token_count=raw_tokens,
        semantic_slice_count=len(sem_slices),
        fixed_slice_count=len(fix_slices),
        created_at=now_iso,
        turns=ordered_turns,
        semantic_slices=sem_slices,
        fixed_slices=fix_slices,
    )


def upsert_session(payload: SessionCreateRequest, db_path: Optional[str] = None) -> SessionDetail:
    with _connect(db_path) as conn:
        return _upsert_session_in_tx(conn, payload, action_label="session_indexed")


def list_sessions(
    repository_filter: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    db_path: Optional[str] = None,
) -> List[SessionSummary]:
    with _connect(db_path) as conn:
        if repository_filter:
            rows = conn.execute(
                """
                SELECT * FROM sessions
                WHERE repository = ?
                ORDER BY created_at DESC, session_id ASC
                LIMIT ? OFFSET ?
                """,
                (repository_filter, limit, offset),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM sessions
                ORDER BY created_at DESC, session_id ASC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()

    return [
        SessionSummary(
            session_id=r["session_id"],
            title=r["title"],
            repository=r["repository"],
            environment_tag=r["environment_tag"],
            turn_count=int(r["turn_count"]),
            failure_turn_count=int(r["failure_turn_count"]),
            raw_token_count=int(r["raw_token_count"]),
            semantic_slice_count=int(r["semantic_slice_count"]),
            fixed_slice_count=int(r["fixed_slice_count"]),
            created_at=r["created_at"],
        )
        for r in rows
    ]


def get_session_detail(session_id: str, db_path: Optional[str] = None) -> Optional[SessionDetail]:
    with _connect(db_path) as conn:
        row = conn.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
        if not row:
            return None
        slice_rows = conn.execute(
            "SELECT * FROM slices WHERE session_id = ? ORDER BY slice_index ASC",
            (session_id,),
        ).fetchall()

    turns_raw = json.loads(row["turns_json"])
    turns = [SessionTurnInput(**t) for t in turns_raw]
    sem_slices: List[SliceRecord] = []
    fix_slices: List[SliceRecord] = []
    for sr in slice_rows:
        rec = _row_to_slice_record(sr)
        if rec.strategy == "semantic_topic":
            sem_slices.append(rec)
        else:
            fix_slices.append(rec)

    return SessionDetail(
        session_id=row["session_id"],
        title=row["title"],
        repository=row["repository"],
        environment_tag=row["environment_tag"],
        turn_count=int(row["turn_count"]),
        failure_turn_count=int(row["failure_turn_count"]),
        raw_token_count=int(row["raw_token_count"]),
        semantic_slice_count=int(row["semantic_slice_count"]),
        fixed_slice_count=int(row["fixed_slice_count"]),
        created_at=row["created_at"],
        turns=turns,
        semantic_slices=sem_slices,
        fixed_slices=fix_slices,
    )


def delete_session(session_id: str, db_path: Optional[str] = None) -> bool:
    with _connect(db_path) as conn:
        existing = conn.execute("SELECT session_id FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
        if not existing:
            return False
        conn.execute("DELETE FROM slices WHERE session_id = ?", (session_id,))
        conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
        conn.execute(
            "INSERT INTO audit_logs (action, entity_id, details, created_at) VALUES (?, ?, ?, ?)",
            ("session_deleted", session_id, f"Deleted session {session_id} and associated slices", datetime.now(timezone.utc).isoformat()),
        )
        return True


def load_all_slices_by_strategy(strategy: str, db_path: Optional[str] = None) -> List[SliceRecord]:
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM slices WHERE strategy = ? ORDER BY session_id ASC, slice_index ASC",
            (strategy,),
        ).fetchall()
    return [_row_to_slice_record(r) for r in rows]


def load_session_title_map(db_path: Optional[str] = None) -> Dict[str, str]:
    with _connect(db_path) as conn:
        rows = conn.execute("SELECT session_id, title FROM sessions").fetchall()
    return {r["session_id"]: r["title"] for r in rows}


def list_audit_logs(limit: int = 30, db_path: Optional[str] = None) -> List[AuditLogEntry]:
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM audit_logs ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [
        AuditLogEntry(
            id=int(r["id"]),
            action=r["action"],
            entity_id=r["entity_id"],
            details=r["details"],
            created_at=r["created_at"],
        )
        for r in rows
    ]


def _row_to_slice_record(row: sqlite3.Row) -> SliceRecord:
    return SliceRecord(
        slice_id=row["slice_id"],
        session_id=row["session_id"],
        strategy=row["strategy"],
        slice_index=int(row["slice_index"]),
        start_turn=int(row["start_turn"]),
        end_turn=int(row["end_turn"]),
        turn_count=int(row["turn_count"]),
        token_count=int(row["token_count"]),
        has_failure_turn=bool(row["has_failure_turn"]),
        failure_turn_count=int(row["failure_turn_count"]),
        dominant_terms=json.loads(row["dominant_terms_json"]),
        boundary_reason=row["boundary_reason"],
        text=row["text"],
    )
