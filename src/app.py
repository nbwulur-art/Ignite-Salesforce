"""
Manager Lead Prioritization & Routing Dashboard (src/app.py)

Purpose:
    Provides an interactive Streamlit command center for sales managers to
    inspect prioritized leads, verify multi-skill and seniority routing rules,
    monitor representative capacity utilization, triage the Manager Review
    overflow queue, and simulate live incoming leads in real time.

How to Run:
    streamlit run src/app.py
"""

import csv
import io
import os
import sys
import time
import streamlit as st

# Ensure local imports work whether launched from repo root or `src/`
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from cleaner import clean_all_datasets, clean_lead_record
from scorer import score_and_sort_leads
from router import route_leads

# ---------------------------------------------------------------------------
# Page Configuration & Custom Styling
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Ignite Lead Routing Command Center",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    .block-container {
        padding-top: 1.5rem;
        padding-bottom: 2rem;
    }
    div[data-testid="stMetric"] {
        background-color: #f8fafc;
        border: 1px solid #e2e8f0;
        border-radius: 10px;
        padding: 14px 18px;
    }
    div[data-testid="stMetric"] label {
        color: #475569 !important;
        font-weight: 600 !important;
    }
    div[data-testid="stMetric"] div[data-testid="stMetricValue"] {
        color: #0f172a !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# Cached Data Loading & Pipeline Execution
# ---------------------------------------------------------------------------
@st.cache_data(show_spinner=False)
def load_baseline_data():
    """Load and sanitize the 50,000-lead and 1,600-rep scale datasets once."""
    return clean_all_datasets()


def execute_pipeline(leads, reps):
    """Run scoring, tie-breaking, and multi-skill routing while timing execution."""
    start = time.perf_counter()
    scored = score_and_sort_leads(leads)
    routed_payload = route_leads(scored, reps)
    elapsed_ms = (time.perf_counter() - start) * 1000
    routed_payload["elapsed_ms"] = elapsed_ms
    return routed_payload


def dicts_to_csv_bytes(records, columns):
    """Serialize a list of dictionaries into downloadable UTF-8 CSV bytes."""
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(records)
    return buffer.getvalue().encode("utf-8")


# ---------------------------------------------------------------------------
# Session State Initialization
# ---------------------------------------------------------------------------
baseline = load_baseline_data()
base_leads = baseline.get("leads_scale", [])
base_reps = baseline.get("reps_scale", [])

if not base_leads or not base_reps:
    st.error(
        "Could not locate `leads_scale.csv` and `reps_scale.csv` inside your `Data/` folder. "
        "Verify both CSV files are present and restart the app."
    )
    st.stop()

if "custom_leads" not in st.session_state:
    st.session_state.custom_leads = []

active_leads = base_leads + st.session_state.custom_leads
pipeline_result = execute_pipeline(active_leads, base_reps)

routed_leads = pipeline_result["routed_leads"]
manager_review = pipeline_result["manager_review"]
updated_reps = pipeline_result["reps"]
elapsed_ms = pipeline_result["elapsed_ms"]


# ---------------------------------------------------------------------------
# Sidebar: Filters & Live Lead Simulator
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("🔍 Queue Filters")
    selected_tiers = st.multiselect(
        "Priority Tier",
        options=["CRITICAL", "HIGH", "MEDIUM", "LOW"],
        default=["CRITICAL", "HIGH", "MEDIUM", "LOW"],
    )
    selected_regions = st.multiselect(
        "Region",
        options=["North America", "Europe", "Asia-Pacific", "Unknown"],
        default=["North America", "Europe", "Asia-Pacific", "Unknown"],
    )
    status_filter = st.radio(
        "Routing Status",
        options=["All Leads", "Assigned Only", "Manager Review Only"],
        index=0,
    )
    search_query = st.text_input(
        "Search Lead ID, Company, or Rep",
        placeholder="e.g. L-1005 or Tech...",
    ).strip().lower()

    st.divider()

    # Live Incoming Lead Simulator for Presentation Demos
    st.header("⚡ Simulate Incoming Lead")
    with st.form("live_lead_form", clear_on_submit=True):
        sim_company = st.text_input("Company Name", value="Lone Star Robotics")
        sim_region = st.selectbox("Region", ["North America", "Europe", "Asia-Pacific", "Unknown"])
        sim_lang = st.selectbox("Language", ["English", "Spanish", "German", "Unknown"])
        sim_industry = st.selectbox(
            "Industry Vertical",
            ["Technology", "Finance", "Healthcare", "Manufacturing", "Retail", "Unknown"],
        )
        sim_size = st.number_input("Company Size (Employees)", min_value=0, max_value=100000, value=2500, step=100)
        sim_activity = st.selectbox(
            "Recent Activity",
            [
                "Requested Live Demo",
                "Attended Webinar",
                "Downloaded Whitepaper",
                "Visited Pricing Page",
                "None",
            ],
        )
        sim_vip = st.checkbox("VIP Referral (Immediate Critical Override)", value=False)
        submitted = st.form_submit_button("Score & Route Lead", use_container_width=True)

        if submitted:
            new_id = f"L-LIVE-{len(st.session_state.custom_leads) + 1:03d}"
            cleaned_new = clean_lead_record({
                "Lead_ID": new_id,
                "Company_Name": sim_company or "New Prospect Inc",
                "Region": sim_region,
                "Language": sim_lang,
                "Industry_Vertical": sim_industry,
                "Company_Size": str(sim_size) if sim_size > 0 else "",
                "Recent_Activity": sim_activity,
                "VIP_Referral": str(sim_vip),
            })
            st.session_state.custom_leads.append(cleaned_new)
            st.rerun()

    if st.session_state.custom_leads:
        if st.button("Reset Simulated Leads", use_container_width=True):
            st.session_state.custom_leads = []
            st.rerun()


# ---------------------------------------------------------------------------
# Apply Filters to Routed Leads
# ---------------------------------------------------------------------------
filtered_leads = []
for lead in routed_leads:
    if lead["Priority_Tier"] not in selected_tiers:
        continue
    if lead["Region"] not in selected_regions:
        continue
    if status_filter == "Assigned Only" and lead["Routing_Status"] != "Assigned":
        continue
    if status_filter == "Manager Review Only" and lead["Routing_Status"] != "Manager Review":
        continue
    if search_query:
        haystack = (
            f"{lead['Lead_ID']} {lead['Company_Name']} "
            f"{lead['Assigned_Rep_Name']} {lead['Assigned_Rep_ID']}"
        ).lower()
        if search_query not in haystack:
            continue
    filtered_leads.append(lead)


# ---------------------------------------------------------------------------
# Header & Top KPI Metrics
# ---------------------------------------------------------------------------
st.title("⚡ Smart Lead Prioritization & Routing Command Center")
st.caption(
    "In-memory deterministic scoring, tie-breaking, multi-skill rep matching, "
    "and least-utilization load balancing."
)

total_leads = len(routed_leads)
assigned_total = total_leads - len(manager_review)
assigned_pct = (assigned_total / total_leads * 100) if total_leads else 0.0
critical_total = sum(1 for l in routed_leads if l["Priority_Tier"] == "CRITICAL")
junior_critical_violations = sum(
    1 for l in routed_leads
    if l["Priority_Tier"] == "CRITICAL" and l["Assigned_Rep_Seniority"] == "Junior"
)

kpi1, kpi2, kpi3, kpi4, kpi5 = st.columns(5)
kpi1.metric("Total Leads Processed", f"{total_leads:,}")
kpi2.metric("Successfully Assigned", f"{assigned_total:,}", f"{assigned_pct:.1f}% routed")
kpi3.metric("Critical Tier Leads", f"{critical_total:,}", f"{junior_critical_violations} Junior violations")
kpi4.metric("Manager Review Overflow", f"{len(manager_review):,}", "Requires triage")
kpi5.metric("Pipeline Runtime", f"{elapsed_ms:.1f} ms", f"{len(updated_reps):,} active reps")

st.divider()


# ---------------------------------------------------------------------------
# Main Dashboard Tabs
# ---------------------------------------------------------------------------
tab_queue, tab_reps, tab_overflow, tab_analytics = st.tabs([
    f"📋 Prioritized Lead Queue ({len(filtered_leads):,})",
    f"👥 Rep Capacity & Load Balancing ({len(updated_reps):,})",
    f"🚨 Manager Review Overflow ({len(manager_review):,})",
    "📊 Pipeline Analytics",
])


# === TAB 1: PRIORITIZED LEAD QUEUE ===
with tab_queue:
    col_info, col_export = st.columns([4, 1])
    with col_info:
        st.subheader("Ranked Routing Queue & Scoring Transparency")
        st.write(
            "Sorted by **Priority Tier** $\\rightarrow$ **Score** $\\rightarrow$ "
            "**VIP Status** $\\rightarrow$ **Company Size** $\\rightarrow$ **Arrival ID**. "
            "Showing top 500 matching rows for fast browser rendering."
        )
    with col_export:
        export_cols = [
            "Lead_ID", "Company_Name", "Priority_Tier", "Score", "VIP_Referral",
            "Region", "Language", "Industry_Vertical", "Company_Size",
            "Recent_Activity", "Assigned_Rep_ID", "Assigned_Rep_Name",
            "Assigned_Rep_Seniority", "Routing_Status", "Routing_Reason", "Score_Breakdown",
        ]
        csv_bytes = dicts_to_csv_bytes(filtered_leads, export_cols)
        st.download_button(
            label="⬇️ Export Filtered CSV",
            data=csv_bytes,
            file_name="routed_leads_export.csv",
            mime="text/csv",
            use_container_width=True,
        )

    display_rows = [
        {
            "Rank": idx + 1,
            "Lead ID": l["Lead_ID"],
            "Company": l["Company_Name"],
            "Tier": l["Priority_Tier"],
            "Score": l["Score"],
            "VIP": "⭐ Yes" if l["VIP_Referral"] else "No",
            "Region": l["Region"],
            "Language": l["Language"],
            "Industry": l["Industry_Vertical"],
            "Size": l["Company_Size"] if l["Company_Size"] is not None else "Unknown",
            "Assigned Rep": f"{l['Assigned_Rep_Name']} ({l['Assigned_Rep_ID']})",
            "Rep Level": l["Assigned_Rep_Seniority"],
            "Status": l["Routing_Status"],
            "Score Breakdown": l["Score_Breakdown"],
        }
        for idx, l in enumerate(filtered_leads[:500])
    ]
    st.dataframe(display_rows, use_container_width=True, hide_index=True, height=480)


# === TAB 2: REP CAPACITY & LOAD BALANCING ===
with tab_reps:
    st.subheader("Sales Representative Utilization & Seniority Distribution")

    # Summary metrics by Seniority
    s_cols = st.columns(3)
    for idx, level in enumerate(["Senior", "Manager", "Junior"]):
        group = [r for r in updated_reps if r["Seniority_Level"] == level]
        used = sum(r["Current_Capacity"] for r in group)
        cap = sum(r["Max_Capacity"] for r in group)
        avg_util = (used / cap * 100) if cap else 0.0
        s_cols[idx].metric(
            f"{level} Reps ({len(group):,})",
            f"{avg_util:.1f}% Avg Utilization",
            f"{used:,} / {cap:,} total capacity",
        )

    st.markdown("---")
    rep_filter_col1, rep_filter_col2 = st.columns(2)
    with rep_filter_col1:
        rep_seniority_filter = st.multiselect(
            "Filter Reps by Seniority",
            options=["Senior", "Manager", "Junior"],
            default=["Senior", "Manager", "Junior"],
        )
    with rep_filter_col2:
        rep_region_filter = st.multiselect(
            "Filter Reps by Region",
            options=["North America", "Europe", "Asia-Pacific", "Unknown"],
            default=["North America", "Europe", "Asia-Pacific"],
        )

    filtered_reps = [
        r for r in updated_reps
        if r["Seniority_Level"] in rep_seniority_filter
        and r["Region"] in rep_region_filter
    ]
    filtered_reps.sort(
        key=lambda r: (r["Current_Capacity"] / r["Max_Capacity"]) if r["Max_Capacity"] else 0,
        reverse=True,
    )

    rep_table = [
        {
            "Rep ID": r["Rep_ID"],
            "Name": r["Name"],
            "Seniority": r["Seniority_Level"],
            "Region": r["Region"],
            "Language": r["Language"],
            "Industry Expertise": r["Industry_Vertical_Expertise"],
            "Load": f"{r['Current_Capacity']} / {r['Max_Capacity']}",
            "Utilization %": round((r["Current_Capacity"] / r["Max_Capacity"] * 100), 1)
            if r["Max_Capacity"] else 0.0,
        }
        for r in filtered_reps[:400]
    ]
    st.dataframe(
        rep_table,
        use_container_width=True,
        hide_index=True,
        height=380,
        column_config={
            "Utilization %": st.column_config.ProgressColumn(
                "Utilization %",
                min_value=0,
                max_value=100,
                format="%.1f%%",
            )
        },
    )

    # Interactive Rep-to-Lead Drilldown
    st.markdown("### 🔎 Inspect Leads Assigned to a Specific Rep")
    active_rep_options = [
        f"{r['Rep_ID']} — {r['Name']} ({r['Seniority_Level']} | {r['Current_Capacity']}/{r['Max_Capacity']})"
        for r in filtered_reps if r["Current_Capacity"] > 0
    ]
    if active_rep_options:
        chosen_option = st.selectbox("Select an active rep to view their assigned queue:", active_rep_options[:200])
        chosen_rep_id = chosen_option.split(" — ")[0]
        rep_leads = [l for l in routed_leads if l["Assigned_Rep_ID"] == chosen_rep_id]
        st.dataframe(
            [
                {
                    "Lead ID": l["Lead_ID"],
                    "Company": l["Company_Name"],
                    "Tier": l["Priority_Tier"],
                    "Score": l["Score"],
                    "Industry": l["Industry_Vertical"],
                    "Score Breakdown": l["Score_Breakdown"],
                }
                for l in rep_leads
            ],
            use_container_width=True,
            hide_index=True,
        )


# === TAB 3: MANAGER REVIEW OVERFLOW QUEUE ===
with tab_overflow:
    st.subheader("Unassigned & Exception Triage Queue (Manager Review)")
    st.write(
        "Zero leads are ever dropped. Leads land here when required routing fields are missing "
        "(`Unknown`) or when all skill- and seniority-eligible reps have reached `Max_Capacity`."
    )

    # Break down overflow reasons
    reason_counts = {}
    for item in manager_review:
        reason = item["Routing_Reason"]
        reason_counts[reason] = reason_counts.get(reason, 0) + 1

    if reason_counts:
        r_cols = st.columns(min(len(reason_counts), 4))
        for idx, (reason, count) in enumerate(sorted(reason_counts.items(), key=lambda x: -x[1])[:4]):
            r_cols[idx].metric(reason, f"{count:,} leads")

    overflow_rows = [
        {
            "Lead ID": l["Lead_ID"],
            "Company": l["Company_Name"],
            "Tier": l["Priority_Tier"],
            "Score": l["Score"],
            "Region": l["Region"],
            "Language": l["Language"],
            "Industry": l["Industry_Vertical"],
            "Overflow Reason": l["Routing_Reason"],
        }
        for l in manager_review[:500]
    ]
    st.dataframe(overflow_rows, use_container_width=True, hide_index=True, height=450)


# === TAB 4: PIPELINE ANALYTICS ===
with tab_analytics:
    st.subheader("Lead Distribution & Routing Breakdown")
    chart_col1, chart_col2 = st.columns(2)

    with chart_col1:
        st.markdown("**Leads by Priority Tier**")
        tier_order = ["CRITICAL", "HIGH", "MEDIUM", "LOW"]
        tier_chart_data = {
            tier: sum(1 for l in routed_leads if l["Priority_Tier"] == tier)
            for tier in tier_order
        }
        st.bar_chart(tier_chart_data)

    with chart_col2:
        st.markdown("**Leads by Region**")
        region_order = ["North America", "Europe", "Asia-Pacific", "Unknown"]
        region_chart_data = {
            reg: sum(1 for l in routed_leads if l["Region"] == reg)
            for reg in region_order
        }
        st.bar_chart(region_chart_data)

    st.markdown("**Assigned vs. Manager Review by Priority Tier**")
    tier_status_rows = []
    for tier in tier_order:
        t_leads = [l for l in routed_leads if l["Priority_Tier"] == tier]
        assigned = sum(1 for l in t_leads if l["Routing_Status"] == "Assigned")
        review = sum(1 for l in t_leads if l["Routing_Status"] == "Manager Review")
        tier_status_rows.append({
            "Priority Tier": tier,
            "Total Leads": len(t_leads),
            "Assigned to Rep": assigned,
            "Manager Review": review,
            "Assignment Rate (%)": round((assigned / len(t_leads) * 100), 1) if t_leads else 0.0,
        })
    st.table(tier_status_rows)