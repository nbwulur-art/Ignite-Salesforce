"""
Data Sanitization & Normalization Engine (src/cleaner.py)

Purpose:
    Ingests raw customer lead and sales representative CSVs (`leads_scale.csv`
    and `reps_scale.csv`), standardizes casing, whitespace, and unstandardized
    aliases, parses messy numeric fields, and applies safe missing-data fallbacks.
"""

import csv
import os
import re

# Lookup dictionaries mapping lowercase/collapsed aliases to standardized values
REGION_ALIASES = {
    "north america": "North America",
    "nort america": "North America",
    "na": "North America",
    "europe": "Europe",
    "europ": "Europe",
    "eur": "Europe",
    "asia pacific": "Asia-Pacific",
    "asia-pacific": "Asia-Pacific",
    "asa-pacific": "Asia-Pacific",
    "asia. pacific": "Asia-Pacific",
    "apac": "Asia-Pacific",
}

LANGUAGE_ALIASES = {
    "en": "English",
    "english": "English",
    "es": "Spanish",
    "spanish": "Spanish",
    "de": "German",
    "german": "German",
}

INDUSTRY_ALIASES = {
    "manufacturing": "Manufacturing",
    "finance": "Finance",
    "healthcare": "Healthcare",
    "retail": "Retail",
    "technology": "Technology",
    "unknown": "Unknown",
    "": "Unknown",
    "n/a": "Unknown",
}

SENIORITY_ALIASES = {
    "junior": "Junior",
    "jr": "Junior",
    "senior": "Senior",
    "sr": "Senior",
    "manager": "Manager",
    "mgr": "Manager",
}

VIP_ALIASES = {
    "true": True,
    "false": False,
    "unknown": False,
    "": False,
    "n/a": False,
}


def normalize_key(raw_value):
    """
    Standardize a raw string into a clean lookup key.

    How it works:
        Strips leading/trailing whitespace, collapses consecutive internal spaces
        into one space, and converts to lowercase so all alias variations resolve
        to an identical dictionary key in O(1) time.
    """
    if raw_value is None:
        return ""
    cleaned = str(raw_value).strip().lower()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned


def clean_int(raw_value, default=0, allow_k_suffix=False):
    """
    Safely convert messy numeric strings into non-negative integers (or default).

    How it works:
        Handles comma-formatted strings ("1,000"), shorthand suffixes ("5k"),
        and missing placeholders ("None", "N/A", ""). Returning `default` (None
        for missing Company_Size) lets scorer.py distinguish blank forms (+20 pts)
        from small businesses (+0 pts), while clamping valid numbers at 0.
    """
    key = normalize_key(raw_value)
    if key in ("", "none", "unknown", "n/a", "null"):
        return default

    key = key.replace(",", "")

    try:
        if allow_k_suffix and key.endswith("k"):
            parsed = int(float(key[:-1]) * 1000)
        else:
            parsed = int(float(key))
        return max(0, parsed)
    except ValueError:
        return default


def clean_activity(raw_activity):
    """
    Standardize customer recent activity labels and unify missing indicators.

    How it works:
        Unifies blank cells and null markers ("N/A", "Unknown") into "None"
        to prevent false scoring awards, and title-cases valid actions for
        exact dictionary matching in scorer.py.
    """
    key = normalize_key(raw_activity)
    if key in ("", "n/a", "unknown", "none", "null"):
        return "None"
    return key.title()


def clean_lead_record(row):
    """
    Clean and normalize all fields of a single prospective lead record.

    How it works:
        Applies deterministic O(1) alias lookups and type conversions per row so
        every lead dictionary conforms strictly to the Data Dictionary schema.
    """
    region_key = normalize_key(row.get("Region"))
    language_key = normalize_key(row.get("Language"))
    industry_key = normalize_key(row.get("Industry_Vertical"))
    vip_key = normalize_key(row.get("VIP_Referral"))

    return {
        "Lead_ID": str(row.get("Lead_ID", "")).strip(),
        "Company_Name": str(row.get("Company_Name", "")).strip(),
        "Region": REGION_ALIASES.get(region_key, "Unknown"),
        "Language": LANGUAGE_ALIASES.get(language_key, "Unknown"),
        "Industry_Vertical": INDUSTRY_ALIASES.get(industry_key, "Unknown"),
        "Company_Size": clean_int(row.get("Company_Size"), default=None, allow_k_suffix=True),
        "Recent_Activity": clean_activity(row.get("Recent_Activity")),
        "VIP_Referral": VIP_ALIASES.get(vip_key, False),
    }


def clean_rep_record(row):
    """
    Clean and normalize all fields of a single sales representative record.

    How it works:
        Normalizes Region, Language, Industry_Vertical_Expertise, and
        Seniority_Level using the same alias maps as leads, and clamps
        Current_Capacity <= Max_Capacity to prevent invalid load states.
    """
    raw_industry = (
        row.get("Industry_Vertical_Expertise")
        or row.get("Industry_Expertise")
        or row.get("Industry_Vertical")
    )
    raw_seniority = row.get("Seniority_Level") or row.get("Seniority")
    raw_name = row.get("Name") or row.get("Rep_Name") or ""

    region_key = normalize_key(row.get("Region"))
    language_key = normalize_key(row.get("Language"))
    industry_key = normalize_key(raw_industry)
    seniority_key = normalize_key(raw_seniority)

    max_cap = clean_int(row.get("Max_Capacity"), default=0, allow_k_suffix=False)
    curr_cap = clean_int(row.get("Current_Capacity"), default=0, allow_k_suffix=False)

    return {
        "Rep_ID": str(row.get("Rep_ID", "")).strip(),
        "Name": str(raw_name).strip(),
        "Region": REGION_ALIASES.get(region_key, "Unknown"),
        "Language": LANGUAGE_ALIASES.get(language_key, "Unknown"),
        "Industry_Vertical_Expertise": INDUSTRY_ALIASES.get(industry_key, "Unknown"),
        "Seniority_Level": SENIORITY_ALIASES.get(seniority_key, "Junior"),
        "Current_Capacity": min(curr_cap, max_cap),
        "Max_Capacity": max_cap,
    }


def load_and_clean_leads(filepath):
    """Stream and sanitize all rows from a leads CSV file in O(N) time."""
    cleaned_leads = []
    with open(filepath, mode="r", encoding="utf-8-sig", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        for row in reader:
            cleaned_leads.append(clean_lead_record(row))
    return cleaned_leads


def load_and_clean_reps(filepath):
    """Stream and sanitize all rows from a representatives CSV file in O(M) time."""
    cleaned_reps = []
    with open(filepath, mode="r", encoding="utf-8-sig", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        for row in reader:
            cleaned_reps.append(clean_rep_record(row))
    return cleaned_reps


def load_scale_datasets(data_dir=None):
    """
    Locate and clean `leads_scale.csv` and `reps_scale.csv`.

    How it works:
        Searches the current working directory, `data/`, `Data/`, and the
        repository root automatically so the 50,000-lead and 1,600-rep scale
        files load cleanly regardless of where the script is launched.
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(script_dir)
    cwd = os.getcwd()

    search_dirs = []
    for d in [
        data_dir,
        cwd,
        os.path.join(cwd, "data"),
        os.path.join(cwd, "Data"),
        os.path.join(repo_root, "data"),
        os.path.join(repo_root, "Data"),
        repo_root,
        script_dir,
    ]:
        if d and d not in search_dirs:
            search_dirs.append(d)

    file_map = {
        "leads_scale": ("leads_scale.csv", load_and_clean_leads),
        "reps_scale": ("reps_scale.csv", load_and_clean_reps),
    }

    datasets = {}
    for key, (filename, loader_fn) in file_map.items():
        found_path = None
        for folder in search_dirs:
            candidate = os.path.join(folder, filename)
            if os.path.exists(candidate):
                found_path = candidate
                break

        if found_path:
            datasets[key] = loader_fn(found_path)
        else:
            print(f"[MISSING] Could not find '{filename}'")
            datasets[key] = []

    return datasets


if __name__ == "__main__":
    data = load_scale_datasets()
    print(f"Cleaned leads_scale: {len(data['leads_scale'])} records")
    print(f"Cleaned reps_scale : {len(data['reps_scale'])} records")