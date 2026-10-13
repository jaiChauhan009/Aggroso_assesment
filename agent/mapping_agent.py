"""
AI Mapping Agent for the Migration Workbench.

Coordinates schema inspection, Gemini LLM reasoning, heuristic fallback matching,
and mapping refinement based on human feedback.
"""
from __future__ import annotations

import difflib
import json
import logging
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

import google.generativeai as genai

from config import GEMINI_API_KEY, GEMINI_MODEL, TRANSFORMATION_RULES
from agent.prompts import (
    MAPPING_PROMPT_TEMPLATE,
    OUTPUT_FORMAT,
    QUESTIONS_PROMPT_TEMPLATE,
    REFINEMENT_PROMPT_TEMPLATE,
    SYSTEM_PROMPT,
)
from agent.risk_analyzer import analyze_risks
from agent.tools import (
    check_type_compatibility,
    get_sample_records,
    inspect_source_schema,
    inspect_target_schema,
    list_transformations,
    validate_mapping,
)
from storage.models import FieldMapping, SchemaDefinition, SchemaField

logger = logging.getLogger(__name__)


# ── Agent Response Dataclass ─────────────────────────────────────────────────

@dataclass
class AgentResponse:
    """Structured response produced by the Mapping Agent."""
    mappings: list[FieldMapping]
    warnings: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    questions: list[str] = field(default_factory=list)
    explanation: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert AgentResponse to a serializable dictionary."""
        return {
            "mappings": [m.model_dump() for m in self.mappings],
            "warnings": self.warnings,
            "risks": self.risks,
            "questions": self.questions,
            "explanation": self.explanation,
        }


# ── Mapping Agent Class ──────────────────────────────────────────────────────

class MappingAgent:
    """Intelligent schema alignment and mapping generation agent."""

    def __init__(self, api_key: Optional[str] = None, model_name: Optional[str] = None) -> None:
        """Initialize the Mapping Agent with Gemini client or fallback to heuristic mode.

        Args:
            api_key: Optional Google Gemini API key. If omitted, uses config.GEMINI_API_KEY.
            model_name: Optional Gemini model name. If omitted, uses config.GEMINI_MODEL.
        """
        self.api_key = (api_key or GEMINI_API_KEY).strip()
        self.model_name = (model_name or GEMINI_MODEL).strip()
        self.is_heuristic_mode = False
        self.model: Optional[genai.GenerativeModel] = None

        if not self.api_key:
            logger.info("No GEMINI_API_KEY provided; operating in heuristic fallback mode.")
            self.is_heuristic_mode = True
        else:
            try:
                genai.configure(api_key=self.api_key)
                self.model = genai.GenerativeModel(self.model_name)
                self.is_heuristic_mode = False
                logger.info(f"Initialized MappingAgent with Gemini model: {self.model_name}")
            except Exception as e:
                logger.warning(f"Failed to configure Gemini client ({e}). Reverting to heuristic mode.")
                self.is_heuristic_mode = True

    def propose_mappings(self) -> AgentResponse:
        """Inspect schemas and sample records, then propose structured field mappings.

        Uses the Gemini LLM if configured; otherwise falls back to intelligent
        heuristic fuzzy name and type matching.

        Returns:
            AgentResponse: Complete mapping plan with mappings, warnings, risks, and questions.
        """
        source_schema = inspect_source_schema()
        target_schema = inspect_target_schema()

        # Check if schemas are available
        if not source_schema.get("fields") or not target_schema.get("fields"):
            missing = []
            if not source_schema.get("fields"):
                missing.append("source schema")
            if not target_schema.get("fields"):
                missing.append("target schema")
            warning_msg = f"Cannot generate mappings: {' and '.join(missing)} not found in database."
            return AgentResponse(
                mappings=[],
                warnings=[warning_msg],
                risks=["Migration cannot proceed without valid source and target schemas."],
                questions=["Please load or inspect the source and target schemas before generating a plan."],
                explanation="No schemas were available to inspect.",
            )

        if self.is_heuristic_mode or self.model is None:
            return self._heuristic_mapping(source_schema, target_schema)

        # Build prompt context for LLM
        sample_records = get_sample_records(limit=5)
        transform_catalog = list_transformations()

        prompt = MAPPING_PROMPT_TEMPLATE.format(
            source_schema_summary=json.dumps(source_schema, indent=2),
            target_schema_summary=json.dumps(target_schema, indent=2),
            sample_records_preview=json.dumps(sample_records, indent=2),
            transformation_catalog=json.dumps(transform_catalog, indent=2),
            output_format=OUTPUT_FORMAT,
        )

        full_prompt = f"{SYSTEM_PROMPT}\n\n{prompt}"

        # Candidate models to try in case of deprecation/404
        candidate_models = [self.model_name, "gemini-2.5-flash", "gemini-1.5-flash", "gemini-1.5-pro"]
        seen_models = set()
        last_error = None

        for m_name in candidate_models:
            if not m_name or m_name in seen_models:
                continue
            seen_models.add(m_name)
            try:
                curr_model = genai.GenerativeModel(m_name)
                response = curr_model.generate_content(full_prompt)
                raw_text = response.text if response and hasattr(response, "text") else ""
                parsed_response = self._parse_llm_json(raw_text, source_schema, target_schema)
                if parsed_response:
                    return parsed_response
                logger.warning(f"LLM response from {m_name} did not contain valid JSON.")
            except Exception as e:
                last_error = e
                logger.warning(f"Gemini call to {m_name} failed: {e}")

        logger.warning(f"All Gemini candidate models failed ({last_error}). Falling back to heuristic mapping.")
        fallback = self._heuristic_mapping(source_schema, target_schema)
        fallback.warnings.insert(0, f"Gemini API call failed ({last_error}). Fell back to heuristic rule matching.")
        return fallback

    def refine_mappings(self, current_mappings: list[FieldMapping], user_feedback: str) -> AgentResponse:
        """Refine existing mappings according to user feedback and instructions.

        Args:
            current_mappings: Existing list of FieldMapping objects.
            user_feedback: Plain-text user instructions, corrections, or answers.

        Returns:
            AgentResponse: Updated mapping proposals adhering to the user's feedback.
        """
        source_schema = inspect_source_schema()
        target_schema = inspect_target_schema()

        if not self.is_heuristic_mode and self.model is not None:
            prompt = REFINEMENT_PROMPT_TEMPLATE.format(
                current_mappings=json.dumps([m.model_dump() for m in current_mappings], indent=2),
                user_feedback=user_feedback,
                source_schema_summary=json.dumps(source_schema, indent=2),
                target_schema_summary=json.dumps(target_schema, indent=2),
                transformation_catalog=json.dumps(list_transformations(), indent=2),
                output_format=OUTPUT_FORMAT,
            )
            full_prompt = f"{SYSTEM_PROMPT}\n\n{prompt}"
            try:
                response = self.model.generate_content(full_prompt)
                raw_text = response.text if response and hasattr(response, "text") else ""
                parsed = self._parse_llm_json(raw_text, source_schema, target_schema)
                if parsed:
                    return parsed
            except Exception as e:
                logger.warning(f"LLM refinement failed ({e}); falling back to heuristic refinement.")

        # Heuristic refinement fallback
        return self._heuristic_refine(current_mappings, user_feedback, source_schema, target_schema)

    # ── Heuristic Matching Fallback ──────────────────────────────────────────

    def _heuristic_mapping(self, source_schema: dict[str, Any], target_schema: dict[str, Any]) -> AgentResponse:
        """Generate mappings using fuzzy name matching, semantic aliases, and type compatibility.

        Args:
            source_schema: Source schema dictionary.
            target_schema: Target schema dictionary.

        Returns:
            AgentResponse: Heuristically generated mappings and risk analysis.
        """
        src_fields = source_schema.get("fields", [])
        tgt_fields = target_schema.get("fields", [])

        # Alias dictionary for common schema naming differences
        synonyms = {
            "fname": ["first_name", "firstname", "first", "given_name"],
            "lname": ["last_name", "lastname", "last", "surname", "family_name"],
            "fullname": ["full_name", "name", "first_name", "last_name", "employee_name", "client_name"],
            "email": ["email_address", "mail", "user_email", "email_raw"],
            "phone": ["phone_number", "telephone", "mobile", "tel", "cell"],
            "id": ["identifier", "pk", "uuid", "key"],
            "cust_id": ["customer_id", "client_id", "clientid", "customerid", "emp_id", "staff_id", "staffid"],
            "clientid": ["cust_id", "customer_id", "client_id", "emp_id", "staff_id", "staffid", "id"],
            "addr": ["address", "street", "street_address"],
            "zip": ["zip_code", "postal_code", "postcode"],
            "created": ["created_at", "creation_date", "created_date", "registered_date", "registereddate", "signup_date"],
            "registereddate": ["signup_date", "created_at", "reg_date", "hire_date", "hiredate"],
            "updated": ["updated_at", "modified_at", "modified_date"],
            "balance": ["account_balance", "bal", "current_balance", "salary", "annual_salary", "annualsalary"],
            "membershiptier": ["tier_code", "tier", "membership_tier", "dept_code", "department"],
            "subscribed": ["is_subscribed", "active", "is_active", "status", "enabled"],
            "amt": ["amount", "total", "price", "cost"],
        }

        def normalize(name: str) -> str:
            return re.sub(r"[^a-z0-9]", "", name.lower())

        def match_score(src_name: str, tgt_name: str) -> float:
            s_clean = normalize(src_name)
            t_clean = normalize(tgt_name)

            if s_clean == t_clean:
                return 1.0

            # Synonym check
            for _, syn_list in synonyms.items():
                s_in_syn = any(normalize(item) in s_clean or s_clean in normalize(item) for item in syn_list)
                t_in_syn = any(normalize(item) in t_clean or t_clean in normalize(item) for item in syn_list)
                if s_in_syn and t_in_syn:
                    return 0.95

            # Substring containment
            if s_clean in t_clean or t_clean in s_clean:
                min_len = min(len(s_clean), len(t_clean))
                max_len = max(len(s_clean), len(t_clean))
                return 0.80 * (min_len / max_len)

            # Difflib sequence similarity
            return difflib.SequenceMatcher(None, s_clean, t_clean).ratio()

        mappings: list[FieldMapping] = []
        used_source_fields: set[str] = set()
        questions: list[str] = []
        warnings: list[str] = []

        # Map each target field to the best matching source field
        for tf in tgt_fields:
            tgt_name = tf["name"]
            tgt_type = tf.get("type", "string")

            best_src = None
            best_score = 0.0

            for sf in src_fields:
                src_name = sf["name"]
                score = match_score(src_name, tgt_name)
                if score > best_score:
                    best_score = score
                    best_src = sf

            # Threshold for accepting a match
            if best_src and best_score >= 0.60:
                src_name = best_src["name"]
                src_type = best_src.get("type", "string")
                used_source_fields.add(src_name)

                # Determine transformation
                comp = check_type_compatibility(src_type, tgt_type)
                rule = comp.get("suggested_transform") or "RENAME"
                params: dict[str, Any] = {}

                # Refine rules based on schema attributes
                if rule == "DATE_REFORMAT":
                    params = {
                        "input_format": best_src.get("format") or "%Y-%m-%d",
                        "output_format": tf.get("format") or "%Y-%m-%d",
                    }
                elif tf.get("max_length") and best_src.get("type") == "string":
                    tgt_max = tf["max_length"]
                    src_max = best_src.get("max_length")
                    if src_max is None or src_max > tgt_max:
                        rule = "TRUNCATE"
                        params = {"max_length": tgt_max}
                elif tf.get("enum") and not best_src.get("enum"):
                    rule = "MAP_VALUES"
                    params = {"mapping": {}, "default": tf["enum"][0] if tf["enum"] else None}
                    questions.append(
                        f"Target field '{tgt_name}' requires enum values {tf['enum']}. Please specify mapping from '{src_name}' values."
                    )
                elif not tf.get("nullable") and best_src.get("nullable") and rule == "RENAME":
                    if tf.get("default") is not None:
                        rule = "DEFAULT"
                        params = {"value": tf["default"]}
                    else:
                        warnings.append(
                            f"Target field '{tgt_name}' is non-nullable but source '{src_name}' is nullable."
                        )

                mappings.append(
                    FieldMapping(
                        source_field=src_name,
                        target_field=tgt_name,
                        transformation=rule,
                        params=params,
                    )
                )

                if 0.60 <= best_score < 0.85:
                    questions.append(
                        f"Mapped source field '{src_name}' to target field '{tgt_name}' (confidence {best_score:.2f}). Please confirm if this mapping is correct."
                    )
            else:
                # Target field unmapped
                if not tf.get("nullable") and tf.get("default") is None:
                    questions.append(
                        f"Required target field '{tgt_name}' ({tgt_type}) has no matching source field. What default or derivation rule should be applied?"
                    )

        # Unmapped source fields
        unmapped_sources = [sf["name"] for sf in src_fields if sf["name"] not in used_source_fields]
        if unmapped_sources:
            warnings.append(
                f"{len(unmapped_sources)} source fields will not be migrated: {', '.join(unmapped_sources[:10])}."
            )

        # Calculate risks
        risk_report = analyze_risks(mappings, source_schema, target_schema)
        risks = [f"[{r.risk_level}] {r.reason}" for r in risk_report.field_risks]

        explanation = (
            "Mappings generated via heuristic fuzzy string matching, semantic synonym lookup, "
            "and schema type compatibility rules (Gemini API key not configured or API call skipped)."
        )

        return AgentResponse(
            mappings=mappings,
            warnings=warnings,
            risks=risks,
            questions=questions,
            explanation=explanation,
        )

    def _heuristic_refine(
        self,
        current_mappings: list[FieldMapping],
        feedback: str,
        source_schema: dict[str, Any],
        target_schema: dict[str, Any],
    ) -> AgentResponse:
        """Apply rule-based adjustments to mappings based on user feedback text.

        Args:
            current_mappings: Existing mappings.
            feedback: Plain-text feedback from the user.
            source_schema: Source schema summary.
            target_schema: Target schema summary.

        Returns:
            AgentResponse: Refined mappings.
        """
        mappings_dict = {m.target_field: m for m in current_mappings}
        adjustments_made: list[str] = []
        feedback_lower = feedback.lower()

        # Handle simple directive patterns
        # 1. "drop <field>" or "ignore <field>"
        drop_matches = re.findall(r"(?:drop|ignore|remove)\s+([a-zA-Z0-9_]+)", feedback_lower)
        for field_name in drop_matches:
            if field_name in mappings_dict:
                mappings_dict[field_name].transformation = "DROP"
                adjustments_made.append(f"Set transformation for '{field_name}' to DROP.")
            else:
                for tf, m in mappings_dict.items():
                    if m.source_field.lower() == field_name:
                        m.transformation = "DROP"
                        adjustments_made.append(f"Set transformation for source '{field_name}' (target '{tf}') to DROP.")

        # 2. "cast <source/target> to (int|integer|float|string|bool)"
        cast_matches = re.findall(r"cast\s+([a-zA-Z0-9_]+)\s+to\s+(int|integer|float|string|bool|boolean)", feedback_lower)
        for field_name, target_type in cast_matches:
            rule_map = {
                "int": "CAST_INT",
                "integer": "CAST_INT",
                "float": "CAST_FLOAT",
                "string": "CAST_STRING",
                "bool": "CAST_BOOL",
                "boolean": "CAST_BOOL",
            }
            rule = rule_map.get(target_type, "CAST_STRING")
            for tf, m in mappings_dict.items():
                if tf.lower() == field_name or m.source_field.lower() == field_name:
                    m.transformation = rule
                    adjustments_made.append(f"Updated '{tf}' transformation to {rule}.")

        # 3. "default <target> to <value>"
        default_matches = re.findall(r"default\s+([a-zA-Z0-9_]+)\s+to\s+['\"]?([^'\"\s]+)['\"]?", feedback_lower)
        for field_name, def_val in default_matches:
            for tf, m in mappings_dict.items():
                if tf.lower() == field_name or m.source_field.lower() == field_name:
                    m.transformation = "DEFAULT"
                    m.params = {"value": def_val}
                    adjustments_made.append(f"Set DEFAULT value for '{tf}' to '{def_val}'.")

        # 4. "map <source> to <target>"
        map_matches = re.findall(r"map\s+([a-zA-Z0-9_]+)\s+to\s+([a-zA-Z0-9_]+)", feedback_lower)
        for src, tgt in map_matches:
            mappings_dict[tgt] = FieldMapping(
                source_field=src,
                target_field=tgt,
                transformation="RENAME",
                params={},
            )
            adjustments_made.append(f"Mapped source '{src}' to target '{tgt}'.")

        updated_mappings = list(mappings_dict.values())
        risk_report = analyze_risks(updated_mappings, source_schema, target_schema)
        risks = [f"[{r.risk_level}] {r.reason}" for r in risk_report.field_risks]

        explanation = (
            f"Mappings refined heuristically based on feedback. Adjustments made: "
            + ("; ".join(adjustments_made) if adjustments_made else "None detected from standard patterns; preserved existing mappings.")
        )

        return AgentResponse(
            mappings=updated_mappings,
            warnings=[f"Refinement applied: {adj}" for adj in adjustments_made],
            risks=risks,
            questions=[],
            explanation=explanation,
        )

    # ── LLM Response Parsing ─────────────────────────────────────────────────

    def _parse_llm_json(
        self,
        raw_text: str,
        source_schema: dict[str, Any],
        target_schema: dict[str, Any],
    ) -> Optional[AgentResponse]:
        """Parse, validate, and convert raw LLM output into an AgentResponse.

        Args:
            raw_text: Raw output string from the LLM.
            source_schema: Source schema summary.
            target_schema: Target schema summary.

        Returns:
            Optional[AgentResponse]: Parsed response or None if parsing fails.
        """
        if not raw_text:
            return None

        # Strip markdown fences if present
        clean_text = raw_text.strip()
        if "```" in clean_text:
            fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", clean_text)
            if fence_match:
                clean_text = fence_match.group(1).strip()

        try:
            data = json.loads(clean_text)
        except json.JSONDecodeError as e:
            logger.debug(f"JSONDecodeError on LLM output: {e}")
            return None

        if not isinstance(data, dict):
            return None

        raw_mappings = data.get("mappings") or []
        warnings = [str(w) for w in (data.get("warnings") or [])]
        risks = [str(r) for r in (data.get("risks") or [])]
        questions = [str(q) for q in (data.get("questions") or [])]
        explanation = str(data.get("explanation") or "")

        field_mappings: list[FieldMapping] = []
        for item in raw_mappings:
            if not isinstance(item, dict):
                continue
            src = str(item.get("source_field") or "").strip()
            tgt = str(item.get("target_field") or "").strip()
            rule = str(item.get("transformation") or "RENAME").strip().upper()
            params = item.get("params") or {}

            if rule not in TRANSFORMATION_RULES:
                warnings.append(f"Unknown transformation rule '{rule}' proposed for '{src}' -> '{tgt}'. Defaulted to RENAME.")
                rule = "RENAME"

            fm = FieldMapping(
                source_field=src,
                target_field=tgt,
                transformation=rule,
                params=params,
            )

            # Validate each mapping with validation tool
            val_result = validate_mapping(fm.model_dump())
            if not val_result.get("valid"):
                for err in val_result.get("errors", []):
                    warnings.append(f"Validation warning for '{src}' -> '{tgt}': {err}")

            field_mappings.append(fm)

        # Supplement with formal risk analysis
        risk_report = analyze_risks(field_mappings, source_schema, target_schema)
        for r in risk_report.field_risks:
            formatted_risk = f"[{r.risk_level}] {r.reason}"
            if formatted_risk not in risks:
                risks.append(formatted_risk)

        return AgentResponse(
            mappings=field_mappings,
            warnings=warnings,
            risks=risks,
            questions=questions,
            explanation=explanation,
        )
