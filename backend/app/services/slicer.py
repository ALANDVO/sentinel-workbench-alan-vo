"""Semantic topic boundary slicer vs fixed-window chunker for agent session trajectories."""

from __future__ import annotations

from collections import Counter
import re
from typing import List, Set

from app.models.schemas import SessionTurnInput, SliceRecord

STOPWORDS: Set[str] = {
    "the", "and", "for", "with", "that", "this", "from", "into", "when", "where",
    "what", "which", "have", "has", "had", "was", "were", "are", "is", "be", "been",
    "to", "of", "in", "on", "at", "by", "an", "a", "or", "as", "it", "its", "run",
    "running", "step", "turn", "agent", "output", "result", "command", "check", "checking",
}


def tokenize_terms(text: str) -> List[str]:
    raw_tokens = re.findall(r"[a-zA-Z0-9_./:-]{2,}", text.lower())
    cleaned: List[str] = []
    for tok in raw_tokens:
        stripped = tok.strip(".:/-_")
        if len(stripped) >= 2 and stripped not in STOPWORDS:
            cleaned.append(stripped)
    return cleaned


def count_whitespace_tokens(text: str) -> int:
    return max(1, len(text.split()))


def extract_dominant_terms(turns: List[SessionTurnInput], top_n: int = 6) -> List[str]:
    counts: Counter[str] = Counter()
    for t in turns:
        combined = f"{t.command_or_tool} {t.error_code or ''} {t.content}"
        for term in tokenize_terms(combined):
            counts[term] += 1
    return [term for term, _ in counts.most_common(top_n)]


def format_slice_text(turns: List[SessionTurnInput]) -> str:
    lines: List[str] = []
    for t in turns:
        status = f"[FAILURE:{t.error_code or 'ERR'}]" if t.is_failure else "[OK]"
        tool_tag = f" ({t.command_or_tool})" if t.command_or_tool else ""
        lines.append(f"Turn {t.turn_index} [{t.role}{tool_tag}] {status}: {t.content}")
    return "\n".join(lines)


def _jaccard_similarity(terms_a: Set[str], terms_b: Set[str]) -> float:
    if not terms_a or not terms_b:
        return 0.0
    inter = len(terms_a.intersection(terms_b))
    union = len(terms_a.union(terms_b))
    return inter / union if union > 0 else 0.0


def _tool_prefix(command_or_tool: str) -> str:
    if not command_or_tool.strip():
        return "none"
    return command_or_tool.strip().split()[0].lower()


def build_semantic_topic_slices(
    session_id: str,
    turns: List[SessionTurnInput],
    target_window_tokens: int = 55,
    topic_drift_threshold: float = 0.22,
) -> List[SliceRecord]:
    """
    Segment agent session turns by semantic topic cohesion and failure-recovery episodes.
    Keeps failure turns attached to their immediate diagnostic/remediation turn rather than
    severing them at arbitrary token boundaries.
    """
    ordered = sorted(turns, key=lambda x: x.turn_index)
    if not ordered:
        return []

    slices: List[SliceRecord] = []
    current_group: List[SessionTurnInput] = [ordered[0]]
    current_reason = "session_start"

    for idx in range(1, len(ordered)):
        turn = ordered[idx]
        prev_turn = ordered[idx - 1]
        accumulated_text = format_slice_text(current_group)
        accumulated_tokens = count_whitespace_tokens(accumulated_text)

        group_terms = set(tokenize_terms(" ".join(f"{t.command_or_tool} {t.content}" for t in current_group)))
        turn_terms = set(tokenize_terms(f"{turn.command_or_tool} {turn.content}"))
        overlap = _jaccard_similarity(group_terms, turn_terms)

        prev_tool = _tool_prefix(prev_turn.command_or_tool)
        curr_tool = _tool_prefix(turn.command_or_tool)
        tool_changed = prev_tool != curr_tool and prev_tool != "none" and curr_tool != "none"

        # If the previous turn was a failure turn, keep the immediate follow-up turn in the same
        # slice if it shares lexical context or resolves the failure episode.
        prev_was_failure = prev_turn.is_failure
        shares_error_recovery = prev_was_failure and (overlap >= 0.10 or not tool_changed)

        should_split = False
        next_reason = "topic_continuation"

        if not shares_error_recovery:
            if overlap < topic_drift_threshold and len(current_group) >= 2:
                should_split = True
                next_reason = f"lexical_topic_shift(jaccard={overlap:.2f})"
            elif tool_changed and overlap < (topic_drift_threshold + 0.12) and accumulated_tokens >= int(target_window_tokens * 0.65):
                should_split = True
                next_reason = f"tool_domain_transition({prev_tool}->{curr_tool})"
            elif accumulated_tokens >= int(target_window_tokens * 1.45):
                should_split = True
                next_reason = f"episode_token_cap({accumulated_tokens})"

        if should_split:
            slices.append(_create_slice_record(session_id, "semantic_topic", len(slices), current_group, current_reason))
            current_group = [turn]
            current_reason = next_reason
        else:
            current_group.append(turn)

    if current_group:
        slices.append(_create_slice_record(session_id, "semantic_topic", len(slices), current_group, current_reason))

    return slices


def build_fixed_window_slices(
    session_id: str,
    turns: List[SessionTurnInput],
    target_window_tokens: int = 55,
) -> List[SliceRecord]:
    """
    Baseline fixed-token-window chunker that slices the transcript strictly by token count,
    splitting individual turns or mid-episode failure diagnostics when the token window fills.
    """
    ordered = sorted(turns, key=lambda x: x.turn_index)
    if not ordered:
        return []

    # Flatten turns into word tokens with turn provenance so fixed windows cut at exact token budgets
    token_stream: List[tuple[int, bool, str]] = []
    for t in ordered:
        formatted = format_slice_text([t])
        for word in formatted.split():
            token_stream.append((t.turn_index, t.is_failure, word))

    window = max(20, target_window_tokens)
    slices: List[SliceRecord] = []
    for chunk_idx, offset in enumerate(range(0, len(token_stream), window)):
        window_items = token_stream[offset : offset + window]
        if not window_items:
            continue
        turn_indices = sorted({item[0] for item in window_items})
        failure_turns = sorted({item[0] for item in window_items if item[1]})
        chunk_text = " ".join(item[2] for item in window_items)
        dom_counts: Counter[str] = Counter(tokenize_terms(chunk_text))
        dominant = [term for term, _ in dom_counts.most_common(6)]
        slices.append(
            SliceRecord(
                slice_id=f"{session_id}::fixed::{chunk_idx}",
                session_id=session_id,
                strategy="fixed_window",
                slice_index=chunk_idx,
                start_turn=turn_indices[0],
                end_turn=turn_indices[-1],
                turn_count=len(turn_indices),
                token_count=len(window_items),
                has_failure_turn=len(failure_turns) > 0,
                failure_turn_count=len(failure_turns),
                dominant_terms=dominant,
                boundary_reason=f"fixed_token_window({window})",
                text=chunk_text,
            )
        )
    return slices


def _create_slice_record(
    session_id: str,
    strategy: str,
    slice_index: int,
    group: List[SessionTurnInput],
    boundary_reason: str,
) -> SliceRecord:
    text = format_slice_text(group)
    failures = [t for t in group if t.is_failure]
    return SliceRecord(
        slice_id=f"{session_id}::sem::{slice_index}",
        session_id=session_id,
        strategy="semantic_topic",
        slice_index=slice_index,
        start_turn=group[0].turn_index,
        end_turn=group[-1].turn_index,
        turn_count=len(group),
        token_count=count_whitespace_tokens(text),
        has_failure_turn=len(failures) > 0,
        failure_turn_count=len(failures),
        dominant_terms=extract_dominant_terms(group),
        boundary_reason=boundary_reason,
        text=text,
    )
