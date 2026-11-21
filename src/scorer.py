"""
Lead Priority Scoring Engine (src/scorer.py)

Purpose:
    Evaluates sanitized customer lead records produced by `cleaner.py`, calculates
    a numeric priority score based on business rules, enforces VIP overrides,
    categorizes each lead into a priority tier (CRITICAL, HIGH, MEDIUM, LOW),
    and sorts the lead queue so the highest-value prospects are routed first.

Basic Algorithm:
    1. VIP Override Gate: Check `VIP_Referral`. If True, immediately assign a
       score of 100, label the lead as 'CRITICAL', and bypass standard scoring.
    2. Trait Point Summation (Non-VIPs):
       - Company Size: +50 (1,000+), +30 (100-999), +0 (1-99), or +20 if missing.
       - Recent Activity: +35 (Requested Live Demo / Contact Sales), +25 (Attended
         Webinar), +15 (Downloaded Whitepaper), +5 (Visited Pricing Page), +0 otherwise.
       - Industry Vertical: +15 (Technology), +10 (Healthcare / Finance), +0 otherwise.
    3. Tier Classification: Bucket total points into CRITICAL (85+), HIGH (60-84),
       MEDIUM (40-59), or LOW (0-39).
    4. Priority Sorting: Sort all leads in O(N log N) time by tier rank
       (CRITICAL -> HIGH -> MEDIUM -> LOW) and descending score so high-priority
       leads claim available sales representative capacity before lower tiers.
"""

from cleaner import clean_all_datasets

# Point lookup tables derived from the Scoring Logic Cheat Sheet
ACTIVITY_POINTS = {
    "Requested Live Demo": 35,
    "Contact Sales": 35,
    "Attended Webinar": 25,
    "Downloaded Whitepaper": 15,
    "Visited Pricing Page": 5,
}

INDUSTRY_POINTS = {
    "Technology": 15,
    "Healthcare": 10,
    "Finance": 10,
    "Manufacturing": 0,
    "Retail": 0,
}

TIER_RANK = {
    "CRITICAL": 0,
    "HIGH": 1,
    "MEDIUM": 2,
    "LOW": 3,
}


def score_company_size(company_size):
    """
    Calculate priority points from employee count, including the missing-data fallback.

    How it works:
        Checks for `None` first so leads with missing or blank employee counts
        receive the +20 fallback buffer rather than being penalized as small
        businesses. Valid integers are evaluated from largest tier downward
        (Enterprise 1,000+ -> +50, Mid-Market 100-999 -> +30, SMB 0-99 -> +0)
        using simple numeric comparisons in O(1) time.

    Args:
        company_size (int | None): Cleaned employee count, or None if missing.

    Returns:
        int: Points awarded for company size (0, 20, 30, or 50).
    """
    if company_size is None:
        return 20
    if company_size >= 1000:
        return 50
    if company_size >= 100:
        return 30
    return 0


def assign_priority_tier(score):
    """
    Classify a numeric lead score into its categorical priority tier.

    How it works:
        Evaluates threshold boundaries in descending order (85+, 60-84, 40-59,
        and 0-39). Checking from highest threshold to lowest ensures clean,
        mutually exclusive tier assignments without needing complex range checks.

    Args:
        score (int): Total numeric priority score for a lead.

    Returns:
        str: Priority tier label ('CRITICAL', 'HIGH', 'MEDIUM', or 'LOW').
    """
    if score >= 85:
        return "CRITICAL"
    if score >= 60:
        return "HIGH"
    if score >= 40:
        return "MEDIUM"
    return "LOW"


def score_lead(lead):
    """
    Compute the total score, priority tier, and point breakdown for a single lead.

    How it works:
        Creates a shallow copy of the cleaned lead dictionary so input data is
        never mutated in place. It tests `VIP_Referral` first to enforce the
        immediate 100-point CRITICAL override. For standard leads, it looks up
        activity and industry multipliers via O(1) dictionary `.get()` calls
        (defaulting safely to 0 for unmapped or 'None'/'Unknown' values), sums the
        three components, and stores a readable 'Score_Breakdown' string for
        dashboard transparency.

    Args:
        lead (dict): A sanitized lead dictionary produced by `cleaner.py`.

    Returns:
        dict: Enriched lead dictionary containing 'Score', 'Priority_Tier', and
              'Score_Breakdown'.
    """
    enriched = dict(lead)

    if enriched.get("VIP_Referral") is True:
        enriched["Score"] = 100
        enriched["Priority_Tier"] = "CRITICAL"
        enriched["Score_Breakdown"] = "VIP Override (100)"
        return enriched

    size_pts = score_company_size(enriched.get("Company_Size"))
    activity_pts = ACTIVITY_POINTS.get(enriched.get("Recent_Activity", "None"), 0)
    industry_pts = INDUSTRY_POINTS.get(enriched.get("Industry_Vertical", "Unknown"), 0)

    total_score = size_pts + activity_pts + industry_pts
    tier = assign_priority_tier(total_score)

    enriched["Score"] = total_score
    enriched["Priority_Tier"] = tier
    enriched["Score_Breakdown"] = (
        f"Size: +{size_pts} | Activity: +{activity_pts} | Industry: +{industry_pts}"
    )
    return enriched


def score_and_sort_leads(cleaned_leads):
    """
    Score an entire list of cleaned leads and sort them in routing priority order.

    How it works:
        Transforms each lead with `score_lead()` in a single O(N) pass, then sorts
        the resulting list using a tuple key `(TIER_RANK[tier], -score)`. Mapping
        tiers to integer ranks (0 for CRITICAL through 3 for LOW) and negating
        the numeric score orders leads from most urgent to least urgent so the
        downstream router allocates rep capacity to top prospects first.

    Args:
        cleaned_leads (list[dict]): Sanitized lead dictionaries from `cleaner.py`.

    Returns:
        list[dict]: Scored lead dictionaries sorted from highest to lowest priority.
    """
    scored = [score_lead(lead) for lead in cleaned_leads]
    scored.sort(
        key=lambda item: (
            TIER_RANK[item["Priority_Tier"]],
            -item["Score"],
            not item.get("VIP_Referral", False),
            -(item.get("Company_Size") or 0),
            item.get("Lead_ID", ""),
        )
    )
    return scored

if __name__ == "__main__":
    print("Running lead scorer verification...\n")
    datasets = clean_all_datasets()
    sample_leads = datasets.get("leads_scale", [])

    if not sample_leads:
        print("[ERROR] No sample leads found. Verify leads_sample.csv is in Data/.")
    else:
        scored_leads = score_and_sort_leads(sample_leads)

        # Audit priority tier distribution against expected baseline (~10% Crit, 20% High, 40% Med, 30% Low)
        tier_counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
        for lead in scored_leads:
            tier_counts[lead["Priority_Tier"]] += 1

        print("=== Priority Tier Distribution (leads_sample) ===")
        for tier, count in tier_counts.items():
            pct = (count / len(scored_leads)) * 100
            print(f"  {tier:<8}: {count:>3} leads ({pct:.1f}%)")

        print(f"\n=== All {len(scored_leads)} Prioritized Leads ===")
        for rank, lead in enumerate(scored_leads, start=1):
            print(
                f"  #{rank:<3} | {lead['Lead_ID']} | {lead['Company_Name']:<22} | "
                f"{lead['Priority_Tier']:<8} | Score: {lead['Score']:>3} | "
                f"{lead['Score_Breakdown']}"
            )