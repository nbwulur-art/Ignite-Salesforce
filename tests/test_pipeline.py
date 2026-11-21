"""
Automated Edge-Case & Pipeline Verification Suite (tests/test_pipeline.py)

Purpose:
    Validates every stage of the lead prioritization and routing pipeline
    (`cleaner.py` -> `scorer.py` -> `router.py`) using deterministic unit tests
    and an end-to-end 50,000-record scale benchmark to prove resilience against
    messy data, capacity exhaustion, and business rule violations.

Basic Algorithm:
    1. Path Setup: Inserts `src/` onto `sys.path` so test functions import
       `cleaner`, `scorer`, and `router` cleanly regardless of working directory.
    2. Unit & Edge-Case Assertions: Exercises isolated synthetic records for
       alias normalization, missing-value fallbacks, VIP overrides, score tie-breakers,
       CRITICAL seniority gating (Senior -> Manager fallback, Junior blocked),
       least-utilization balancing, and Manager Review overflow capture.
    3. Scale Stress Verification: Runs the full 50,000-lead / 1,600-rep dataset
       in memory if present in `Data/` and asserts sub-2-second execution with
       zero Junior CRITICAL violations.
"""

import os
import sys
import time
import pytest

# Ensure `src/` modules are importable when running `pytest` from the repo root
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(REPO_ROOT, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from cleaner import clean_lead_record, clean_rep_record, clean_all_datasets
from scorer import score_lead, score_and_sort_leads
from router import route_leads


# ---------------------------------------------------------------------------
# 1. Data Sanitization & Missing-Value Fallback Tests (`cleaner.py`)
# ---------------------------------------------------------------------------

def test_cleaner_normalizes_messy_aliases_and_whitespace():
    """Verify typos, mixed casing, leading spaces, and shorthand numbers clean properly."""
    raw_lead = {
        "Lead_ID": " L-901 ",
        "Company_Name": "  Acme Corp  ",
        "Region": "  Asa-Pacific ",
        "Language": " de ",
        "Industry_Vertical": " TECHNOLOGY ",
        "Company_Size": "2,500",
        "Recent_Activity": "  requested live demo ",
        "VIP_Referral": "TRUE",
    }
    cleaned = clean_lead_record(raw_lead)

    assert cleaned["Lead_ID"] == "L-901"
    assert cleaned["Company_Name"] == "Acme Corp"
    assert cleaned["Region"] == "Asia-Pacific"
    assert cleaned["Language"] == "German"
    assert cleaned["Industry_Vertical"] == "Technology"
    assert cleaned["Company_Size"] == 2500
    assert cleaned["Recent_Activity"] == "Requested Live Demo"
    assert cleaned["VIP_Referral"] is True


def test_cleaner_missing_values_and_capacity_clamping():
    """Verify blank Company_Size becomes None (+20 fallback) and rep capacity clamps safely."""
    raw_lead = {
        "Lead_ID": "L-902",
        "Company_Name": "Mystery Inc",
        "Region": "",
        "Language": "N/A",
        "Industry_Vertical": "Unknown",
        "Company_Size": "",
        "Recent_Activity": "N/A",
        "VIP_Referral": "Unknown",
    }
    cleaned_lead = clean_lead_record(raw_lead)

    assert cleaned_lead["Region"] == "Unknown"
    assert cleaned_lead["Language"] == "Unknown"
    assert cleaned_lead["Industry_Vertical"] == "Unknown"
    assert cleaned_lead["Company_Size"] is None
    assert cleaned_lead["Recent_Activity"] == "None"
    assert cleaned_lead["VIP_Referral"] is False

    raw_rep = {
        "Rep_ID": "R-901",
        "Name": "Alex Rivera",
        "Region": "EUR",
        "Language": "ES",
        "Industry_Vertical_Expertise": " Finance ",
        "Seniority_Level": "SR",
        "Current_Capacity": "30",  # Exceeds Max_Capacity; must clamp to 20
        "Max_Capacity": "20",
    }
    cleaned_rep = clean_rep_record(raw_rep)

    assert cleaned_rep["Region"] == "Europe"
    assert cleaned_rep["Language"] == "Spanish"
    assert cleaned_rep["Industry_Vertical_Expertise"] == "Finance"
    assert cleaned_rep["Seniority_Level"] == "Senior"
    assert cleaned_rep["Current_Capacity"] == 20
    assert cleaned_rep["Max_Capacity"] == 20


# ---------------------------------------------------------------------------
# 2. Scoring Matrix, VIP Override & Tie-Breaker Tests (`scorer.py`)
# ---------------------------------------------------------------------------

def test_scorer_vip_override_bypasses_low_traits():
    """VIP_Referral=True must immediately score 100 and classify as CRITICAL."""
    lead = clean_lead_record({
        "Lead_ID": "L-VIP",
        "Company_Name": "Tiny VIP LLC",
        "Region": "North America",
        "Language": "English",
        "Industry_Vertical": "Retail",     # Normally +0
        "Company_Size": "5",               # Normally +0
        "Recent_Activity": "None",         # Normally +0
        "VIP_Referral": "True",
    })
    scored = score_lead(lead)

    assert scored["Score"] == 100
    assert scored["Priority_Tier"] == "CRITICAL"


def test_scorer_standard_matrix_and_missing_size_fallback():
    """Verify exact point summation and the +20 fallback for blank Company_Size."""
    # Enterprise (+50) + Requested Live Demo (+35) + Technology (+15) = 100 -> CRITICAL
    enterprise_tech = score_lead(clean_lead_record({
        "Lead_ID": "L-1",
        "Company_Name": "TechGiant",
        "Region": "North America",
        "Language": "English",
        "Industry_Vertical": "Technology",
        "Company_Size": "1500",
        "Recent_Activity": "Requested Live Demo",
        "VIP_Referral": "False",
    }))
    assert enterprise_tech["Score"] == 100
    assert enterprise_tech["Priority_Tier"] == "CRITICAL"

    # Missing Size (+20 fallback) + Attended Webinar (+25) + Healthcare (+10) = 55 -> MEDIUM
    missing_size_lead = score_lead(clean_lead_record({
        "Lead_ID": "L-2",
        "Company_Name": "MedStart",
        "Region": "Europe",
        "Language": "German",
        "Industry_Vertical": "Healthcare",
        "Company_Size": "",
        "Recent_Activity": "Attended Webinar",
        "VIP_Referral": "False",
    }))
    assert missing_size_lead["Score"] == 55
    assert missing_size_lead["Priority_Tier"] == "MEDIUM"


def test_scorer_tie_breaker_order():
    """Verify score ties break by VIP status -> larger Company_Size -> Lead_ID."""
    leads = [
        clean_lead_record({
            "Lead_ID": "L-SMALL",
            "Company_Name": "Small Tech",
            "Region": "North America",
            "Language": "English",
            "Industry_Vertical": "Technology",  # +15
            "Company_Size": "1200",             # +50
            "Recent_Activity": "Requested Live Demo",  # +35 -> Total 100 (Non-VIP)
            "VIP_Referral": "False",
        }),
        clean_lead_record({
            "Lead_ID": "L-BIG",
            "Company_Name": "Big Tech",
            "Region": "North America",
            "Language": "English",
            "Industry_Vertical": "Technology",  # +15
            "Company_Size": "9000",             # +50
            "Recent_Activity": "Requested Live Demo",  # +35 -> Total 100 (Non-VIP)
            "VIP_Referral": "False",
        }),
        clean_lead_record({
            "Lead_ID": "L-VIP",
            "Company_Name": "VIP Startup",
            "Region": "North America",
            "Language": "English",
            "Industry_Vertical": "Retail",
            "Company_Size": "10",
            "Recent_Activity": "None",
            "VIP_Referral": "True",             # Total 100 (VIP)
        }),
    ]
    sorted_leads = score_and_sort_leads(leads)
    assert [l["Lead_ID"] for l in sorted_leads] == ["L-VIP", "L-BIG", "L-SMALL"]


# ---------------------------------------------------------------------------
# 3. Seniority Gating, Load Balancing & Overflow Tests (`router.py`)
# ---------------------------------------------------------------------------

def test_router_critical_seniority_hierarchy_and_junior_block():
    """
    CRITICAL leads must route to Senior first, fallback to Manager when Senior
    is full, and NEVER route to Junior—even when Junior has open capacity.
    """
    reps = [
        clean_rep_record({
            "Rep_ID": "R-JR",
            "Name": "Junior Rep",
            "Region": "North America",
            "Language": "English",
            "Industry_Vertical_Expertise": "Technology",
            "Seniority_Level": "Junior",
            "Current_Capacity": "0",
            "Max_Capacity": "50",
        }),
        clean_rep_record({
            "Rep_ID": "R-SR",
            "Name": "Senior Rep",
            "Region": "North America",
            "Language": "English",
            "Industry_Vertical_Expertise": "Technology",
            "Seniority_Level": "Senior",
            "Current_Capacity": "0",
            "Max_Capacity": "1",
        }),
        clean_rep_record({
            "Rep_ID": "R-MGR",
            "Name": "Manager Rep",
            "Region": "North America",
            "Language": "English",
            "Industry_Vertical_Expertise": "Technology",
            "Seniority_Level": "Manager",
            "Current_Capacity": "0",
            "Max_Capacity": "1",
        }),
    ]

    # Create 3 CRITICAL VIP leads in the same bucket
    raw_leads = [
        {
            "Lead_ID": f"L-CRIT-{i}",
            "Company_Name": f"VIP Corp {i}",
            "Region": "North America",
            "Language": "English",
            "Industry_Vertical": "Technology",
            "Company_Size": "5000",
            "Recent_Activity": "Requested Live Demo",
            "VIP_Referral": "True",
        }
        for i in range(1, 4)
    ]
    scored = score_and_sort_leads([clean_lead_record(r) for r in raw_leads])
    result = route_leads(scored, reps)
    routed = result["routed_leads"]

    # 1st Critical -> Senior, 2nd Critical -> Manager fallback, 3rd Critical -> Manager Review (Junior blocked!)
    assert routed[0]["Assigned_Rep_ID"] == "R-SR"
    assert routed[1]["Assigned_Rep_ID"] == "R-MGR"
    assert routed[2]["Routing_Status"] == "Manager Review"
    assert len(result["manager_review"]) == 1

    # Confirm Junior still has 0 leads
    junior_state = next(r for r in result["reps"] if r["Rep_ID"] == "R-JR")
    assert junior_state["Current_Capacity"] == 0


def test_router_least_utilization_load_balancing():
    """Leads must distribute evenly by utilization ratio (Current / Max) across eligible reps."""
    reps = [
        clean_rep_record({
            "Rep_ID": "R-A",
            "Name": "Rep A",
            "Region": "Europe",
            "Language": "English",
            "Industry_Vertical_Expertise": "Retail",
            "Seniority_Level": "Junior",
            "Current_Capacity": "0",
            "Max_Capacity": "10",
        }),
        clean_rep_record({
            "Rep_ID": "R-B",
            "Name": "Rep B",
            "Region": "Europe",
            "Language": "English",
            "Industry_Vertical_Expertise": "Retail",
            "Seniority_Level": "Junior",
            "Current_Capacity": "0",
            "Max_Capacity": "10",
        }),
    ]
    leads = [
        clean_lead_record({
            "Lead_ID": f"L-LOW-{i}",
            "Company_Name": f"Shop {i}",
            "Region": "Europe",
            "Language": "English",
            "Industry_Vertical": "Retail",
            "Company_Size": "20",
            "Recent_Activity": "Visited Pricing Page",
            "VIP_Referral": "False",
        })
        for i in range(4)
    ]
    result = route_leads(score_and_sort_leads(leads), reps)
    rep_loads = {r["Rep_ID"]: r["Current_Capacity"] for r in result["reps"]}

    assert rep_loads["R-A"] == 2
    assert rep_loads["R-B"] == 2


def test_router_missing_skill_diverts_to_manager_review():
    """Leads with 'Unknown' Region, Language, or Industry go safely to Manager Review."""
    reps = [
        clean_rep_record({
            "Rep_ID": "R-1",
            "Name": "Rep One",
            "Region": "North America",
            "Language": "English",
            "Industry_Vertical_Expertise": "Finance",
            "Seniority_Level": "Senior",
            "Current_Capacity": "0",
            "Max_Capacity": "20",
        })
    ]
    incomplete_lead = score_and_sort_leads([
        clean_lead_record({
            "Lead_ID": "L-MISSING",
            "Company_Name": "Unknown Region Corp",
            "Region": "",  # Becomes "Unknown"
            "Language": "English",
            "Industry_Vertical": "Finance",
            "Company_Size": "500",
            "Recent_Activity": "Attended Webinar",
            "VIP_Referral": "False",
        })
    ])
    result = route_leads(incomplete_lead, reps)

    assert len(result["manager_review"]) == 1
    assert result["manager_review"][0]["Lead_ID"] == "L-MISSING"
    assert "Missing Region" in result["manager_review"][0]["Routing_Reason"]


# ---------------------------------------------------------------------------
# 4. Full 50,000-Record Scale Benchmark Test
# ---------------------------------------------------------------------------

def test_full_scale_pipeline_performance_and_invariants():
    """Run the 50,000-lead / 1,600-rep scale dataset and verify speed and constraints."""
    datasets = clean_all_datasets()
    leads = datasets.get("leads_scale", [])
    reps = datasets.get("reps_scale", [])

    if not leads or not reps:
        pytest.skip("Scale CSV datasets not present in Data/ directory.")

    start = time.perf_counter()
    scored = score_and_sort_leads(leads)
    result = route_leads(scored, reps)
    elapsed_sec = time.perf_counter() - start

    # Must complete in under 2 seconds in memory
    assert elapsed_sec < 2.0
    # Zero dropped records: every input lead appears in routed_leads
    assert len(result["routed_leads"]) == len(leads)
    # Zero Junior reps ever assigned a CRITICAL lead
    junior_criticals = [
        l for l in result["routed_leads"]
        if l["Priority_Tier"] == "CRITICAL" and l["Assigned_Rep_Seniority"] == "Junior"
    ]
    assert len(junior_criticals) == 0
    # No rep ever exceeds Max_Capacity
    overloaded_reps = [
        r for r in result["reps"] if r["Current_Capacity"] > r["Max_Capacity"]
    ]
    assert len(overloaded_reps) == 0