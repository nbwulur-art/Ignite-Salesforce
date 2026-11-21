"""
Smart Lead Routing & Load-Balancing Engine (src/router.py)

Purpose:
    Assigns priority-sorted leads from `scorer.py` to sanitized sales
    representatives from `cleaner.py` while enforcing strict multi-skill
    matching (Region, Language, Industry Vertical), seniority gates for
    CRITICAL leads, maximum capacity limits, proportional workload balancing,
    and overflow handling into a visible Manager Review queue.

Basic Algorithm:
    1. Skill & Seniority Indexing: Pre-group all reps with positive capacity
       into an O(1) hash map keyed by `(Region, Language, Industry)` and split
       into `Senior`, `Manager`, and `Junior` lists.
    2. Missing-Skill Fallback: If a lead is missing Region, Language, or
       Industry (`"Unknown"`), divert immediately to `Manager Review`.
    3. Seniority Gate:
       - CRITICAL leads check `Senior` reps first, then fallback to `Manager`
         reps. `Junior` reps are strictly excluded.
       - HIGH, MEDIUM, and LOW leads consider all matching reps (`Junior`,
         `Senior`, and `Manager`).
    4. Least-Utilization Scheduling: Among eligible reps with remaining capacity
       (`Current_Capacity < Max_Capacity`), select the rep with the lowest
       utilization ratio (`Current_Capacity / Max_Capacity`), breaking ties by
       lowest raw load and `Rep_ID`.
    5. Overflow Capture: If all eligible reps are full or no skill match exists,
       route the lead to `Manager Review` with a diagnostic reason.
"""

from collections import defaultdict
import time

from cleaner import clean_all_datasets
from scorer import score_and_sort_leads


def build_rep_index(reps):
    """
    Pre-index sanitized representatives by (Region, Language, Industry) and Seniority.

    How it works:
        Iterates once over all representatives in O(M) time and organizes them into
        a nested dictionary keyed by `(Region, Language, Industry_Vertical_Expertise)`
        with sub-lists for `Senior`, `Manager`, and `Junior`. This eliminates nested
        loops during routing, allowing 50,000+ leads to find eligible reps in O(1)
        average lookup time.

    Args:
        reps (list[dict]): Sanitized representative dictionaries from `cleaner.py`.

    Returns:
        dict: Nested hash map `{(region, language, industry): {seniority: [rep, ...]}}`.
    """
    index = defaultdict(lambda: {"Senior": [], "Manager": [], "Junior": []})
    for rep in reps:
        if rep.get("Max_Capacity", 0) <= 0:
            continue
        skill_key = (
            rep["Region"],
            rep["Language"],
            rep["Industry_Vertical_Expertise"],
        )
        seniority = rep["Seniority_Level"]
        if seniority in index[skill_key]:
            index[skill_key][seniority].append(rep)
    return index


def select_best_rep(candidates):
    """
    Choose the optimal available representative using Least-Utilization Balancing.

    How it works:
        Filters candidates to those strictly below `Max_Capacity`, then selects the
        rep with the smallest utilization ratio (`Current_Capacity / Max_Capacity`).
        Because capacity limits vary by seniority (Juniors: 40-50, Seniors: 20-25,
        Managers: 5-10), balancing by utilization percentage keeps workloads fair
        relative to each rep's bandwidth, while `(Current_Capacity, Rep_ID)` breaks
        exact ties deterministically.

    Args:
        candidates (list[dict]): Eligible reps matching skills and seniority rules.

    Returns:
        dict | None: The selected rep dictionary, or None if all candidates are full.
    """
    available = [r for r in candidates if r["Current_Capacity"] < r["Max_Capacity"]]
    if not available:
        return None

    return min(
        available,
        key=lambda r: (
            r["Current_Capacity"] / r["Max_Capacity"],
            r["Current_Capacity"],
            r["Rep_ID"],
        ),
    )


def route_leads(scored_leads, cleaned_reps):
    """
    Route all scored leads to eligible reps or the Manager Review overflow queue.

    How it works:
        Clones the incoming rep records so pipeline runs and dashboard resets
        never mutate the original cleaned dataset. For each lead in priority order,
        it verifies complete routing attributes, performs an O(1) skill-bucket
        lookup, enforces the CRITICAL seniority hierarchy (Senior -> Manager, never
        Junior), updates the chosen rep's live `Current_Capacity`, and logs any
        unassignable leads into `manager_review` with an audit reason.

    Args:
        scored_leads (list[dict]): Priority-sorted leads from `scorer.py`.
        cleaned_reps (list[dict]): Sanitized representative records from `cleaner.py`.

    Returns:
        dict: Summary payload containing:
            - `routed_leads` (list[dict]): Every lead enriched with assignment details.
            - `manager_review` (list[dict]): Subset of leads routed to overflow review.
            - `reps` (list[dict]): Updated rep records with final capacities.
    """
    reps = [dict(r) for r in cleaned_reps]
    rep_index = build_rep_index(reps)

    routed_leads = []
    manager_review = []

    for lead in scored_leads:
        record = dict(lead)
        region = record["Region"]
        language = record["Language"]
        industry = record["Industry_Vertical"]
        tier = record["Priority_Tier"]

        # Missing critical routing dimensions cannot match a strict multi-skill rep
        if "Unknown" in (region, language, industry):
            record["Assigned_Rep_ID"] = "UNASSIGNED"
            record["Assigned_Rep_Name"] = "Manager Review"
            record["Assigned_Rep_Seniority"] = "N/A"
            record["Routing_Status"] = "Manager Review"
            record["Routing_Reason"] = "Missing Region, Language, or Industry"
            routed_leads.append(record)
            manager_review.append(record)
            continue

        skill_bucket = rep_index.get((region, language, industry))
        chosen_rep = None

        if skill_bucket:
            if tier == "CRITICAL":
                # Seniority Constraint: Try Senior first, fallback to Manager; NEVER Junior
                chosen_rep = select_best_rep(skill_bucket["Senior"])
                if chosen_rep is None:
                    chosen_rep = select_best_rep(skill_bucket["Manager"])
            else:
                # Non-Critical leads can be assigned to any matching rep with capacity
                all_eligible = (
                    skill_bucket["Junior"]
                    + skill_bucket["Senior"]
                    + skill_bucket["Manager"]
                )
                chosen_rep = select_best_rep(all_eligible)

        if chosen_rep is not None:
            chosen_rep["Current_Capacity"] += 1
            record["Assigned_Rep_ID"] = chosen_rep["Rep_ID"]
            record["Assigned_Rep_Name"] = chosen_rep["Name"]
            record["Assigned_Rep_Seniority"] = chosen_rep["Seniority_Level"]
            record["Routing_Status"] = "Assigned"
            record["Routing_Reason"] = f"Matched ({region}, {language}, {industry})"
            routed_leads.append(record)
        else:
            record["Assigned_Rep_ID"] = "UNASSIGNED"
            record["Assigned_Rep_Name"] = "Manager Review"
            record["Assigned_Rep_Seniority"] = "N/A"
            record["Routing_Status"] = "Manager Review"
            if not skill_bucket:
                record["Routing_Reason"] = f"No rep for ({region}, {language}, {industry})"
            elif tier == "CRITICAL":
                record["Routing_Reason"] = "All eligible Seniors & Managers at max capacity"
            else:
                record["Routing_Reason"] = "All eligible reps at max capacity"
            routed_leads.append(record)
            manager_review.append(record)

    return {
        "routed_leads": routed_leads,
        "manager_review": manager_review,
        "reps": reps,
    }


if __name__ == "__main__":
    print("Running full end-to-end routing verification...\n")
    datasets = clean_all_datasets()

    for label, leads_key, reps_key in [
        ("SAMPLE (100 Leads)", "leads_sample", "reps_sample"),
        ("SCALE (50,000 Leads)", "leads_scale", "reps_scale"),
    ]:
        leads = datasets.get(leads_key, [])
        reps = datasets.get(reps_key, [])
        if not leads or not reps:
            continue

        start_time = time.perf_counter()
        scored = score_and_sort_leads(leads)
        result = route_leads(scored, reps)
        elapsed_ms = (time.perf_counter() - start_time) * 1000

        assigned_count = len(result["routed_leads"]) - len(result["manager_review"])
        print(f"=== {label} ===")
        print(f"  Execution Time : {elapsed_ms:.2f} ms")
        print(f"  Assigned Leads : {assigned_count} / {len(leads)}")
        print(f"  Manager Review : {len(result['manager_review'])} leads")

        # Verify zero Critical leads were ever assigned to a Junior rep
        junior_criticals = [
            l for l in result["routed_leads"]
            if l["Priority_Tier"] == "CRITICAL" and l["Assigned_Rep_Seniority"] == "Junior"
        ]
        print(f"  Junior Critical Violations: {len(junior_criticals)}")
        print()

    # Print sample rep capacity utilization
    sample_scored = score_and_sort_leads(datasets.get("leads_sample", []))
    sample_result = route_leads(sample_scored, datasets.get("reps_sample", []))
    print("=== Sample Representative Utilization ===")
    for rep in sample_result["reps"]:
        print(
            f"  {rep['Rep_ID']} | {rep['Name']:<18} | {rep['Seniority_Level']:<7} | "
            f"{rep['Region']:<13} | {rep['Language']:<7} | {rep['Industry_Vertical_Expertise']:<13} | "
            f"Load: {rep['Current_Capacity']}/{rep['Max_Capacity']}"
        )