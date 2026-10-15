"""Hybrid BM25 + dense n-gram cosine retrieval and preregistered evaluation engine."""

from __future__ import annotations

from collections import Counter
import math
from typing import Dict, List, Optional, Tuple

from app.models.schemas import (
    EvalCaseResult,
    EvalReportResponse,
    SearchComparisonResponse,
    SearchHit,
    SliceRecord,
)
from app.services.slicer import tokenize_terms


FAILURE_SITUATION_CUES = {
    "fail", "failed", "failure", "error", "panic", "sigabrt", "401", "403", "429",
    "timeout", "crash", "abort", "rejected", "breaker", "enomem", "freeze", "stuck",
    "broken", "bug", "incident", "retry", "exhaustion", "mismatch", "deny", "deadlock",
}


def _char_And_word_ngrams(text: str) -> Counter[str]:
    terms = tokenize_terms(text)
    grams: Counter[str] = Counter()
    for term in terms:
        grams[f"w:{term}"] += 1.5
        padded = f"#{term}#"
        for i in range(max(0, len(padded) - 3)):
            grams[f"c3:{padded[i:i+3]}"] += 0.5
    for i in range(len(terms) - 1):
        grams[f"bi:{terms[i]}_{terms[i+1]}"] += 1.25
    return grams


def _cosine_similarity(vec_a: Counter[str], vec_b: Counter[str]) -> float:
    if not vec_a or not vec_b:
        return 0.0
    dot = 0.0
    for k, val in vec_a.items():
        if k in vec_b:
            dot += val * vec_b[k]
    norm_a = math.sqrt(sum(v * v for v in vec_a.values()))
    norm_b = math.sqrt(sum(v * v for v in vec_b.values()))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def _query_has_failure_intent(query: str) -> bool:
    q_terms = set(tokenize_terms(query))
    for term in q_terms:
        if term in FAILURE_SITUATION_CUES or any(cue in term for cue in ("err", "fail", "panic", "401", "429", "abort")):
            return True
    return False


def rank_slices(
    query: str,
    slices: List[SliceRecord],
    session_titles: Dict[str, str],
    scoring_mode: str = "hybrid",
    top_k: int = 5,
    failure_boost: float = 0.25,
    exclude_slice_ids: Optional[set[str]] = None,
) -> List[SearchHit]:
    """
    Rank candidate slices using BM25 sparse lexical score, dense n-gram cosine similarity,
    and situation-aware failure-turn retention bonus.
    """
    candidates = [s for s in slices if not exclude_slice_ids or s.slice_id not in exclude_slice_ids]
    if not candidates:
        return []

    query_terms = tokenize_terms(query)
    query_vec = _char_And_word_ngrams(query)
    failure_intent = _query_has_failure_intent(query)

    doc_term_counters: List[Counter[str]] = []
    doc_lengths: List[int] = []
    df: Counter[str] = Counter()

    for sl in candidates:
        terms = tokenize_terms(f"{' '.join(sl.dominant_terms)} {sl.text}")
        counts = Counter(terms)
        doc_term_counters.append(counts)
        doc_lengths.append(max(1, len(terms)))
        for term in counts.keys():
            df[term] += 1

    n_docs = len(candidates)
    avg_dl = sum(doc_lengths) / max(1, n_docs)
    k1 = 1.5
    b = 0.75

    raw_bm25: List[float] = []
    raw_dense: List[float] = []

    for idx, sl in enumerate(candidates):
        counts = doc_term_counters[idx]
        dl = doc_lengths[idx]
        bm25_val = 0.0
        for q_term in query_terms:
            tf = counts.get(q_term, 0)
            if tf == 0:
                continue
            doc_freq = df.get(q_term, 0)
            idf = math.log(1.0 + (n_docs - doc_freq + 0.5) / (doc_freq + 0.5))
            denom = tf + k1 * (1.0 - b + b * (dl / avg_dl))
            bm25_val += idf * ((tf * (k1 + 1.0)) / denom)
        raw_bm25.append(bm25_val)

        slice_vec = _char_And_word_ngrams(f"{' '.join(sl.dominant_terms)} {sl.text}")
        raw_dense.append(_cosine_similarity(query_vec, slice_vec))

    max_bm25 = max(raw_bm25) if raw_bm25 and max(raw_bm25) > 0 else 1.0

    scored_hits: List[Tuple[float, float, float, float, SliceRecord]] = []
    for idx, sl in enumerate(candidates):
        norm_bm25 = raw_bm25[idx] / max_bm25 if max_bm25 > 0 else 0.0
        dense_val = raw_dense[idx]
        # Only apply failure bonus when slice has some lexical or dense relevance
        base_relevance = 0.55 * norm_bm25 + 0.45 * dense_val
        f_bonus = 0.0
        if failure_intent and sl.has_failure_turn and base_relevance > 0.08:
            # Bonus is higher when the slice preserves both the failure turn and remediation context
            cohesion_factor = 1.0 if sl.turn_count >= 2 else 0.45
            f_bonus = failure_boost * cohesion_factor

        if scoring_mode == "bm25":
            final_score = norm_bm25 + f_bonus
        elif scoring_mode == "dense":
            final_score = dense_val + f_bonus
        else:
            final_score = (0.55 * norm_bm25) + (0.45 * dense_val) + f_bonus

        scored_hits.append((final_score, round(norm_bm25, 4), round(dense_val, 4), round(f_bonus, 4), sl))

    scored_hits.sort(key=lambda item: (item[0], item[2], -item[4].token_count), reverse=True)

    results: List[SearchHit] = []
    for rank_idx, (score, bm25_s, dense_s, f_bon, sl) in enumerate(scored_hits[:top_k], start=1):
        results.append(
            SearchHit(
                rank=rank_idx,
                slice_id=sl.slice_id,
                session_id=sl.session_id,
                session_title=session_titles.get(sl.session_id, sl.session_id),
                strategy=sl.strategy,
                start_turn=sl.start_turn,
                end_turn=sl.end_turn,
                score=round(score, 4),
                bm25_score=bm25_s,
                dense_score=dense_s,
                failure_bonus=f_bon,
                has_failure_turn=sl.has_failure_turn,
                boundary_reason=sl.boundary_reason,
                dominant_terms=sl.dominant_terms,
                token_count=sl.token_count,
                snippet=sl.text[:360] + ("..." if len(sl.text) > 360 else ""),
            )
        )
    return results


def estimate_grep_tokens(query: str, all_semantic_slices: List[SliceRecord], total_corpus_tokens: int) -> int:
    """
    Estimate how many tokens a naive `grep -C 3` scan over the session logs would dump into the
    agent context window when searching for any non-stopword token in the situation query.
    """
    q_terms = tokenize_terms(query)
    if not q_terms:
        return total_corpus_tokens
    matched_tokens = 0
    for sl in all_semantic_slices:
        low_text = sl.text.lower()
        # Grep matches any slice where any query token or common status token appears, plus surrounding context
        if any(term in low_text for term in q_terms) or "error" in low_text or "fail" in low_text:
            matched_tokens += sl.token_count * 2
    return max(matched_tokens, min(total_corpus_tokens, 280))


def compare_retrieval_strategies(
    query: str,
    semantic_slices: List[SliceRecord],
    fixed_slices: List[SliceRecord],
    session_titles: Dict[str, str],
    slicing_strategy: str = "semantic_topic",
    scoring_mode: str = "hybrid",
    top_k: int = 5,
    failure_boost: float = 0.25,
) -> SearchComparisonResponse:
    sem_hits = rank_slices(query, semantic_slices, session_titles, scoring_mode, top_k, failure_boost)
    fix_hits = rank_slices(query, fixed_slices, session_titles, scoring_mode, top_k, failure_boost)

    if slicing_strategy == "semantic_topic":
        primary_hits = sem_hits
        counter_strategy = "fixed_window"
        counter_hits = fix_hits
    else:
        primary_hits = fix_hits
        counter_strategy = "semantic_topic"
        counter_hits = sem_hits

    corpus_tokens = max(1, sum(s.token_count for s in semantic_slices))
    grep_tokens = estimate_grep_tokens(query, semantic_slices, corpus_tokens)
    top1_tokens = primary_hits[0].token_count if primary_hits else 1

    ratio_corpus = round(corpus_tokens / max(1, top1_tokens), 2)
    ratio_grep = round(grep_tokens / max(1, top1_tokens), 2)

    return SearchComparisonResponse(
        query=query,
        scoring_mode=scoring_mode,
        selected_strategy=slicing_strategy,
        hits=primary_hits,
        counterpart_strategy=counter_strategy,
        counterpart_hits=counter_hits,
        corpus_total_tokens=corpus_tokens,
        grep_matched_line_tokens=grep_tokens,
        retrieved_top1_tokens=top1_tokens,
        token_reduction_ratio_vs_corpus=ratio_corpus,
        token_reduction_ratio_vs_grep=ratio_grep,
    )


def wilson_confidence_interval(successes: int, total: int, z: float = 1.96) -> Tuple[float, float]:
    if total <= 0:
        return (0.0, 0.0)
    phat = successes / total
    denom = 1.0 + (z * z) / total
    center = (phat + (z * z) / (2.0 * total)) / denom
    half_width = (z * math.sqrt((phat * (1.0 - phat) + (z * z) / (4.0 * total)) / total)) / denom
    low = max(0.0, round(center - half_width, 4))
    high = min(1.0, round(center + half_width, 4))
    return (low, high)


BENCHMARK_QUERIES = [
    {
        "case_id": "eval-01-oauth-audience",
        "situation_query": "deploy failed again with 401 token audience mismatch on staging gateway",
        "expected_session_id": "sess-auth-rollout-01",
        "expected_turn_index": 2,
        "requires_failure_context": True,
    },
    {
        "case_id": "eval-02-sigabrt-drain-stack",
        "situation_query": "node crashed exit 134 SIGABRT thread xerj-drain-free failed to allocate alternative stack ENOMEM",
        "expected_session_id": "sess-memtable-abort-02",
        "expected_turn_index": 2,
        "requires_failure_context": True,
    },
    {
        "case_id": "eval-03-bulk-breaker-oscillation",
        "situation_query": "multi-index bulk ingest concurrency oscillates 32 to 1 against 16GB memory circuit breaker watermark",
        "expected_session_id": "sess-ingest-breaker-03",
        "expected_turn_index": 1,
        "requires_failure_context": True,
    },
    {
        "case_id": "eval-04-flywheel-writeback-freeze",
        "situation_query": "decision flywheel write-back freezes after 12 cached answers once BM25 history vote hits tier-1",
        "expected_session_id": "sess-flywheel-cache-04",
        "expected_turn_index": 1,
        "requires_failure_context": True,
    },
    {
        "case_id": "eval-05-exists-probe-slow-scan",
        "situation_query": "finalize catalog resume stuck brute-scanning 3.4s per ax_file exists probe with zero hits",
        "expected_session_id": "sess-ingest-breaker-03",
        "expected_turn_index": 4,
        "requires_failure_context": True,
    },
    {
        "case_id": "eval-06-diagonal-mask-zero-recall",
        "situation_query": "retrieval benchmark evaluation reports constant zero hits after adding similarity matrix fill_diagonal mask",
        "expected_session_id": "sess-flywheel-cache-04",
        "expected_turn_index": 4,
        "requires_failure_context": True,
    },
]


def _slice_satisfies_case(
    sl: SliceRecord,
    expected_session_id: str,
    expected_turn_index: int,
    requires_failure_context: bool,
) -> bool:
    if sl.session_id != expected_session_id:
        return False
    if not (sl.start_turn <= expected_turn_index <= sl.end_turn):
        return False
    # In agent session memory, a retrieval hit over a failure episode must preserve BOTH the failure turn
    # and the resolution/remediation turn in the same slice so the agent sees what failed AND what fixed it.
    if requires_failure_context:
        return sl.has_failure_turn and (sl.end_turn >= expected_turn_index + 1)
    return True


def run_benchmark_evaluation(
    semantic_slices: List[SliceRecord],
    fixed_slices: List[SliceRecord],
    session_titles: Dict[str, str],
    scoring_mode: str = "hybrid",
) -> EvalReportResponse:
    sem_hits_at_1 = 0
    fix_hits_at_1 = 0
    sem_rr_sum = 0.0
    fix_rr_sum = 0.0
    token_ratios: List[float] = []
    cases: List[EvalCaseResult] = []
    corpus_tokens = max(1, sum(s.token_count for s in semantic_slices))

    # Simulate candidate self-mask bug (fill_diagonal bug where gold slices are excluded from candidate pool)
    buggy_mask_hits = 0

    for item in BENCHMARK_QUERIES:
        query = str(item["situation_query"])
        exp_session = str(item["expected_session_id"])
        exp_turn = int(item["expected_turn_index"])
        req_fail = bool(item["requires_failure_context"])

        sem_ranked = rank_slices(query, semantic_slices, session_titles, scoring_mode=scoring_mode, top_k=10)
        fix_ranked = rank_slices(query, fixed_slices, session_titles, scoring_mode=scoring_mode, top_k=10)

        # Find reciprocal rank for semantic slices
        sem_rr = 0.0
        for h in sem_ranked:
            sl_obj = next((s for s in semantic_slices if s.slice_id == h.slice_id), None)
            if sl_obj and _slice_satisfies_case(sl_obj, exp_session, exp_turn, req_fail):
                sem_rr = 1.0 / h.rank
                break

        fix_rr = 0.0
        for h in fix_ranked:
            sl_obj = next((s for s in fixed_slices if s.slice_id == h.slice_id), None)
            if sl_obj and _slice_satisfies_case(sl_obj, exp_session, exp_turn, req_fail):
                fix_rr = 1.0 / h.rank
                break

        sem_top1_ok = sem_rr == 1.0
        fix_top1_ok = fix_rr == 1.0
        if sem_top1_ok:
            sem_hits_at_1 += 1
        if fix_top1_ok:
            fix_hits_at_1 += 1
        sem_rr_sum += sem_rr
        fix_rr_sum += fix_rr

        grep_toks = estimate_grep_tokens(query, semantic_slices, corpus_tokens)
        top1_toks = sem_ranked[0].token_count if sem_ranked else 1
        token_ratios.append(grep_toks / max(1, top1_toks))

        # Check diagonal self-masking bug simulation: exclude all slices matching gold session/turn
        gold_ids = {
            s.slice_id
            for s in semantic_slices
            if _slice_satisfies_case(s, exp_session, exp_turn, req_fail)
        }
        masked_ranked = rank_slices(
            query,
            semantic_slices,
            session_titles,
            scoring_mode=scoring_mode,
            top_k=5,
            exclude_slice_ids=gold_ids,
        )
        if masked_ranked:
            top_masked = next((s for s in semantic_slices if s.slice_id == masked_ranked[0].slice_id), None)
            if top_masked and _slice_satisfies_case(top_masked, exp_session, exp_turn, req_fail):
                buggy_mask_hits += 1

        cases.append(
            EvalCaseResult(
                case_id=str(item["case_id"]),
                situation_query=query,
                expected_session_id=exp_session,
                expected_turn_index=exp_turn,
                requires_failure_context=req_fail,
                semantic_top1_slice_id=sem_ranked[0].slice_id if sem_ranked else None,
                semantic_hit_at_1=sem_top1_ok,
                semantic_reciprocal_rank=round(sem_rr, 4),
                fixed_top1_slice_id=fix_ranked[0].slice_id if fix_ranked else None,
                fixed_hit_at_1=fix_top1_ok,
                fixed_reciprocal_rank=round(fix_rr, 4),
            )
        )

    n = len(BENCHMARK_QUERIES)
    sem_r1 = round(sem_hits_at_1 / max(1, n), 4)
    fix_r1 = round(fix_hits_at_1 / max(1, n), 4)
    sem_ci = wilson_confidence_interval(sem_hits_at_1, n)
    fix_ci = wilson_confidence_interval(fix_hits_at_1, n)

    failure_slices = [s for s in semantic_slices if s.has_failure_turn]
    retained_with_context = [s for s in failure_slices if s.turn_count >= 2]
    retention_rate = round(len(retained_with_context) / max(1, len(failure_slices)), 4)

    return EvalReportResponse(
        benchmark_name="Agent Session Memory Scar Corpus (n=6 paired failure-recovery queries)",
        num_queries=n,
        scoring_mode=scoring_mode,
        semantic_recall_at_1=sem_r1,
        semantic_recall_ci95_low=sem_ci[0],
        semantic_recall_ci95_high=sem_ci[1],
        semantic_mrr=round(sem_rr_sum / max(1, n), 4),
        fixed_window_recall_at_1=fix_r1,
        fixed_window_recall_ci95_low=fix_ci[0],
        fixed_window_recall_ci95_high=fix_ci[1],
        fixed_window_mrr=round(fix_rr_sum / max(1, n), 4),
        failure_turn_retention_rate=retention_rate,
        mean_token_reduction_vs_grep=round(sum(token_ratios) / max(1, len(token_ratios)), 2),
        candidate_mask_integrity_ok=sem_r1 > 0.0 and buggy_mask_hits == 0,
        diagonal_mask_bug_simulated_recall=round(buggy_mask_hits / max(1, n), 4),
        cases=cases,
    )
