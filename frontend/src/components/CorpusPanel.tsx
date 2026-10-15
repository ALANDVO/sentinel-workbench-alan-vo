import React, { useState } from "react";
import {
  SessionCreateRequest,
  SessionDetail,
  SessionSummary,
  SliceRecord,
} from "../api/client";

interface CorpusPanelProps {
  sessions: SessionSummary[];
  selectedSession: SessionDetail | null;
  onSelectSession: (sessionId: string) => void;
  onCreateSession: (payload: SessionCreateRequest) => Promise<void>;
  onDeleteSession: (sessionId: string) => Promise<void>;
}

export const CorpusPanel: React.FC<CorpusPanelProps> = ({
  sessions,
  selectedSession,
  onSelectSession,
  onCreateSession,
  onDeleteSession,
}) => {
  const [sessionId, setSessionId] = useState("sess-redis-tls-05");
  const [title, setTitle] = useState("Redis TLS Handshake Failure & CA Rotation");
  const [repository, setRepository] = useState("org/cache-service");
  const [failureTurnText, setFailureTurnText] = useState(
    "TLS handshake failed with x509 certificate signed by unknown authority on redis-primary:6379"
  );
  const [recoveryTurnText, setRecoveryTurnText] = useState(
    "Updated mounted secret ca-bundle.crt and verified redis-cli --tls ping returned PONG"
  );
  const [sliceViewMode, setSliceViewMode] = useState<"semantic_topic" | "fixed_window">(
    "semantic_topic"
  );
  const [submitting, setSubmitting] = useState(false);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!sessionId.trim() || !title.trim()) return;
    setSubmitting(true);
    try {
      await onCreateSession({
        session_id: sessionId.trim(),
        title: title.trim(),
        repository: repository.trim() || "org/default",
        environment_tag: "staging",
        target_window_tokens: 45,
        topic_drift_threshold: 0.22,
        turns: [
          {
            turn_index: 0,
            role: "agent",
            timestamp: new Date().toISOString(),
            command_or_tool: "kubectl get pods -n cache",
            content: "Checking cache cluster pod health and configmap mounts before rollout.",
            is_failure: false,
          },
          {
            turn_index: 1,
            role: "tool",
            timestamp: new Date().toISOString(),
            command_or_tool: "redis-cli --tls -h redis-primary ping",
            content: failureTurnText,
            is_failure: true,
            error_code: "TLS_HANDSHAKE_ERR",
          },
          {
            turn_index: 2,
            role: "agent",
            timestamp: new Date().toISOString(),
            command_or_tool: "kubectl apply -f redis-ca-secret.yaml",
            content: recoveryTurnText,
            is_failure: false,
          },
        ],
      });
    } finally {
      setSubmitting(false);
    }
  };

  const activeSlices: SliceRecord[] = selectedSession
    ? sliceViewMode === "semantic_topic"
      ? selectedSession.semantic_slices
      : selectedSession.fixed_slices
    : [];

  return (
    <div className="panel-grid">
      <section className="card">
        <h2>Indexed Agent Session Trajectories ({sessions.length})</h2>
        <p className="muted">
          Multi-session coding and operations trajectories indexed with both semantic topic
          boundary detection and fixed-token window chunking.
        </p>
        <div className="session-list">
          {sessions.map((s) => (
            <div
              key={s.session_id}
              className={`session-item ${
                selectedSession?.session_id === s.session_id ? "active" : ""
              }`}
            >
              <div className="session-item-header">
                <button
                  type="button"
                  className="link-button"
                  onClick={() => onSelectSession(s.session_id)}
                >
                  <strong>{s.title}</strong>
                </button>
                <span className="badge">{s.repository}</span>
              </div>
              <div className="session-meta">
                <span>ID: {s.session_id}</span>
                <span>Turns: {s.turn_count}</span>
                <span className="failure-pill">Failures: {s.failure_turn_count}</span>
                <span>Semantic Slices: {s.semantic_slice_count}</span>
                <span>Fixed Slices: {s.fixed_slice_count}</span>
              </div>
              <div className="session-actions">
                <button
                  type="button"
                  className="btn-secondary"
                  onClick={() => onSelectSession(s.session_id)}
                >
                  Inspect Slices
                </button>
                <button
                  type="button"
                  className="btn-danger"
                  onClick={() => onDeleteSession(s.session_id)}
                >
                  Delete
                </button>
              </div>
            </div>
          ))}
        </div>

        <form className="ingest-form" onSubmit={handleCreate}>
          <h3>Ingest New Agent Trajectory</h3>
          <div className="form-row">
            <label>
              Session ID
              <input
                aria-label="Session ID"
                value={sessionId}
                onChange={(e) => setSessionId(e.target.value)}
                required
              />
            </label>
            <label>
              Repository
              <input
                aria-label="Repository"
                value={repository}
                onChange={(e) => setRepository(e.target.value)}
                required
              />
            </label>
          </div>
          <label>
            Session Title
            <input
              aria-label="Session Title"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              required
            />
          </label>
          <label>
            Failure Turn Output (Verbatim Error Episode)
            <textarea
              aria-label="Failure Turn Output"
              rows={2}
              value={failureTurnText}
              onChange={(e) => setFailureTurnText(e.target.value)}
              required
            />
          </label>
          <label>
            Remediation Turn Output (Resolution Episode)
            <textarea
              aria-label="Remediation Turn Output"
              rows={2}
              value={recoveryTurnText}
              onChange={(e) => setRecoveryTurnText(e.target.value)}
              required
            />
          </label>
          <button type="submit" className="btn-primary" disabled={submitting}>
            {submitting ? "Indexing..." : "Index Session & Compute Slices"}
          </button>
        </form>
      </section>

      <section className="card">
        {selectedSession ? (
          <>
            <div className="slice-header">
              <div>
                <h2>Slice Inspector: {selectedSession.title}</h2>
                <p className="muted">
                  Session <code>{selectedSession.session_id}</code> · {selectedSession.raw_token_count}{" "}
                  raw tokens across {selectedSession.turn_count} turns
                </p>
              </div>
              <div className="toggle-group">
                <button
                  type="button"
                  className={sliceViewMode === "semantic_topic" ? "btn-primary" : "btn-secondary"}
                  onClick={() => setSliceViewMode("semantic_topic")}
                >
                  Semantic Topic Slices ({selectedSession.semantic_slices.length})
                </button>
                <button
                  type="button"
                  className={sliceViewMode === "fixed_window" ? "btn-primary" : "btn-secondary"}
                  onClick={() => setSliceViewMode("fixed_window")}
                >
                  Fixed-Window Slices ({selectedSession.fixed_slices.length})
                </button>
              </div>
            </div>

            <div className="slice-list">
              {activeSlices.map((sl) => (
                <div
                  key={sl.slice_id}
                  className={`slice-card ${sl.has_failure_turn ? "slice-failure" : ""}`}
                >
                  <div className="slice-meta">
                    <strong>{sl.slice_id}</strong>
                    <span>
                      Turns {sl.start_turn}–{sl.end_turn} ({sl.turn_count} turns, {sl.token_count} tokens)
                    </span>
                    <span className="badge">{sl.boundary_reason}</span>
                    {sl.has_failure_turn && (
                      <span className="failure-pill">Failure Episode Preserved</span>
                    )}
                  </div>
                  <div className="term-row">
                    Dominant terms:{" "}
                    {sl.dominant_terms.map((t) => (
                      <code key={t} className="term-chip">
                        {t}
                      </code>
                    ))}
                  </div>
                  <pre className="slice-pre">{sl.text}</pre>
                </div>
              ))}
            </div>
          </>
        ) : (
          <p className="muted">Select a session to inspect its semantic vs fixed-window slices.</p>
        )}
      </section>
    </div>
  );
};
