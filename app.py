"""Small Streamlit demo for a single SQL repair."""
import json
import streamlit as st
from benchmark import SCHEMA_TEXT, create_database, DB_PATH
from model_client import generate_fix
from evaluator import parse_model_json
from sql_validator import validate_select, execute_readonly

st.set_page_config(page_title="SQL Error Explainer & Fixer", page_icon="🛠️")
st.title("SQL Error Explainer & Fixer")
st.caption("Gemma 3 4B · LM Studio local inference · SQLite sandbox")
st.info("Demo queries are tested against synthetic data. Only validated read-only SELECT queries are executed.")

schema = st.text_area("Database schema", SCHEMA_TEXT, height=110)
sql = st.text_area("Broken SQL query", "SELECT name age FROM Students;", height=120)
if st.button("Explain and fix SQL", type="primary"):
    with st.spinner("Asking local Gemma model..."):
        try:
            response = generate_fix(sql, schema)
            parsed = parse_model_json(response["raw_response"])
            st.subheader("Explanation")
            st.write(parsed.get("explanation", "No explanation returned."))
            st.subheader("Proposed SQL")
            fixed = parsed.get("fixed_sql", "")
            st.code(fixed or "(No safe correction returned)", language="sql")
            st.write("Error type:", parsed.get("error_type", "unknown"))
            st.write("Assumptions:", parsed.get("assumptions", "None"))
            st.write(f"Model response time: {response['latency_seconds']} seconds")
            allowed, cleaned, reason = validate_select(fixed)
            st.write("Safety validation:", "PASS" if allowed else "BLOCKED")
            st.caption(reason)
            if allowed and st.button("Execute safe fix against sample database"):
                create_database(DB_PATH)
                result = execute_readonly(DB_PATH, cleaned)
                if result["ok"]:
                    st.success("Executed successfully")
                    st.dataframe(result["rows"], column_config=None, use_container_width=True)
                    st.write("Columns:", result["columns"])
                else:
                    st.error(result["reason"])
            with st.expander("Raw model response"):
                st.code(response["raw_response"])
        except Exception as exc:
            st.error(f"Could not contact the local model: {exc}")
            st.markdown("Check that LM Studio's local server is running and the model is loaded.")
