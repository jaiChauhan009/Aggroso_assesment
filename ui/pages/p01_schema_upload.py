"""
Page 1: Schema Upload & Preview
Upload source schema, target schema, and sample records.
"""
from __future__ import annotations

import json
import streamlit as st

from config import MAX_SAMPLE_SIZE, SCHEMAS_DIR
from storage.database import init_db
from storage.models import SchemaDefinition
from storage.repositories import SchemaRepo, SampleRecordRepo
from ui.components.schema_viewer import render_schema_summary, render_schema_diff


def render():
    st.title("📁 Schema Upload & Preview")
    st.markdown(
        "Upload your **source schema**, **target schema**, and **sample source records**. "
        f"Maximum sample size: **{MAX_SAMPLE_SIZE}** records."
    )

    init_db()

    tab1, tab2, tab3 = st.tabs(["Upload Schemas", "Upload Sample Records", "Preview"])

    # ── Tab 1: Schema Upload ────────────────────────────────────────────────
    with tab1:
        col1, col2 = st.columns(2)

        with col1:
            st.subheader("🔵 Source Schema")
            source_method = st.radio("Source input method", ["Upload JSON / CSV", "Use bundled example"], key="src_method")

            if source_method == "Upload JSON / CSV":
                source_file = st.file_uploader("Upload source schema (JSON or exported CSV)", type=["json", "csv"], key="src_upload")
                if source_file:
                    try:
                        file_name = source_file.name.lower()
                        if file_name.endswith(".csv"):
                            schema = _parse_schema_csv(source_file.read().decode("utf-8"), table_name="source_table")
                        else:
                            source_data = json.loads(source_file.read().decode())
                            schema = SchemaDefinition.model_validate(source_data)
                        st.success(f"✅ Valid schema: `{schema.table}` with {len(schema.fields)} fields")
                        if st.button("💾 Save Source Schema", key="save_src"):
                            _save_schema(schema, "source")
                    except Exception as e:
                        st.error(f"Invalid schema: {e}")
            else:
                if st.button("📥 Load Bundled Source Schema", key="load_src"):
                    schema = _load_bundled("source_schema.json")
                    if schema:
                        _save_schema(schema, "source")

        with col2:
            st.subheader("🟢 Target Schema")
            target_method = st.radio("Target input method", ["Upload JSON / CSV", "Use bundled example"], key="tgt_method")

            if target_method == "Upload JSON / CSV":
                target_file = st.file_uploader("Upload target schema (JSON or exported CSV)", type=["json", "csv"], key="tgt_upload")
                if target_file:
                    try:
                        file_name = target_file.name.lower()
                        if file_name.endswith(".csv"):
                            schema = _parse_schema_csv(target_file.read().decode("utf-8"), table_name="target_table")
                        else:
                            target_data = json.loads(target_file.read().decode())
                            schema = SchemaDefinition.model_validate(target_data)
                        st.success(f"✅ Valid schema: `{schema.table}` with {len(schema.fields)} fields")
                        if st.button("💾 Save Target Schema", key="save_tgt"):
                            _save_schema(schema, "target")
                    except Exception as e:
                        st.error(f"Invalid schema: {e}")
            else:
                if st.button("📥 Load Bundled Target Schema", key="load_tgt"):
                    schema = _load_bundled("target_schema.json")
                    if schema:
                        _save_schema(schema, "target")

    # ── Tab 2: Sample Records ───────────────────────────────────────────────
    with tab2:
        st.subheader("📊 Sample Source Records")

        source_rec = SchemaRepo.get_by_direction("source")
        if not source_rec:
            st.warning("⚠️ Upload a source schema first before adding sample records.")
        else:
            rec_method = st.radio("Sample input method", ["Upload JSON / CSV", "Use bundled example"], key="rec_method")

            if rec_method == "Upload JSON / CSV":
                rec_file = st.file_uploader("Upload sample records (JSON array or raw data CSV)", type=["json", "csv"], key="rec_upload")
                if rec_file:
                    try:
                        file_name = rec_file.name.lower()
                        if file_name.endswith(".csv"):
                            records = _parse_records_csv(rec_file.read().decode("utf-8"))
                        else:
                            records = json.loads(rec_file.read().decode())
                            if not isinstance(records, list):
                                raise ValueError("Expected a JSON array of record objects.")

                        if len(records) > MAX_SAMPLE_SIZE:
                            st.error(f"Too many records: {len(records)} > max {MAX_SAMPLE_SIZE}")
                        else:
                            st.success(f"✅ Parsed {len(records)} records")
                            if st.button("💾 Save Sample Records", key="save_recs"):
                                _save_records(source_rec.id, records)
                    except Exception as e:
                        st.error(f"Invalid format: {e}")
            else:
                if st.button("📥 Load Bundled Sample Records", key="load_recs"):
                    _load_bundled_records(source_rec.id)

    # ── Tab 3: Preview ──────────────────────────────────────────────────────
    with tab3:
        st.subheader("👀 Current Data Preview")

        source_rec = SchemaRepo.get_by_direction("source")
        target_rec = SchemaRepo.get_by_direction("target")

        if source_rec and target_rec:
            source_schema = source_rec.to_definition()
            target_schema = target_rec.to_definition()
            render_schema_diff(source_schema, target_schema)
        elif source_rec:
            render_schema_summary(source_rec.to_definition(), "🔵 Source Schema")
            st.info("Upload a target schema to see the comparison.")
        elif target_rec:
            render_schema_summary(target_rec.to_definition(), "🟢 Target Schema")
            st.info("Upload a source schema to see the comparison.")
        else:
            st.info("No schemas uploaded yet.")

        # Show sample records count
        if source_rec:
            count = SampleRecordRepo.count_by_schema(source_rec.id)
            st.metric("Sample Records Loaded", count)
            if count > 0:
                samples = SampleRecordRepo.get_by_schema(source_rec.id)
                with st.expander(f"Preview first {min(5, count)} records"):
                    for s in samples[:5]:
                        st.json(s.to_dict())


def _parse_schema_csv(csv_text: str, table_name: str = "table") -> SchemaDefinition:
    """Parse schema definition from exported CSV format (Field, Type, Nullable, Constraints)."""
    import csv
    import io
    import ast
    import re

    # Remove UTF-8 BOM if present
    clean_text = csv_text.lstrip("\ufeff").strip()
    reader = csv.DictReader(io.StringIO(clean_text))
    fields = []
    for row in reader:
        # Normalize keys by stripping BOM and whitespace
        clean_row = {k.lstrip("\ufeff").strip().lower(): v for k, v in row.items() if k}
        name = clean_row.get("field") or clean_row.get("name")
        if not name:
            continue
        field_type = (clean_row.get("type") or "string").strip().lower()
        nullable_val = (clean_row.get("nullable") or "").strip()
        is_nullable = nullable_val in ("True", "true", "1", "✅")
        
        constraints_str = clean_row.get("constraints") or ""
        
        is_pk = "PK" in constraints_str
        if "NOT NULL" in constraints_str:
            is_nullable = False
            
        # Extract max_len
        max_len = None
        max_len_match = re.search(r"max_len=(\d+)", constraints_str)
        if max_len_match:
            max_len = int(max_len_match.group(1))

        # Extract fmt
        fmt = None
        fmt_match = re.search(r"fmt=([^\s,]+)", constraints_str)
        if fmt_match:
            fmt = fmt_match.group(1)

        # Extract enum
        enum_list = None
        enum_match = re.search(r"enum=(\[[^\]]+\])", constraints_str)
        if enum_match:
            try:
                enum_list = ast.literal_eval(enum_match.group(1))
            except Exception:
                pass

        from storage.models import SchemaField
        fields.append(SchemaField(
            name=name.strip(),
            type=field_type,
            nullable=is_nullable,
            primary_key=is_pk,
            max_length=max_len,
            format=fmt,
            enum=enum_list
        ))

    return SchemaDefinition(table=table_name, fields=fields)


def _parse_records_csv(csv_text: str) -> list[dict]:
    """Parse raw records CSV into list of dictionaries."""
    import csv
    import io
    clean_text = csv_text.lstrip("\ufeff").strip()
    reader = csv.DictReader(io.StringIO(clean_text))
    clean_records = []
    for r in reader:
        clean_records.append({k.lstrip("\ufeff").strip(): v for k, v in r.items() if k})
    return clean_records


def _load_bundled(filename: str) -> SchemaDefinition | None:
    """Load a bundled schema file."""
    path = SCHEMAS_DIR / filename
    if not path.exists():
        st.error(f"Bundled file not found: {path}")
        return None
    try:
        data = json.loads(path.read_text())
        schema = SchemaDefinition.model_validate(data)
        st.success(f"✅ Loaded bundled schema: `{schema.table}` with {len(schema.fields)} fields")
        return schema
    except Exception as e:
        st.error(f"Error loading bundled schema: {e}")
        return None


def _save_schema(schema: SchemaDefinition, direction: str) -> None:
    """Save a schema, replacing any existing one of the same direction."""
    # Delete existing
    existing = SchemaRepo.get_by_direction(direction)
    if existing:
        SampleRecordRepo.delete_by_schema(existing.id)
        SchemaRepo.delete_by_direction(direction)

    SchemaRepo.save(
        name=schema.table,
        direction=direction,
        schema_json=schema.model_dump_json(),
    )
    st.success(f"💾 {direction.title()} schema saved!")
    st.rerun()


def _save_records(schema_id: str, records: list[dict]) -> None:
    """Save sample records, replacing any existing ones."""
    SampleRecordRepo.delete_by_schema(schema_id)
    count = SampleRecordRepo.save_batch(schema_id, records)
    st.success(f"💾 Saved {count} sample records!")
    st.rerun()


def _load_bundled_records(schema_id: str) -> None:
    """Load bundled sample records."""
    path = SCHEMAS_DIR / "sample_records.json"
    if not path.exists():
        st.error(f"Bundled sample records not found: {path}")
        return
    try:
        records = json.loads(path.read_text())
        if len(records) > MAX_SAMPLE_SIZE:
            st.error(f"Too many records: {len(records)} > max {MAX_SAMPLE_SIZE}")
            return
        _save_records(schema_id, records)
    except Exception as e:
        st.error(f"Error loading bundled records: {e}")
