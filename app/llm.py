"""
LLM-powered audit topic detection and recommendation generation.

Uses Anthropic Claude to analyse audit data and produce topic-specific,
clinically grounded recommendations. Falls back to hardcoded suggestions
if the API is unavailable or the key is missing.

Why a real LLM call:
The static recommendation logic in early versions returned identical
advice ("add EPR prompts, schedule re-audit") regardless of audit topic.
Real audits — VTE, hand hygiene, falls, drug charts — have entirely
different evidence bases and improvement levers. This module routes
the audit context through Claude so the recommendations match the
audit being performed.
"""

from __future__ import annotations

import os
import json
from pathlib import Path

# Load .env if present (local dev). On Streamlit Cloud, secrets are injected
# via st.secrets — see streamlit_app.py for the lookup logic.
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # python-dotenv not installed — fine, we'll fall back to os.environ directly
    pass

# Sonnet 4.6 — best clinical reasoning at sane cost
CLAUDE_MODEL = "claude-sonnet-4-6"

# Hardcoded fallback recommendations used when the API key is missing
# or the API call fails. Generic on purpose — they should never look
# like "real AI output".
FALLBACK_RECOMMENDATIONS = [
    "Add electronic prompts or ward-board reminders to highlight the audit standard.",
    "Provide a 5-minute teaching huddle covering the evidence base and common pitfalls.",
    "Schedule a re-audit within 1-3 months to confirm sustained improvement.",
]
FALLBACK_TOPIC = "Clinical compliance audit"


def _load_api_key() -> str | None:
    """Resolve the API key from environment (.env locally, st.secrets in deploy)."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        return key.strip()
    # Streamlit Cloud injects secrets at runtime via st.secrets — but this
    # module shouldn't depend on streamlit at import time, so we let
    # streamlit_app.py call set_api_key() if needed.
    return None


_RUNTIME_KEY: str | None = None


def set_api_key(key: str) -> None:
    """Override the env-derived key (used by streamlit_app for st.secrets)."""
    global _RUNTIME_KEY
    _RUNTIME_KEY = key.strip() if key else None


def _get_client():
    """Build an Anthropic client. Returns None if no key is configured."""
    key = _RUNTIME_KEY or _load_api_key()
    if not key:
        return None
    try:
        from anthropic import Anthropic
        return Anthropic(api_key=key)
    except Exception:
        return None


def _build_prompt(
    component_compliance: dict[str, float],
    overall: float,
    n_records: int,
    column_names: list[str],
) -> str:
    """Construct the user message sent to Claude."""
    components_block = "\n".join(
        f"- {name}: {pct * 100:.1f}% compliance"
        for name, pct in component_compliance.items()
    )
    columns_block = ", ".join(column_names)

    return (
        "You are advising an NHS doctor on improving the results of a clinical audit.\n\n"
        f"DATASET COLUMNS: {columns_block}\n"
        f"RECORDS ANALYSED: {n_records}\n"
        f"OVERALL COMPLIANCE: {overall * 100:.1f}%\n\n"
        "PER-COMPONENT COMPLIANCE:\n"
        f"{components_block}\n\n"
        "Respond ONLY with a JSON object matching this schema:\n"
        "{\n"
        '  "topic": "<short audit topic name, e.g. \'VTE risk assessment\' or '
        '\'Hand hygiene\'>",\n'
        '  "recommendations": [\n'
        '    "<concrete, specific, NICE/RCP/WHO-grounded action>",\n'
        '    "<another action>",\n'
        '    "<another action>",\n'
        '    "<another action, optional>"\n'
        "  ]\n"
        "}\n\n"
        "Rules:\n"
        "- Detect the audit topic from the column names. Be specific "
        "('VTE prophylaxis prescribing', not just 'compliance').\n"
        "- Give 3-4 recommendations. Tailor them to the specific topic and to where "
        "the gaps actually are (which components scored worst).\n"
        "- Cite UK guidance bodies where relevant (NICE, Royal College, WHO 5 Moments, etc.)\n"
        "- Be concrete: 'Set the prophylaxis prescription to default-on in EPR' "
        "is better than 'add EPR prompts'.\n"
        "- No fluff. No hedging. Each recommendation should be 1-2 sentences max.\n"
        "- Return ONLY the JSON. No prose before or after."
    )


def _parse_response(text: str) -> tuple[str, list[str]] | None:
    """Extract topic and recommendations from the model's JSON response."""
    text = text.strip()
    # Tolerate markdown code-fences if the model wraps JSON in ```json ... ```
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].lstrip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None

    topic = data.get("topic")
    recs = data.get("recommendations")
    if not isinstance(topic, str) or not isinstance(recs, list):
        return None
    if not topic or not recs:
        return None
    if not all(isinstance(r, str) and r.strip() for r in recs):
        return None
    return topic.strip(), [r.strip() for r in recs]


def generate_audit_insights(
    component_compliance: dict[str, float],
    overall: float,
    n_records: int,
    column_names: list[str],
) -> tuple[str, list[str], str]:
    """
    Detect audit topic and generate tailored recommendations.

    Returns
    -------
    topic : str
        Inferred audit topic, e.g. "VTE risk assessment".
    recommendations : list[str]
        3-4 concrete, topic-specific suggestions.
    source : str
        "claude" if AI-generated, "fallback" if hardcoded was used.
    """
    client = _get_client()
    if client is None:
        return FALLBACK_TOPIC, FALLBACK_RECOMMENDATIONS, "fallback"

    prompt = _build_prompt(
        component_compliance=component_compliance,
        overall=overall,
        n_records=n_records,
        column_names=column_names,
    )

    try:
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        # Claude returns a list of content blocks; we want the first text block
        text = ""
        for block in response.content:
            if getattr(block, "type", None) == "text":
                text = block.text
                break
        if not text:
            return FALLBACK_TOPIC, FALLBACK_RECOMMENDATIONS, "fallback"

        parsed = _parse_response(text)
        if parsed is None:
            return FALLBACK_TOPIC, FALLBACK_RECOMMENDATIONS, "fallback"

        topic, recs = parsed
        return topic, recs, "claude"
    except Exception:
        # Any network/API/auth failure falls back gracefully
        return FALLBACK_TOPIC, FALLBACK_RECOMMENDATIONS, "fallback"