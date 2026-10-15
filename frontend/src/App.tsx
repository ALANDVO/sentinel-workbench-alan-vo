import React, { useEffect, useState } from "react";
import {
  apiClient,
  EvalReportResponse,
  HealthResponse,
  SearchComparisonResponse,
  SearchRequest,
  SessionCreateRequest,
  SessionDetail,
  SessionSummary,
} from "./api/client";
import { CorpusPanel } from "./components/CorpusPanel";
import { SearchComparePanel } from "./components/SearchComparePanel";
import { EvalGatePanel } from "./components/EvalGatePanel";
import "./styles.css";

export const App: React.FC = () => {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [selectedSession, setSelectedSession] = useState<SessionDetail | null>(null);
  const [searchResult, setSearchResult] = useState<SearchComparisonResponse | null>(null);
  const [evalReport, setEvalReport] = useState<EvalReportResponse | null>(null);
  const [activeTab, setActiveTab] = useState<"corpus" | "search" | "eval">("corpus");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(true);

  const loadInitialData = async () => {
    setLoading(true);
    setErrorMessage(null);
    try {
      const [h, sessList, initialSearch, initialEval] = await Promise.all([
        apiClient.getHealth(),
        apiClient.listSessions(),
        apiClient.runSearch({
          query: "deploy failed again with 401 token audience mismatch on staging gateway",
          slicing_strategy: "semantic_topic",
          scoring_mode: "hybrid",
          top_k: 4,
          failure_boost: 0.25,
        }),
        apiClient.runEvaluation("hybrid"),
      ]);
      setHealth(h);
      setSessions(sessList);
      setSearchResult(initialSearch);
      setEvalReport(initialEval);
      if (sessList.length > 0) {
        const detail = await apiClient.getSessionDetail(sessList[0].session_id);
        setSelectedSession(detail);
      }
    } catch (err) {
      setErrorMessage(err instanceof Error ? err.message : "Failed to load workbench data");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadInitialData();
  }, []);

  const handleSelectSession = async (sessionId: string) => {
    try {
      setErrorMessage(null);
      const detail = await apiClient.getSessionDetail(sessionId);
      setSelectedSession(detail);
    } catch (err) {
      setErrorMessage(err instanceof Error ? err.message : "Failed to inspect session");
    }
  };

  const handleCreateSession = async (payload: SessionCreateRequest) => {
    try {
      setErrorMessage(null);
      const created = await apiClient.createSession(payload);
      const [updatedList, h] = await Promise.all([
        apiClient.listSessions(),
        apiClient.getHealth(),
      ]);
      setSessions(updatedList);
      setHealth(h);
      setSelectedSession(created);
    } catch (err) {
      setErrorMessage(err instanceof Error ? err.message : "Failed to create session");
    }
  };

  const handleDeleteSession = async (sessionId: string) => {
    try {
      setErrorMessage(null);
      await apiClient.deleteSession(sessionId);
      const [updatedList, h] = await Promise.all([
        apiClient.listSessions(),
        apiClient.getHealth(),
      ]);
      setSessions(updatedList);
      setHealth(h);
      if (selectedSession?.session_id === sessionId) {
        if (updatedList.length > 0) {
          const nextDetail = await apiClient.getSessionDetail(updatedList[0].session_id);
          setSelectedSession(nextDetail);
        } else {
          setSelectedSession(null);
        }
      }
    } catch (err) {
      setErrorMessage(err instanceof Error ? err.message : "Failed to delete session");
    }
  };

  const handleRunSearch = async (req: SearchRequest) => {
    try {
      setErrorMessage(null);
      const res = await apiClient.runSearch(req);
      setSearchResult(res);
    } catch (err) {
      setErrorMessage(err instanceof Error ? err.message : "Search request failed");
    }
  };

  const handleRunEval = async (scoringMode: "hybrid" | "bm25" | "dense") => {
    try {
      setErrorMessage(null);
      const rep = await apiClient.runEvaluation(scoringMode);
      setEvalReport(rep);
    } catch (err) {
      setErrorMessage(err instanceof Error ? err.message : "Evaluation run failed");
    }
  };

  return (
    <div className="app-shell">
      <header className="top-header">
        <div>
          <h1>Sentinel Workbench — Agent Memory Topic Slicing & Hybrid Retrieval</h1>
          <p className="subtitle">
            Low-token semantic episode indexing, situation-based BM25 + dense n-gram retrieval, and
            preregistered evaluation gates for multi-session AI coding agents.
          </p>
        </div>
        {health && (
          <div className="status-strip">
            <span>Version: v{health.version}</span>
            <span>Sessions: {health.indexed_sessions}</span>
            <span>Semantic Slices: {health.semantic_slices}</span>
            <span>Corpus Tokens: {health.corpus_tokens}</span>
          </div>
        )}
      </header>

      <nav className="tab-bar" aria-label="Workbench Views">
        <button
          type="button"
          className={activeTab === "corpus" ? "tab-btn active" : "tab-btn"}
          onClick={() => setActiveTab("corpus")}
        >
          1. Trajectory Corpus & Topic Slicer
        </button>
        <button
          type="button"
          className={activeTab === "search" ? "tab-btn active" : "tab-btn"}
          onClick={() => setActiveTab("search")}
        >
          2. Situation Hybrid Retrieval vs Grep
        </button>
        <button
          type="button"
          className={activeTab === "eval" ? "tab-btn active" : "tab-btn"}
          onClick={() => setActiveTab("eval")}
        >
          3. Preregistered Evaluation & Mask Sanity
        </button>
      </nav>

      {errorMessage && (
        <div className="error-banner" role="alert">
          <strong>Error:</strong> {errorMessage}
        </div>
      )}

      {loading ? (
        <div className="card">Loading indexed agent trajectories and evaluation metrics...</div>
      ) : (
        <main className="main-content">
          {activeTab === "corpus" && (
            <CorpusPanel
              sessions={sessions}
              selectedSession={selectedSession}
              onSelectSession={handleSelectSession}
              onCreateSession={handleCreateSession}
              onDeleteSession={handleDeleteSession}
            />
          )}
          {activeTab === "search" && (
            <SearchComparePanel
              searchResult={searchResult}
              onRunSearch={handleRunSearch}
            />
          )}
          {activeTab === "eval" && (
            <EvalGatePanel
              evalReport={evalReport}
              onRunEval={handleRunEval}
            />
          )}
        </main>
      )}
    </div>
  );
};

export default App;
