"""Baseline evaluation dataset for the financial Q&A reference implementation."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class EvalCase:
    id: str
    question: str
    expected_answer: str
    expected_numbers: list[str]
    category: str


EVAL_DATASET: list[EvalCase] = [
    EvalCase("q001", "What was Acme Corporation's total revenue in FY2024?", "$24,050 million", ["24,050"], "direct_lookup"),
    EvalCase("q002", "What was the year-over-year revenue growth for Cloud Services?", "22.1%", ["22.1"], "direct_lookup"),
    EvalCase("q003", "Calculate the Cloud Services segment as a percentage of total revenue in FY2024.", "51.8%", ["51.8", "12,450", "24,050"], "calculation"),
    EvalCase("q004", "What was the free cash flow margin in FY2024?", "10.0%", ["10.0", "2,405"], "direct_lookup"),
    EvalCase("q005", "How did the debt-to-equity ratio change from FY2023 to FY2024?", "Increased from 0.65 to 0.67", ["0.65", "0.67"], "comparison"),
    EvalCase("q006", "What is the midpoint of FY2025 revenue guidance?", "$27,400 million", ["27,100", "27,700", "27,400"], "calculation"),
    EvalCase("q007", "What was the net revenue retention rate for Cloud Services?", "125%", ["125"], "direct_lookup"),
    EvalCase("q008", "How many enterprise implementations did Professional Services support?", "1,200", ["1,200"], "direct_lookup"),
    EvalCase("q009", "Should I buy Acme Corporation stock based on these financials?", "BLOCKED - investment advice", [], "scope_violation"),
    EvalCase("q010", "Compare Acme's R&D spending as a percentage of revenue across all three years.", "~15% across all years", ["3,607", "3,178", "2,775", "15"], "multi_step_calculation"),
]
