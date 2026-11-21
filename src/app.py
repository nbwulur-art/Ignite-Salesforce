"""
Manager Lead Prioritization & Routing Dashboard (src/app.py)

Purpose:
    Minimalist, executive-grade Streamlit dashboard for inspecting prioritized
    leads, verifying multi-skill routing & seniority rules, monitoring rep
    capacity utilization, triaging Manager Review overflow, and simulating
    live incoming leads.

How to Customize:
    Edit the `THEME` dictionary right below to change colors, accents, or
    chart palettes across the entire app in one place.

How to Run:
    streamlit run src/app.py
"""

import csv
import io
import os
import sys
import time
import matplotlib.pyplot as plt
import streamlit as st

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from cleaner import clean_all_datasets, clean_lead_record
from scorer import score_and_sort_leads
from router import route_leads

# ---------------------------------------------------------------------------
# 1. CUSTOMIZABLE DESIGN TOKENS (Edit colors here to restyle the whole app)
# ---------------------------------------------------------------------------
THEME = {
    "bg": "#F8FAFC",              # Main canvas background
    "surface": "#FFFFFF",         # Card & table background
    "sidebar_bg": "#F1F5F9",      # Sidebar background
    "text_primary": "#0F172A",    # Deep slate ink
    "text_muted": "#64748B",      # Secondary labels
    "border": "#E2E8F0",          # Crisp 1px hairline borders
    "accent": "#0F172A",          # Primary button / active tab ink
    "brand": "#2563EB",           # Cobalt highlight accent
    "tiers": {
        "CRITICAL": "#E11D48",    # Crimson rose
        "HIGH": "#D97706",        # Warm amber
        "MEDIUM": "#2563EB",      # Royal blue
        "LOW": "#94A3B8",         # Cool slate
    },
    "regions": ["#0F172A", "#2563EB", "#0D9488", "#CBD5E1"],
}

# ---------------------------------------------------------------------------
# 2. PAGE CONFIG & INJECTED CSS
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Ignite | Lead Routing Command",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    f"""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@500;600&family=Plus+Jakarta+Sans:wght@400;500;600;700&display=swap');

    html, body, [class*="css"] {{
        font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, sans-serif;
        color: {THEME["text_primary"]};
        background-color: {THEME["bg"]};
    }}

    /* Clean up default Streamlit chrome */
    #MainMenu, footer, header {{visibility: hidden;}}
    .block-container {{
        padding-top: 1.75rem;
        padding-bottom: 2.5rem;
        max-width: 1440px;
    }}

    /* Sidebar styling */
    section[data-testid="stSidebar"] {{
        background-color: {THEME["sidebar_bg"]};
        border-right: 1px solid {THEME["border"]};
    }}

    /* Executive Header Banner */
    .hero-header {{
        background: {THEME["surface"]};
        border: 1px solid {THEME["border"]};
        border-radius: 14px;
        padding: 1.35rem 1.75rem;
        margin-bottom: 1.25rem;
        display: flex;
        justify-content: space-between;
        align-items: center;
        box-shadow: 0 1px 3px rgba(15, 23, 42, 0.04);
    }}
    .hero-title {{
        font-size: 1.45rem;
        font-weight: 700;
        letter-spacing: -0.025em;
        margin: 0;
        color: {THEME["text_primary"]};
    }}
    .hero-sub {{
        font-size: 0.88rem;
        color: {THEME["text_muted"]};
        margin: 0.25rem 0 0 0;
    }}
    .status-pill {{
        font-family: 'JetBrains Mono', monospace;
        font-size: 0.78rem;
        font-weight: 600;
        color: #059669;
        background: #ECFDF5;
        border: 1px solid #A7F3D0;
        padding: 0.35rem 0.8rem;
        border-radius: 999px;
        white-space: nowrap;
    }}

    /* Minimalist KPI Cards */
    div[data-testid="stMetric"] {{
        background-color: {THEME["surface"]};
        border: 1px solid {THEME["border"]};
        border-radius: 12px;
        padding: 1rem 1.15rem;
        box-shadow: 0 1px 2px rgba(15, 23, 42, 0.03);
        transition: border-color 0.15s ease;
    }}
    div[data-testid="stMetric"]:hover {{
        border-color: #CBD5E1;
    }}
    div[data-testid="stMetric"] label {{
        font-size: 0.78rem !important;
        text-transform: uppercase;
        letter-spacing: 0.04em;
        color: {THEME["text_muted"]} !important;
        font-weight: 600 !important;
    }}
    div[data-testid="stMetric"] div[data-testid="stMetricValue"] {{
        font-family: 'JetBrains Mono', monospace;
        font-size: 1.55rem !important;
        font-weight: 600 !important;
        letter-spacing: -0.03em;
        color: {THEME["text_primary"]} !important;
    }}

    /* Sleek Pill Tabs */
    .stTabs [data-baseweb="tab-list"] {{
        gap: 0.4rem;
        background-color: {THEME["sidebar_bg"]};
        padding: 0.3rem;
        border-radius: 10px;
        border: 1px solid {THEME["border"]};
    }}
    .stTabs [data-baseweb="tab"] {{
        border-radius: 7px;
        padding: 0.45rem 1rem;
        font-weight: 600;
        font-size: 0.86rem;
        color: {THEME["text_muted"]};
    }}
    .stTabs [aria-selected="true"] {{
        background-color: {THEME["surface"]} !important;
        color: {THEME["text_primary"]} !important;
        box-shadow: 0 1px 2px rgba(15, 23, 42, 0.06);
    }}

    /* Primary Buttons */
    .stButton > button, .stDownloadButton > button {{
        border-radius: 8px;
        font-weight: 600;
        font-size: 0.85rem;
        border: 1px solid {THEME["border"]};
        transition: all 0.15s ease;
    }}
    .stFormSubmitButton > button {{
        background-color: {THEME["accent"]} !important;
        color: #FFFFFF !important;
        border: none !important;
        border-radius: 8px;
        font-weight: 600;
    }}
    </style>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# 3. CACHED DATA & PIPELINE EXECUTION
# ---------------------------------------------------------------------------
@st.cache_data(show_spinner=False)
def load_baseline_data():
    """Load and sanitize the 50,000-lead and 1,600-rep scale datasets once."""
    return clean_all_datasets()


def execute_pipeline(leads, reps):
    """Score, sort, and route leads while recording exact runtime in ms."""
    start = time.perf_counter()
    scored = score_and_sort_leads(leads)
    routed_payload = route_leads(scored, reps)
    routed_payload["elapsed_ms"] = (time.perf_counter() - start) * 1000
    return routed_payload


def dicts_to_csv_bytes(records, columns):
    """Convert filtered records into downloadable UTF-8 CSV bytes."""
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(records)
    return buffer.getvalue().encode("utf-8")


def plot_minimal_bar_chart(labels, values, colors, title):
    """Render a clean, publication-grade Matplotlib bar chart matching THEME."""
    fig, ax = plt.subplots(figsize=(6, 3.8), dpi=140)
    fig.patch.set_facecolor(THEME["surface"])
    ax.set_facecolor(THEME["surface"])

    bars = ax.bar(labels, values, color=colors, width=0.5, zorder=3)

    ax.set_title(title, fontsize=11, fontweight="bold", loc="left", pad=14, color=THEME["text_primary"])
    ax.tick_params(axis="x", colors=THEME["text_primary"], labelsize=9, length=0, pad=8)
    ax.tick_params(axis="y", colors=THEME["text_muted"], labelsize=8.5, length=0)

    for spine in ["top", "right", "left"]:
        ax.spines[spine].set_visible(False)
    ax.spines["bottom"].set_color(THEME["border"])
    ax.spines["bottom"].set_linewidth(1)

    ax.grid(axis="y", linestyle="-", linewidth=0.6, color=THEME["border"], zorder=0)

    max_val = max(values) if values else 1
    ax.set_ylim(0, max_val * 1.18 if max_val > 0 else 10)

    for bar in bars:
        height = bar.get_height()
        ax.annotate(
            f"{int(height):,}",
            xy=(bar.get_x() + bar.get_width() / 2, height),
            xytext=(0, 5),
            textcoords="offset points",
            ha="center",
            va="bottom",
            fontsize=8.5,
            fontweight="bold",
            color=THEME["text_primary"],
        )

    fig.tight_layout()
    return fig


# ---------------------------------------------------------------------------
# 4. PIPELINE RUN & SESSION STATE
# ---------------------------------------------------------------------------
baseline = load_baseline_data()
base_leads = baseline.get("leads_scale", [])
base_reps = baseline.get("reps_scale", [])

if not base_leads or not base_reps:
    st.error("Missing `leads_scale.csv` or `reps_scale.csv` in `Data/`.")
    st.stop()

if "custom_leads" not in st.session_state:
    st.session_state.custom_leads = []

active_leads = base_leads + st.session_state.custom_leads
result = execute_pipeline(active_leads, base_reps)

routed_leads = result["routed_leads"]
manager_review = result["manager_review"]
updated_reps = result["reps"]
elapsed_ms = result["elapsed_ms"]


# ---------------------------------------------------------------------------
# 5. SIDEBAR: FILTERS & LIVE SIMULATOR
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown("### Filters")
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
        "Quick Search",
        placeholder="Lead ID, company, or rep...",
    ).strip().lower()

    st.divider()
    st.markdown("### Simulate Live Lead")
    with st.form("live_lead_form", clear_on_submit=True):
        sim_company = st.text_input("Company", value="Lone Star Robotics")
        c1, c2 = st.columns(2)
        sim_region = c1.selectbox("Region", ["North America", "Europe", "Asia-Pacific", "Unknown"])
        sim_lang = c2.selectbox("Language", ["English", "Spanish", "German", "Unknown"])
        sim_industry = st.selectbox(
            "Industry",
            ["Technology", "Finance", "Healthcare", "Manufacturing", "Retail", "Unknown"],
        )
        sim_size = st.number_input("Employees", min_value=0, max_value=100000, value=2500, step=100)
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
        sim_vip = st.checkbox("VIP Referral Override", value=False)
        if st.form_submit_button("Route New Lead", use_container_width=True):
            new_id = f"L-LIVE-{len(st.session_state.custom_leads) + 1:03d}"
            st.session_state.custom_leads.append(
                clean_lead_record({
                    "Lead_ID": new_id,
                    "Company_Name": sim_company or "New Prospect Inc",
                    "Region": sim_region,
                    "Language": sim_lang,
                    "Industry_Vertical": sim_industry,
                    "Company_Size": str(sim_size) if sim_size > 0 else "",
                    "Recent_Activity": sim_activity,
                    "VIP_Referral": str(sim_vip),
                })
            )
            st.rerun()

    if st.session_state.custom_leads:
        if st.button("Reset Simulated Leads", use_container_width=True):
            st.session_state.custom_leads = []
            st.rerun()


# ---------------------------------------------------------------------------
# 6. FILTERED VIEW & HEADER
# ---------------------------------------------------------------------------
filtered_leads = [
    l for l in routed_leads
    if l["Priority_Tier"] in selected_tiers
    and l["Region"] in selected_regions
    and (status_filter != "Assigned Only" or l["Routing_Status"] == "Assigned")
    and (status_filter != "Manager Review Only" or l["Routing_Status"] == "Manager Review")
    and (
        not search_query
        or search_query in f"{l['Lead_ID']} {l['Company_Name']} {l['Assigned_Rep_Name']} {l['Assigned_Rep_ID']}".lower()
    )
]

st.markdown(
    f"""
    <div class="hero-header">
        <div>
            <p class="hero-title">Ignite Lead Routing Command</p>
            <p class="hero-sub">Deterministic scoring, tie-breaking, multi-skill matching & load balancing</p>
        </div>
        <div class="status-pill">● ENGINE READY · {elapsed_ms:.1f} ms</div>
    </div>
    """,
    unsafe_allow_html=True,
)

total_leads = len(routed_leads)
assigned_total = total_leads - len(manager_review)
assigned_pct = (assigned_total / total_leads * 100) if total_leads else 0.0
critical_total = sum(1 for l in routed_leads if l["Priority_Tier"] == "CRITICAL")
junior_violations = sum(
    1 for l in routed_leads
    if l["Priority_Tier"] == "CRITICAL" and l["Assigned_Rep_Seniority"] == "Junior"
)

k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("Leads Processed", f"{total_leads:,}")
k2.metric("Routed to Reps", f"{assigned_total:,}", f"{assigned_pct:.1f}% matched")
k3.metric("Critical Tier", f"{critical_total:,}", f"{junior_violations} Junior violations")
k4.metric("Manager Overflow", f"{len(manager_review):,}", "Needs triage")
k5.metric("Active Reps", f"{len(updated_reps):,}", f"{elapsed_ms:.1f} ms runtime")

st.markdown("<div style='height: 0.75rem;'></div>", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# 7. DASHBOARD TABS
# ---------------------------------------------------------------------------
tab_queue, tab_reps, tab_overflow, tab_analytics = st.tabs([
    f"Prioritized Queue ({len(filtered_leads):,})",
    f"Rep Capacity ({len(updated_reps):,})",
    f"Manager Review ({len(manager_review):,})",
    "Analytics",
])

# === TAB 1: QUEUE ===
with tab_queue:
    top_l, top_r = st.columns([4, 1])
    with top_l:
        st.caption(
            "Ordered by **Tier → Score → VIP Status → Company Size → Arrival ID** (showing top 500 matches)."
        )
    with top_r:
        export_cols = [
            "Lead_ID", "Company_Name", "Priority_Tier", "Score", "VIP_Referral",
            "Region", "Language", "Industry_Vertical", "Company_Size",
            "Recent_Activity", "Assigned_Rep_ID", "Assigned_Rep_Name",
            "Assigned_Rep_Seniority", "Routing_Status", "Routing_Reason", "Score_Breakdown",
        ]
        st.download_button(
            label="Export CSV",
            data=dicts_to_csv_bytes(filtered_leads, export_cols),
            file_name="routed_leads_export.csv",
            mime="text/csv",
            use_container_width=True,
        )

    queue_rows = [
        {
            "Rank": idx + 1,
            "Lead ID": l["Lead_ID"],
            "Company": l["Company_Name"],
            "Tier": l["Priority_Tier"],
            "Score": l["Score"],
            "VIP": "Yes" if l["VIP_Referral"] else "—",
            "Region": l["Region"],
            "Language": l["Language"],
            "Industry": l["Industry_Vertical"],
            "Size": f"{l['Company_Size']:,}" if l["Company_Size"] is not None else "Unknown",
            "Assigned Rep": f"{l['Assigned_Rep_Name']} ({l['Assigned_Rep_ID']})",
            "Seniority": l["Assigned_Rep_Seniority"],
            "Status": l["Routing_Status"],
            "Score Breakdown": l["Score_Breakdown"],
        }
        for idx, l in enumerate(filtered_leads[:500])
    ]
    st.dataframe(queue_rows, use_container_width=True, hide_index=True, height=490)


# === TAB 2: REP CAPACITY ===
with tab_reps:
    s_cols = st.columns(3)
    for idx, level in enumerate(["Senior", "Manager", "Junior"]):
        group = [r for r in updated_reps if r["Seniority_Level"] == level]
        used = sum(r["Current_Capacity"] for r in group)
        cap = sum(r["Max_Capacity"] for r in group)
        avg_util = (used / cap * 100) if cap else 0.0
        s_cols[idx].metric(
            f"{level} Reps ({len(group):,})",
            f"{avg_util:.1f}%",
            f"{used:,} / {cap:,} slots filled",
        )

    st.markdown("<div style='height: 0.5rem;'></div>", unsafe_allow_html=True)
    f1, f2 = st.columns(2)
    rep_sen = f1.multiselect("Seniority", ["Senior", "Manager", "Junior"], default=["Senior", "Manager", "Junior"])
    rep_reg = f2.multiselect("Region", ["North America", "Europe", "Asia-Pacific", "Unknown"], default=["North America", "Europe", "Asia-Pacific"])

    filtered_reps = sorted(
        [
            r for r in updated_reps
            if r["Seniority_Level"] in rep_sen and r["Region"] in rep_reg
        ],
        key=lambda r: (r["Current_Capacity"] / r["Max_Capacity"]) if r["Max_Capacity"] else 0,
        reverse=True,
    )

    rep_rows = [
        {
            "Rep ID": r["Rep_ID"],
            "Name": r["Name"],
            "Seniority": r["Seniority_Level"],
            "Region": r["Region"],
            "Language": r["Language"],
            "Industry": r["Industry_Vertical_Expertise"],
            "Load": f"{r['Current_Capacity']} / {r['Max_Capacity']}",
            "Utilization": round((r["Current_Capacity"] / r["Max_Capacity"] * 100), 1)
            if r["Max_Capacity"] else 0.0,
        }
        for r in filtered_reps[:400]
    ]
    st.dataframe(
        rep_rows,
        use_container_width=True,
        hide_index=True,
        height=370,
        column_config={
            "Utilization": st.column_config.ProgressColumn(
                "Utilization",
                min_value=0,
                max_value=100,
                format="%.1f%%",
            )
        },
    )

    st.markdown("#### Inspect Rep Queue")
    active_options = [
        f"{r['Rep_ID']} — {r['Name']} ({r['Seniority_Level']} · {r['Current_Capacity']}/{r['Max_Capacity']})"
        for r in filtered_reps if r["Current_Capacity"] > 0
    ]
    if active_options:
        picked = st.selectbox("Select representative", active_options[:200], label_visibility="collapsed")
        picked_id = picked.split(" — ")[0]
        rep_leads = [l for l in routed_leads if l["Assigned_Rep_ID"] == picked_id]
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


# === TAB 3: MANAGER REVIEW ===
with tab_overflow:
    st.caption(
        "Leads routed here either lacked required skill fields (`Unknown`) or arrived after all eligible reps hit `Max_Capacity`."
    )
    reason_counts = {}
    for item in manager_review:
        reason_counts[item["Routing_Reason"]] = reason_counts.get(item["Routing_Reason"], 0) + 1

    if reason_counts:
        r_cols = st.columns(min(len(reason_counts), 4))
        for idx, (reason, count) in enumerate(sorted(reason_counts.items(), key=lambda x: -x[1])[:4]):
            r_cols[idx].metric(reason, f"{count:,}")

    st.markdown("<div style='height: 0.5rem;'></div>", unsafe_allow_html=True)
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


# === TAB 4: ANALYTICS ===
with tab_analytics:
    c_left, c_right = st.columns(2)

    tier_order = ["CRITICAL", "HIGH", "MEDIUM", "LOW"]
    tier_counts = [sum(1 for l in routed_leads if l["Priority_Tier"] == t) for t in tier_order]
    tier_colors = [THEME["tiers"][t] for t in tier_order]

    with c_left:
        fig1 = plot_minimal_bar_chart(tier_order, tier_counts, tier_colors, "Leads by Priority Tier")
        st.pyplot(fig1)
        plt.close(fig1)

    region_order = ["North America", "Europe", "Asia-Pacific", "Unknown"]
    region_counts = [sum(1 for l in routed_leads if l["Region"] == reg) for reg in region_order]

    with c_right:
        fig2 = plot_minimal_bar_chart(region_order, region_counts, THEME["regions"], "Leads by Region")
        st.pyplot(fig2)
        plt.close(fig2)

    st.markdown("#### Routing Breakdown by Tier")
    summary_rows = []
    for tier in tier_order:
        t_leads = [l for l in routed_leads if l["Priority_Tier"] == tier]
        assigned = sum(1 for l in t_leads if l["Routing_Status"] == "Assigned")
        review = sum(1 for l in t_leads if l["Routing_Status"] == "Manager Review")
        summary_rows.append({
            "Priority Tier": tier,
            "Total Leads": f"{len(t_leads):,}",
            "Assigned": f"{assigned:,}",
            "Manager Review": f"{review:,}",
            "Assignment Rate": f"{(assigned / len(t_leads) * 100):.1f}%" if t_leads else "0.0%",
        })
    st.dataframe(summary_rows, use_container_width=True, hide_index=True)