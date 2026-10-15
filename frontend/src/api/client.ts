export interface SessionTurnInput {
  turn_index: number;
  role: "agent" | "tool" | "user" | "system";
  timestamp: string;
  command_or_tool: string;
  content: string;
  is_failure: boolean;
  error_code?: string | null;
}

export interface SliceRecord {
  slice_id: string;
  session_id: string;
  strategy: "semantic_topic" | "fixed_window";
  slice_index: number;
  start_turn: number;
  end_turn: number;
  turn_count: number;
  token_count: number;
  has_failure_turn: boolean;
  failure_turn_count: number;
  dominant_terms: string[];
  boundary_reason: string;
  text: string;
}

export interface SessionSummary {
  session_id: string;
  title: string;
  repository: string;
  environment_tag: string;
  turn_count: number;
  failure_turn_count: number;
  raw_token_count: number;
  semantic_slice_count: number;
  fixed_slice_count: number;
  created_at: string;
}

export interface SessionDetail extends SessionSummary {
  turns: SessionTurnInput[];
  semantic_slices: SliceRecord[];
  fixed_slices: SliceRecord[];
}

export interface SessionCreateRequest {
  session_id: string;
  title: string;
  repository: string;
  environment_tag: string;
  turns: SessionTurnInput[];
  target_window_tokens: number;
  topic_drift_threshold: number;
}

export interface SearchRequest {
  query: string;
  slicing_strategy: "semantic_topic" | "fixed_window";
  scoring_mode: "hybrid" | "bm25" | "dense";
  top_k: number;
  failure_boost: number;
}

export interface SearchHit {
  rank: number;
  slice_id: string;
  session_id: string;
  session_title: string;
  strategy: string;
  start_turn: number;
  end_turn: number;
  score: number;
  bm25_score: number;
  dense_score: number;
  failure_bonus: number;
  has_failure_turn: boolean;
  boundary_reason: string;
  dominant_terms: string[];
  token_count: number;
  snippet: string;
}

export interface SearchComparisonResponse {
  query: string;
  scoring_mode: string;
  selected_strategy: string;
  hits: SearchHit[];
  counterpart_strategy: string;
  counterpart_hits: SearchHit[];
  corpus_total_tokens: number;
  grep_matched_line_tokens: number;
  retrieved_top1_tokens: number;
  token_reduction_ratio_vs_corpus: number;
  token_reduction_ratio_vs_grep: number;
}

export interface EvalCaseResult {
  case_id: string;
  situation_query: string;
  expected_session_id: string;
  expected_turn_index: number;
  requires_failure_context: boolean;
  semantic_top1_slice_id: string | null;
  semantic_hit_at_1: boolean;
  semantic_reciprocal_rank: number;
  fixed_top1_slice_id: string | null;
  fixed_hit_at_1: boolean;
  fixed_reciprocal_rank: number;
}

export interface EvalReportResponse {
  benchmark_name: string;
  num_queries: number;
  scoring_mode: string;
  semantic_recall_at_1: number;
  semantic_recall_ci95_low: number;
  semantic_recall_ci95_high: number;
  semantic_mrr: number;
  fixed_window_recall_at_1: number;
  fixed_window_recall_ci95_low: number;
  fixed_window_recall_ci95_high: number;
  fixed_window_mrr: number;
  failure_turn_retention_rate: number;
  mean_token_reduction_vs_grep: number;
  candidate_mask_integrity_ok: boolean;
  diagonal_mask_bug_simulated_recall: number;
  cases: EvalCaseResult[];
}

export interface HealthResponse {
  status: string;
  app: string;
  version: string;
  environment: string;
  indexed_sessions: number;
  semantic_slices: number;
  corpus_tokens: number;
}

async function requestJson<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`API Error (${res.status}): ${text}`);
  }
  return res.json() as Promise<T>;
}

export const apiClient = {
  getHealth: () => requestJson<HealthResponse>("/api/health"),
  listSessions: (repository?: string) => {
    const query = repository ? `?repository=${encodeURIComponent(repository)}` : "";
    return requestJson<SessionSummary[]>(`/api/sessions${query}`);
  },
  getSessionDetail: (sessionId: string) =>
    requestJson<SessionDetail>(`/api/sessions/${encodeURIComponent(sessionId)}`),
  createSession: (payload: SessionCreateRequest) =>
    requestJson<SessionDetail>("/api/sessions", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  deleteSession: (sessionId: string) =>
    requestJson<{ deleted: boolean; session_id: string }>(
      `/api/sessions/${encodeURIComponent(sessionId)}`,
      { method: "DELETE" }
    ),
  runSearch: (payload: SearchRequest) =>
    requestJson<SearchComparisonResponse>("/api/search", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  runEvaluation: (scoringMode: "hybrid" | "bm25" | "dense" = "hybrid") =>
    requestJson<EvalReportResponse>(`/api/eval/run?scoring_mode=${scoringMode}`, {
      method: "POST",
    }),
};
