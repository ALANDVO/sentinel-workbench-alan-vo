import React, { useState } from "react";
import { EvalReportResponse } from "../api/client";

interface EvalGatePanelProps {
  evalReport: EvalReportResponse | null;
  onRunEval: (scoringMode: "hybrid" | "bm25" | "dense") => Promise<void>;
}

export const EvalGatePanel: React.FC<EvalGatePanelProps> = ({
  evalReport,
  onRunEval,
}) => {
  const [scoringMode, setScoringMode] = useState<"hybrid" | "bm25" | "dense">("hybrid");
  const [running, setRunning] = useState(false);

  const handleRun = async () => {
    setRunning(true);
    try {
      await onRunEval(scoringMode);
    } finally {
      setRunning(false);
    }
  };

  const exportReportJson = () => {
    if (!evalReport) return;
    const blob = new Blob([JSON.stringify(evalReport, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `sentinel-eval-report-${evalReport.scoring_mode}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="card">
      <div className="slice-header">
        <div>
          <h2>Preregistered Retrieval Evaluation & Mask Sanity Check</h2>
          <p className="muted">
            Recomputes paired Recall@1, Mean Reciprocal Rank (MRR), Wilson 95% confidence
            intervals, and verifies that candidate-pool self-exclusion (<code>fill_diagonal</code>{" "}
            masking bug) is absent.
          </p>
        </div>
        <div className="toggle-group">
          <select
            aria-label="Evaluation Scoring Mode"
            value={scoringMode}
            onChange={(e) => setScoringMode(e.target.value as "hybrid" | "bm25" | "dense")}
          >
            <option value="hybrid">Hybrid Mode</option>
            <option value="bm25">BM25 Sparse</option>
            <option value="dense">Dense Cosine</option>
          </select>
          <button type="button" className="btn-primary" onClick={handleRun} disabled={running}>
            {running ? "Evaluating..." : "Recompute Evaluation Benchmark"}
          </button>
          {evalReport && (
            <button type="button" className="btn-secondary" onClick={exportReportJson}>
              Export JSON Artifact
            </button>
          )}
        </div>
      </div>

      {evalReport && (
        <>
          <div className="metrics-banner">
            <div className="metric-box">
              <span className="metric-label">Semantic Slicing Recall@1</span>
              <strong>{(evalReport.semantic_recall_at_1 * 100).toFixed(1)}%</strong>
              <span className="muted">
                95% CI: [{(evalReport.semantic_recall_ci95_low * 100).toFixed(1)}%,{" "}
                {(evalReport.semantic_recall_ci95_high * 100).toFixed(1)}%]
              </span>
            </div>
            <div className="metric-box">
              <span className="metric-label">Fixed-Window Recall@1</span>
              <strong>{(evalReport.fixed_window_recall_at_1 * 100).toFixed(1)}%</strong>
              <span className="muted">
                95% CI: [{(evalReport.fixed_window_recall_ci95_low * 100).toFixed(1)}%,{" "}
                {(evalReport.fixed_window_recall_ci95_high * 100).toFixed(1)}%]
              </span>
            </div>
            <div className="metric-box">
              <span className="metric-label">Semantic MRR vs Fixed MRR</span>
              <strong>
                {evalReport.semantic_mrr.toFixed(3)} vs {evalReport.fixed_window_mrr.toFixed(3)}
              </strong>
            </div>
            <div className="metric-box">
              <span className="metric-label">Candidate Mask Integrity</span>
              <strong>
                {evalReport.candidate_mask_integrity_ok ? "PASS (No Self-Mask)" : "FAIL"}
              </strong>
              <span className="muted">
                Simulated fill_diagonal recall: {evalReport.diagonal_mask_bug_simulated_recall}
              </span>
            </div>
          </div>

          <table className="eval-table">
            <thead>
              <tr>
                <th>Case ID</th>
                <th>Situation Query</th>
                <th>Expected Session (Turn)</th>
                <th>Semantic Top-1</th>
                <th>Semantic Hit@1</th>
                <th>Fixed Top-1</th>
                <th>Fixed Hit@1</th>
              </tr>
            </thead>
            <tbody>
              {evalReport.cases.map((c) => (
                <tr key={c.case_id}>
                  <td>
                    <code>{c.case_id}</code>
                  </td>
                  <td>{c.situation_query}</td>
                  <td>
                    <code>
                      {c.expected_session_id} (#{c.expected_turn_index})
                    </code>
                  </td>
                  <td>
                    <code>{c.semantic_top1_slice_id || "none"}</code>
                  </td>
                  <td>
                    <span className={c.semantic_hit_at_1 ? "pass-pill" : "failure-pill"}>
                      {c.semantic_hit_at_1 ? "PASS" : "MISS"}
                    </span>
                  </td>
                  <td>
                    <code>{c.fixed_top1_slice_id || "none"}</code>
                  </td>
                  <td>
                    <span className={c.fixed_hit_at_1 ? "pass-pill" : "failure-pill"}>
                      {c.fixed_hit_at_1 ? "PASS" : "MISS"}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  );
};
