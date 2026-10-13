"""
AI Agent layer for the Migration Workbench.

Provides intelligent schema inspection, Gemini LLM reasoning, heuristic fallback
mapping, risk assessment, and interactive mapping refinement.
"""
from __future__ import annotations

from agent.mapping_agent import AgentResponse, MappingAgent
from agent.prompts import (
    MAPPING_PROMPT_TEMPLATE,
    OUTPUT_FORMAT,
    QUESTIONS_PROMPT_TEMPLATE,
    REFINEMENT_PROMPT_TEMPLATE,
    RISK_PROMPT_TEMPLATE,
    SYSTEM_PROMPT,
)
from agent.risk_analyzer import (
    FieldRisk,
    RiskLevel,
    RiskReport,
    analyze_risks,
)
from agent.tools import (
    check_type_compatibility,
    get_sample_records,
    inspect_source_schema,
    inspect_target_schema,
    list_transformations,
    validate_mapping,
)

__all__ = [
    # Mapping Agent
    "MappingAgent",
    "AgentResponse",
    # Risk Analysis
    "RiskReport",
    "FieldRisk",
    "RiskLevel",
    "analyze_risks",
    # Tools
    "inspect_source_schema",
    "inspect_target_schema",
    "get_sample_records",
    "list_transformations",
    "validate_mapping",
    "check_type_compatibility",
    # Prompts
    "SYSTEM_PROMPT",
    "MAPPING_PROMPT_TEMPLATE",
    "RISK_PROMPT_TEMPLATE",
    "QUESTIONS_PROMPT_TEMPLATE",
    "REFINEMENT_PROMPT_TEMPLATE",
    "OUTPUT_FORMAT",
]
