import React, { useState } from "react";
import { SearchComparisonResponse, SearchRequest } from "../api/client";

interface SearchComparePanelProps {
  searchResult: SearchComparisonResponse | null;
  onRunSearch: (req: SearchRequest) => Promise<void>;
}

const PRESET_QUERIES = [
  "deploy failed again with 401 token audience mismatch on staging gateway",
  "node crashed exit 134 SIGABRT thread xerj-drain-free failed to allocate alternative stack ENOMEM",
  "multi-index bulk ingest concurrency oscillates 32 to 1 against 16GB memory circuit breaker watermark",
  "decision flywheel write-back freezes after 12 cached answers once BM25 history vote hits tier-1",
];

export const SearchComparePanel: React.FC<SearchComparePanelProps> = ({
  searchResult,
  onRunSearch,
}) => {
  const [query, setQuery] = useState(PRESET_QUERIES[0]);
  const [scoringMode, setScoringMode] = useState<"hybrid" | "bm25" | "dense">("hybrid");
  const [strategy, setStrategy] = useState<"semantic_topic" | "fixed_window">("semantic_topic");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!query.trim()) return;
    setLoading(true);
    try {
      await onRunSearch({
        query: query.trim(),
        slicing_strategy: strategy,
        scoring_mode: scoringMode,
        top_k: 4,
        failure_boost: 0.25,
      });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="card">
      <h2>Situation-Based Hybrid Retrieval & Token Efficiency Analyzer</h2>
      <p className="muted">
        In agent memory retrieval, the query is the agent&apos;s current situation or imperative error
        context. Compare Semantic Topic Slicing against Fixed-Window Chunking across Hybrid, BM25,
        and Dense n-gram scoring.
      </p>

      <form onSubmit={handleSubmit} className="search-form">
        <label>
          Agent Situation / Imperative Error Context
          <input
            aria-label="Agent Situation Query"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="e.g. deploy failed again with 401..."
            required
          />
        </label>

        <div className="preset-row">
          <span>Presets:</span>
          {PRESET_QUERIES.map((q, i) => (
            <button
              key={i}
              type="button"
              className="btn-chip"
              onClick={() => setQuery(q)}
            >
              Scenario #{i + 1}
            </button>
          ))}
        </div>

        <div className="form-row">
          <label>
            Primary Slicing Strategy
            <select
              aria-label="Primary Slicing Strategy"
              value={strategy}
              onChange={(e) =>
                setStrategy(e.target.value as "semantic_topic" | "fixed_window")
              }
            >
              <option value="semantic_topic">Semantic Topic & Failure Boundary</option>
              <option value="fixed_window">Fixed-Token Window</option>
            </select>
          </label>
          <label>
            Scoring Mode
            <select
              aria-label="Scoring Mode"
              value={scoringMode}
              onChange={(e) =>
                setScoringMode(e.target.value as "hybrid" | "bm25" | "dense")
              }
            >
              <option value="hybrid">Hybrid (BM25 + Dense Cosine + Failure Retention)</option>
              <option value="bm25">BM25 Sparse Only</option>
              <option value="dense">Dense N-Gram Cosine Only</option>
            </select>
          </label>
          <button type="submit" className="btn-primary" disabled={loading}>
            {loading ? "Searching..." : "Run Comparative Search"}
          </button>
        </div>
      </form>

      {searchResult && (
        <>
          <div className="metrics-banner">
            <div className="metric-box">
              <span className="metric-label">Top-1 Slice Tokens</span>
              <strong>{searchResult.retrieved_top1_tokens} tokens</strong>
            </div>
            <div className="metric-box">
              <span className="metric-label">Naive Grep Scan Tokens</span>
              <strong>{searchResult.grep_matched_line_tokens} tokens</strong>
            </div>
            <div className="metric-box">
              <span className="metric-label">Token Reduction vs Grep</span>
              <strong>{searchResult.token_reduction_ratio_vs_grep}x fewer tokens</strong>
            </div>
            <div className="metric-box">
              <span className="metric-label">Token Reduction vs Full Corpus</span>
              <strong>{searchResult.token_reduction_ratio_vs_corpus}x fewer tokens</strong>
            </div>
          </div>

          <div className="panel-grid">
            <div>
              <h3>Primary: {searchResult.selected_strategy}</h3>
              {searchResult.hits.map((h) => (
                <div
                  key={h.slice_id}
                  className={`slice-card ${h.has_failure_turn ? "slice-failure" : ""}`}
                >
                  <div className="slice-meta">
                    <strong>
                      #{h.rank} {h.slice_id}
                    </strong>
                    <span>Score: {h.score.toFixed(3)}</span>
                    <span>
                      (BM25 {h.bm25_score.toFixed(2)} | Dense {h.dense_score.toFixed(2)} | FailBonus{" "}
                      {h.failure_bonus.toFixed(2)})
                    </span>
                  </div>
                  <div className="slice-meta">
                    <span>
                      Turns {h.start_turn}–{h.end_turn} ({h.token_count} tokens)
                    </span>
                    <span className="badge">{h.boundary_reason}</span>
                  </div>
                  <pre className="slice-pre">{h.snippet}</pre>
                </div>
              ))}
            </div>

            <div>
              <h3>Counterpart Baseline: {searchResult.counterpart_strategy}</h3>
              {searchResult.counterpart_hits.map((h) => (
                <div
                  key={h.slice_id}
                  className={`slice-card ${h.has_failure_turn ? "slice-failure" : ""}`}
                >
                  <div className="slice-meta">
                    <strong>
                      #{h.rank} {h.slice_id}
                    </strong>
                    <span>Score: {h.score.toFixed(3)}</span>
                    <span>
                      Turns {h.start_turn}–{h.end_turn} ({h.token_count} tokens)
                    </span>
                  </div>
                  <pre className="slice-pre">{h.snippet}</pre>
                </div>
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  );
};
