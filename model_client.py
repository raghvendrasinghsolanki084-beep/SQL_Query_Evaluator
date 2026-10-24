"""Local LM Studio client. No cloud LLM API is used."""
import os
import time
import requests

BASE_URL = os.getenv("LM_STUDIO_BASE_URL", "http://localhost:1234/v1")
MODEL_NAME = os.getenv("LM_STUDIO_MODEL", "gemma-3-4b")
API_KEY = os.getenv("LM_STUDIO_API_KEY", "lm-studio")  # Local server commonly accepts any non-empty key.

SYSTEM_PROMPT = """You are a careful SQL debugging assistant.
Return ONLY a JSON object with these keys:
{
  "error_type": "short category",
  "explanation": "what is wrong and why",
  "fixed_sql": "one corrected SQL statement, or empty string if uncertain",
  "assumptions": "any assumptions made"
}
Use only tables and columns in the supplied schema. Preserve the user's apparent intent.
Do not propose DROP, ALTER, TRUNCATE, INSERT, UPDATE, or DELETE statements as a repair.
Do not wrap the JSON in Markdown fences. If the request is ambiguous, say so in assumptions.
"""

def generate_fix(broken_sql: str, schema: str, dialect: str = "SQLite",
                 timeout: int = 120) -> dict:
    """Call the local OpenAI-compatible LM Studio endpoint and return response + latency."""
    url = BASE_URL.rstrip("/") + "/chat/completions"
    prompt = f"""SQL dialect: {dialect}
Database schema:
{schema}

Broken SQL:
{broken_sql}

Explain the error and propose a safe corrected SELECT query."""
    started = time.perf_counter()
    response = requests.post(
        url,
        headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
        json={
            "model": MODEL_NAME,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0,
            "max_tokens": 700,
        },
        timeout=timeout,
    )
    response.raise_for_status()
    elapsed = time.perf_counter() - started
    payload = response.json()
    content = payload["choices"][0]["message"]["content"]
    return {"raw_response": content, "latency_seconds": round(elapsed, 4),
            "model": payload.get("model", MODEL_NAME)}
