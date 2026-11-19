"""Evaluation criteria definitions for the preregistered retrieval evaluation gates.

This module freezes the preregistered evaluation criteria used in Sentinel Workbench,
including metric names and their order. This ensures that the evaluation report
includes all required metrics and that they are stable across releases.
"""

PREREGISTERED_CRITERIA = [
    "recall@1",
    "mrr",
    "failure-turn recall",
    "majority-class baseline",
    "Wilson 95% confidence intervals",
    "paired McNemar comparison",
]

# Mapping from internal field names to criteria names (optional)
CRITERIA_TO_FIELD = {
    "Recall@1": "semantic_recall_at_1",
    "Mean Reciprocal Rank": "semantic_mrr",
    "Failure-turn recall": "failure_turn_recall_at_1",
    "Majority-class baseline": "majority_class_baseline_recall",
    "Wilson 95% confidence intervals": "semantic_recall_ci95_low",  # as example
    "Paired McNemar comparison": "paired_mcnemar_pvalue",
}
