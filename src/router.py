"""
Smart Lead Routing & Capacity-Weighted Fair Queuing Engine (src/router.py)

Purpose:
    Assigns priority-sorted leads from `scorer.py` to sanitized sales
    representatives from `cleaner.py` while enforcing strict multi-skill
    matching (Region, Language, Industry Vertical), seniority gates for
    CRITICAL leads, maximum capacity limits, Capacity-Weighted Fair
    Round-Robin (`fair_share`) scheduling, and overflow capture into a
    visible Manager Review queue.

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
    4. Capacity-Weighted Fair Round-Robin (`fair_share`):
       Among eligible reps with remaining capacity (`Current_Capacity < Max_Capacity`),
       pick the rep minimizing:
         - Virtual finish time: `(Current_Capacity + 1) / Max_Capacity`
         - Value fairness: `value_received / Max_Capacity` (spreads high-score leads)
         - Round-robin rotation: `last_served` (served longest ago goes first)
         - File position: `file_pos` (reproducible tie-breaker)
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
        with sub-lists for `Senior`, `Manager`, and `Junior`.
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


def select_best_rep(candidates, rep_stats=None):
    """
    Choose the optimal available rep using Capacity-Weighted Fair Round-Robin.

    How it works:
        Evaluates each eligible rep below `Max_Capacity` using Weighted Fair
        Queuing:
          1. Virtual finish time `(Current_Capacity + 1) / Max_Capacity`
          2. Value fairness `value_received / Max_Capacity`
          3. Round-robin `last_served` turn counter
          4. Original CSV `file_pos` order
        Optional `rep_stats` keeps existing unit tests backward-compatible if
        called as `select_best_rep(candidates)`.
    """
    available = [r for r in candidates if r["Current_Capacity"] < r["Max_Capacity"]]
    if not available:
        return None

    stats = rep_stats or {}

    return min(
        available,
        key=lambda r: (
            (r["Current_Capacity"] + 1) / r["Max_Capacity"],
            stats.get(r["Rep_ID"], {}).get("value_received", 0.0) / r["Max_Capacity"],
            stats.get(r["Rep_ID"], {}).get("last_served", -1),
            stats.get(r["Rep_ID"], {}).get("file_pos", 0),
        ),
    )


def jain_index(values):
    """Compute Jain's fairness index: 1.0 = perfectly even, 1/n = completely skewed."""
    vals = list(values)
    total = sum(vals)
    squares = sum(v * v for v in vals)
    if not vals or squares == 0:
        return 1.0
    return (total * total) / (len(vals) * squares)


def compute_distribution_fairness(reps, rep_stats=None):
    """
    Calculate weighted-average Jain's fairness index across interchangeable rep pools.
    """
    groups = defaultdict(list)
    for rep in reps:
        if rep["Max_Capacity"] > 0 and "Unknown" not in (
            rep["Region"],
            rep["Language"],
            rep["Industry_Vertical_Expertise"],
        ):
            pool_key = (
                rep["Region"],
                rep["Language"],
                rep["Industry_Vertical_Expertise"],
                rep["Seniority_Level"],
            )
            if rep_stats is not None:
                amount = rep_stats.get(rep["Rep_ID"], {}).get("value_received", 0.0)
            else:
                amount = rep["Current_Capacity"]
            groups[pool_key].append(amount / rep["Max_Capacity"])

    weighted_sum, total_weight = 0.0, 0
    for utilizations in groups.values():
        if len(utilizations) >= 2 and sum(utilizations) > 0:
            weighted_sum += jain_index(utilizations) * len(utilizations)
            total_weight += len(utilizations)
    return round(weighted_sum / total_weight, 4) if total_weight else 1.0


def route_leads(scored_leads, cleaned_reps):
    """
    Route all scored leads to eligible reps or the Manager Review overflow queue.

    How it works:
        Clones the incoming rep records so pipeline runs and dashboard resets
        never mutate the original cleaned dataset. Tracks per-rep `value_received`,
        `last_served` turn counter, and `file_pos` to power Capacity-Weighted
        Fair Round-Robin scheduling while strictly enforcing CRITICAL seniority
        rules and logging overflow to `manager_review`.
    """
    reps = [dict(r) for r in cleaned_reps]
    rep_stats = {
        rep["Rep_ID"]: {
            "value_received": 0.0,
            "last_served": -1,
            "file_pos": idx,
        }
        for idx, rep in enumerate(reps)
    }
    rep_index = build_rep_index(reps)

    routed_leads = []
    manager_review = []

    for turn, lead in enumerate(scored_leads):
        record = dict(lead)
        region = record["Region"]
        language = record["Language"]
        industry = record["Industry_Vertical"]
        tier = record["Priority_Tier"]

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
                chosen_rep = select_best_rep(skill_bucket["Senior"], rep_stats)
                if chosen_rep is None:
                    chosen_rep = select_best_rep(skill_bucket["Manager"], rep_stats)
            else:
                all_eligible = (
                    skill_bucket["Junior"]
                    + skill_bucket["Senior"]
                    + skill_bucket["Manager"]
                )
                chosen_rep = select_best_rep(all_eligible, rep_stats)

        if chosen_rep is not None:
            chosen_rep["Current_Capacity"] += 1
            stat = rep_stats[chosen_rep["Rep_ID"]]
            stat["value_received"] += record.get("Score", 0)
            stat["last_served"] = turn

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
        "workload_fairness": compute_distribution_fairness(reps),
        "value_fairness": compute_distribution_fairness(reps, rep_stats),
    }


if __name__ == "__main__":
    print("Running scale routing verification (50,000 leads / 1,600 reps)...\n")
    datasets = clean_all_datasets()
    leads = datasets["leads_scale"]
    reps = datasets["reps_scale"]

    if not leads or not reps:
        print("[ERROR] Missing leads_scale.csv or reps_scale.csv in Data/.")
    else:
        start_time = time.perf_counter()
        scored = score_and_sort_leads(leads)
        result = route_leads(scored, reps)
        elapsed_ms = (time.perf_counter() - start_time) * 1000

        assigned_count = len(result["routed_leads"]) - len(result["manager_review"])
        junior_criticals = [
            l for l in result["routed_leads"]
            if l["Priority_Tier"] == "CRITICAL" and l["Assigned_Rep_Seniority"] == "Junior"
        ]

        print("=== SCALE BENCHMARK RESULTS ===")
        print(f"  Execution Time            : {elapsed_ms:.2f} ms")
        print(f"  Total Leads Processed     : {len(leads)}")
        print(f"  Assigned Leads            : {assigned_count}")
        print(f"  Manager Review Overflow   : {len(result['manager_review'])}")
        print(f"  Junior Critical Violations: {len(junior_criticals)}")
        print(f"  Workload Jain Fairness    : {result['workload_fairness']}")
        print(f"  Lead Value Jain Fairness  : {result['value_fairness']}")