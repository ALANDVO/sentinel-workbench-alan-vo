import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { describe, it, expect, vi, beforeEach } from "vitest";
import App from "./App";

const mockHealth = {
  status: "ok",
  app: "sentinel-workbench-alan-vo",
  version: "1.0.0",
  environment: "development",
  indexed_sessions: 4,
  semantic_slices: 8,
  corpus_tokens: 420,
};

const mockSessions = [
  {
    session_id: "sess-auth-rollout-01",
    title: "Staging Gateway OIDC Rollout & 401 Audience Mismatch Recovery",
    repository: "org/gateway-proxy",
    environment_tag: "staging",
    turn_count: 5,
    failure_turn_count: 1,
    raw_token_count: 112,
    semantic_slice_count: 3,
    fixed_slice_count: 3,
    created_at: "2026-10-15T00:00:00Z",
  },
];

const mockDetail = {
  ...mockSessions[0],
  turns: [],
  semantic_slices: [
    {
      slice_id: "sess-auth-rollout-01::sem::1",
      session_id: "sess-auth-rollout-01",
      strategy: "semantic_topic",
      slice_index: 1,
      start_turn: 2,
      end_turn: 3,
      turn_count: 2,
      token_count: 48,
      has_failure_turn: true,
      failure_turn_count: 1,
      dominant_terms: ["401", "audience", "staging-gateway"],
      boundary_reason: "lexical_topic_shift(jaccard=0.05)",
      text: "Turn 2 [tool] [FAILURE:AUTH_401]: Deploy failed again with HTTP 401 audience mismatch.",
    },
  ],
  fixed_slices: [
    {
      slice_id: "sess-auth-rollout-01::fixed::1",
      session_id: "sess-auth-rollout-01",
      strategy: "fixed_window",
      slice_index: 1,
      start_turn: 2,
      end_turn: 2,
      turn_count: 1,
      token_count: 45,
      has_failure_turn: true,
      failure_turn_count: 1,
      dominant_terms: ["401", "audience"],
      boundary_reason: "fixed_token_window(45)",
      text: "Turn 2 [tool] [FAILURE:AUTH_401]: Deploy failed again...",
    },
  ],
};

const mockSearch = {
  query: "deploy failed again with 401 token audience mismatch on staging gateway",
  scoring_mode: "hybrid",
  selected_strategy: "semantic_topic",
  hits: [
    {
      rank: 1,
      slice_id: "sess-auth-rollout-01::sem::1",
      session_id: "sess-auth-rollout-01",
      session_title: mockSessions[0].title,
      strategy: "semantic_topic",
      start_turn: 2,
      end_turn: 3,
      score: 1.215,
      bm25_score: 1.0,
      dense_score: 0.92,
      failure_bonus: 0.25,
      has_failure_turn: true,
      boundary_reason: "lexical_topic_shift(jaccard=0.05)",
      dominant_terms: ["401", "audience"],
      token_count: 48,
      snippet: "Turn 2 [tool] [FAILURE:AUTH_401]: Deploy failed again with HTTP 401...",
    },
  ],
  counterpart_strategy: "fixed_window",
  counterpart_hits: [],
  corpus_total_tokens: 420,
  grep_matched_line_tokens: 340,
  retrieved_top1_tokens: 48,
  token_reduction_ratio_vs_corpus: 8.75,
  token_reduction_ratio_vs_grep: 7.08,
};

const mockEval = {
  benchmark_name: "Agent Session Memory Scar Corpus",
  num_queries: 6,
  scoring_mode: "hybrid",
  semantic_recall_at_1: 1.0,
  semantic_recall_ci95_low: 0.6097,
  semantic_recall_ci95_high: 1.0,
  semantic_mrr: 1.0,
  fixed_window_recall_at_1: 0.3333,
  fixed_window_recall_ci95_low: 0.0968,
  fixed_window_recall_ci95_high: 0.70,
  fixed_window_mrr: 0.4167,
  failure_turn_retention_rate: 1.0,
  mean_token_reduction_vs_grep: 6.45,
  candidate_mask_integrity_ok: true,
  diagonal_mask_bug_simulated_recall: 0.0,
  cases: [
    {
      case_id: "eval-01-oauth-audience",
      situation_query: "deploy failed again with 401 token audience mismatch on staging gateway",
      expected_session_id: "sess-auth-rollout-01",
      expected_turn_index: 2,
      requires_failure_context: true,
      semantic_top1_slice_id: "sess-auth-rollout-01::sem::1",
      semantic_hit_at_1: true,
      semantic_reciprocal_rank: 1.0,
      fixed_top1_slice_id: "sess-auth-rollout-01::fixed::1",
      fixed_hit_at_1: false,
      fixed_reciprocal_rank: 0.0,
    },
  ],
};

describe("Sentinel Workbench UI", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/api/health")) {
        return new Response(JSON.stringify(mockHealth), { status: 200 });
      }
      if (url.includes("/api/sessions/sess-auth-rollout-01")) {
        return new Response(JSON.stringify(mockDetail), { status: 200 });
      }
      if (url.includes("/api/sessions")) {
        return new Response(JSON.stringify(mockSessions), { status: 200 });
      }
      if (url.includes("/api/search")) {
        return new Response(JSON.stringify(mockSearch), { status: 200 });
      }
      if (url.includes("/api/eval/run")) {
        return new Response(JSON.stringify(mockEval), { status: 200 });
      }
      return new Response("Not Found", { status: 404 });
    });
  });

  it("renders indexed sessions and inspects semantic vs fixed slices", async () => {
    render(<App />);
    await waitFor(() => {
      expect(screen.getByText("sess-auth-rollout-01::sem::1")).toBeInTheDocument();
    });
    expect(
      screen.getAllByText(/Staging Gateway OIDC Rollout & 401 Audience Mismatch Recovery/i)
        .length
    ).toBeGreaterThanOrEqual(1);

    fireEvent.click(screen.getByRole("button", { name: /Fixed-Window Slices/i }));
    expect(screen.getByText("sess-auth-rollout-01::fixed::1")).toBeInTheDocument();
  });

  it("switches to the Situation Hybrid Retrieval tab and displays token reduction metrics", async () => {
    render(<App />);
    await waitFor(() => {
      expect(screen.getByText(/Version: v1.0.0/i)).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /2. Situation Hybrid Retrieval vs Grep/i }));
    expect(screen.getByText(/7.08x fewer tokens/i)).toBeInTheDocument();
    expect(screen.getByText(/#1 sess-auth-rollout-01::sem::1/i)).toBeInTheDocument();
  });

  it("switches to the Preregistered Evaluation tab and verifies candidate mask integrity", async () => {
    render(<App />);
    await waitFor(() => {
      expect(screen.getByText(/Version: v1.0.0/i)).toBeInTheDocument();
    });

    fireEvent.click(
      screen.getByRole("button", { name: /3. Preregistered Evaluation & Mask Sanity/i })
    );
    expect(screen.getByText(/PASS \(No Self-Mask\)/i)).toBeInTheDocument();
    expect(screen.getByText("eval-01-oauth-audience")).toBeInTheDocument();
  });
});
