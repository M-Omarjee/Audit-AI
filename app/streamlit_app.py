import os, sys
sys.path.append(os.path.dirname(__file__))  # allow imports from /app

import streamlit as st
import pandas as pd
from report_utils import build_pdf, resolve_logo_path

st.set_page_config(page_title="AuditAI", layout="wide")
st.title("AuditAI — Clinical Audit & QI (MVP)")
st.write("✅ Upload your dataset; we’ll auto-detect boolean-like columns and summarise everything.")

# ----- helpers -----
TRUE_SET  = {"yes", "true", "1", "y", "t"}
FALSE_SET = {"no", "false", "0", "n", "f", ""}

def to_bool_series(s: pd.Series) -> pd.Series:
    """Map common yes/no/true/false/1/0 to booleans. Unknowns become NaN."""
    x = s.astype(str).str.strip().str.lower()
    out = pd.Series(index=s.index, dtype="float")  # will hold 1.0/0.0/NaN then cast to bool/NaN
    out = out.mask(x.isin(TRUE_SET), 1.0)
    out = out.mask(x.isin(FALSE_SET), 0.0)
    # non-mapped values remain NaN
    return out

def find_boolean_columns(df: pd.DataFrame):
    """Return list of columns that look boolean-like (after mapping)."""
    bool_cols = []
    for col in df.columns:
        mapped = to_bool_series(df[col])
        # if at least half the non-null values map to 0/1, consider it boolean-like
        non_null = mapped.notna().sum()
        if non_null > 0 and (non_null / len(df) >= 0.5):
            bool_cols.append(col)
    return bool_cols

def compute_component_compliance(df: pd.DataFrame, cols):
    """Return dict of per-column compliance: % True among non-null values."""
    agg = {}
    for col in cols:
        s = to_bool_series(df[col])
        valid = s.notna()
        if valid.any():
            pct = float((s[valid] == 1.0).mean())
        else:
            pct = float("nan")
        agg[col] = pct
    return agg

def compute_overall(df: pd.DataFrame, bool_cols):
    # if there's a 'compliant' column, use it
    lower_cols = {c.lower(): c for c in bool_cols}
    if "compliant" in lower_cols:
        col = lower_cols["compliant"]
        s = to_bool_series(df[col])
        valid = s.notna()
        overall_series = s[valid] == 1.0
        pct = float(overall_series.mean()) if valid.any() else 0.0
        return pct, overall_series.reindex(df.index, fill_value=False)

    # else: overall = AND across all boolean-like columns
    if not bool_cols:
        return 0.0, pd.Series([False] * len(df))

    mask_all_true = pd.Series([True] * len(df))
    for col in bool_cols:
        s = to_bool_series(df[col])
        # treat NaN as True (N/A does not penalise row)
        s_bool = s.fillna(1.0) == 1.0
        mask_all_true &= s_bool

    pct = float(mask_all_true.mean())
    return pct, mask_all_true

# ----- UI -----
st.subheader("Step 1 — Upload data")
uploaded_file = st.file_uploader("Upload a CSV or Excel file", type=["csv", "xlsx"])

df = None
if uploaded_file is not None:
    df = pd.read_csv(uploaded_file) if uploaded_file.name.endswith(".csv") else pd.read_excel(uploaded_file)

if df is not None:
    st.success(f"File uploaded: {uploaded_file.name}")
    st.write("### Data preview:")
    st.dataframe(df.head(20), use_container_width=True)
    st.info(f"Rows = {df.shape[0]} | Columns = {df.shape[1]}")

    # Auto-detect boolean-like columns
    bool_cols = find_boolean_columns(df)
    if not bool_cols:
        st.error("Couldn’t find any boolean-like columns (Yes/No, True/False, 1/0). Add one like 'compliant'.")
        st.stop()

    st.subheader("Detected components")
    st.write(", ".join(bool_cols))

    # Per-component compliance
    comp = compute_component_compliance(df, bool_cols)

    # Overall
    overall_pct, overall_series = compute_overall(df, bool_cols)

    # KPIs
    k1, k2 = st.columns([1,2])
    with k1:
        st.metric("Overall Compliance", f"{overall_pct*100:.1f}%")
    with k2:
        st.progress(overall_pct)

    st.write("### Component Compliance")
    st.dataframe(
        pd.DataFrame({"component": list(comp.keys()), "compliance_%": [v*100 for v in comp.values()]}),
        use_container_width=True
    )

    # Recommendations (very simple rule-based)
    st.subheader("Recommendations")
    recs = []
    target = 0.95
    if overall_pct < target:
        gap = int(target*100 - overall_pct*100)
        recs.append(f"Add EPR prompts / ward board reminders to close ~{gap}% gap.")
        recs.append("Include a mandatory field in the form; add 5-minute huddle teaching.")
        recs.append("Schedule a re-audit next month to confirm improvement.")
    else:
        recs.append("Maintain gains via induction teaching and monthly spot checks.")
    for r in recs:
        st.write(f"- {r}")

# --- Export PDF ---
st.subheader("Export PDF report")
report_title = st.text_input("Report title", value="Audit Report — Compliance Summary")

left, right = st.columns(2)
with left:
    author_name = st.text_input("Your name", value="")
with right:
    author_grade = st.text_input("Grade/Role", value="")

if st.button("Build PDF"):
    # 1) Ensure output folder + define pdf_path BEFORE using it
    os.makedirs("reports", exist_ok=True)
    pdf_path = "reports/audit_report.pdf"

    # 2) Aggregate metrics for the report
    agg_dict = {"overall": overall_pct, **comp}

    # 3) Build PDF (auto-resolves NHS logo; returns debug string)
    used_logo = build_pdf(
        output_path=pdf_path,
        title=report_title,
        agg_dict=agg_dict,
        n_records=len(df),
        recommendations=recs,
        author_name=author_name,
        author_grade=author_grade,
        logo_path=None,  # None => auto-resolve from /assets, else draws vector badge
    )

    # 4) Show where the logo came from
    st.caption(f"Logo source: {used_logo}")

    # 5) Offer the download
    with open(pdf_path, "rb") as f:
        st.download_button(
            "Download PDF",
            data=f.read(),
            file_name="audit_report.pdf",
            mime="application/pdf",
        )

