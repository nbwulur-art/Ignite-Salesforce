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
    "unknown": False,  # Conservative fallback: unverified VIP status defaults to False
    "": False,
    "n/a": False,
}


def normalize_key(raw_value):
    """
    Standardize a raw string into a clean lookup key.

    How this works:
        Raw CSV cells frequently include outer spaces, mixed capitalization, or
        repeated internal whitespace (e.g., "ASIA  PACIFIC"). Stripping outer
        spaces, collapsing internal runs of whitespace into a single space, and
        lowercasing guarantees all variations of a label map to one consistent
        dictionary key in O(1) lookup time.

    Args:
        raw_value (str): The raw cell value extracted from a CSV file.

    Returns:
        str: A trimmed, single-spaced, lowercase string (or "" if None).
    """
    if raw_value is None:
        return ""
    cleaned = str(raw_value).strip().lower()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned


def clean_int(raw_value, default=0, allow_k_suffix=False):
    """
    Safely convert messy numeric strings into non-negative integers.

    Why it works:
        Both leads (Company_Size) and reps (Current_Capacity, Max_Capacity) can
        contain comma-formatted numbers ("1,000"), shorthand suffixes ("5k"),
        negative values, or missing placeholders ("None", "N/A", ""). Stripping
        commas, optionally expanding "k" multipliers, catching ValueError, and
        clamping below zero ensures downstream math never crashes.

    Args:
        raw_value (str): The raw text value from a numeric CSV column.
        default (int): Fallback integer if the value is missing or unparseable.
        allow_k_suffix (bool): Whether to parse shorthand like "5k" as 5000.

    Returns:
        int: A sanitized non-negative integer.
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

    Why it works:
        Activity strings contain leading whitespace (" Contact Sales"), mixed
        casing, blank cells, and null markers ("N/A", "Unknown"). Converting all
        missing indicators to "None" prevents false point awards during scoring,
        while title-casing valid actions ensures exact matches in the scoring table.

    Args:
        raw_activity (str): The raw value from the Recent_Activity column.

    Returns:
        str: Standardized activity string, or "None" when no activity is recorded.
    """
    key = normalize_key(raw_activity)
    if key in ("", "n/a", "unknown", "none", "null"):
        return "None"
    return key.title()


def clean_lead_record(row):
    """
    Clean and normalize all fields of a single prospective lead record.

    Why it works:
        Applying deterministic alias lookups and type conversions per row ensures
        every lead dictionary exiting the ingestion layer follows an identical
        schema before entering the scoring and routing engines.

    Args:
        row (dict): A raw row dictionary produced by csv.DictReader.

    Returns:
        dict: A sanitized lead dictionary with standardized strings, ints, and bools.
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
        "Company_Size": clean_int(row.get("Company_Size"), default=0, allow_k_suffix=True),
        "Recent_Activity": clean_activity(row.get("Recent_Activity")),
        "VIP_Referral": VIP_ALIASES.get(vip_key, False),
    }


def clean_rep_record(row):
    """
    Clean and normalize all fields of a single sales representative record.

    Why it works:
        Representatives must match leads on exact Region, Language, and Industry
        strings, while adhering to seniority gates and maximum capacity limits.
        Normalizing skill fields with the exact same alias maps as leads prevents
        mismatch bugs, and clamping Current_Capacity <= Max_Capacity prevents
        invalid capacity states.

    Args:
        row (dict): A raw row dictionary produced by csv.DictReader.

    Returns:
        dict: A sanitized representative dictionary ready for skill indexing.
    """
    # Support slight column header variations just in case (e.g. Industry_Expertise vs Industry_Vertical)
    raw_industry = row.get("Industry_Expertise") or row.get("Industry_Vertical")
    raw_name = row.get("Rep_Name") or row.get("Name") or ""

    region_key = normalize_key(row.get("Region"))
    language_key = normalize_key(row.get("Language"))
    industry_key = normalize_key(raw_industry)
    seniority_key = normalize_key(row.get("Seniority"))

    max_cap = clean_int(row.get("Max_Capacity"), default=0, allow_k_suffix=False)
    curr_cap = clean_int(row.get("Current_Capacity"), default=0, allow_k_suffix=False)

    return {
        "Rep_ID": str(row.get("Rep_ID", "")).strip(),
        "Rep_Name": str(raw_name).strip(),
        "Region": REGION_ALIASES.get(region_key, "Unknown"),
        "Language": LANGUAGE_ALIASES.get(language_key, "Unknown"),
        "Industry_Expertise": INDUSTRY_ALIASES.get(industry_key, "Unknown"),
        "Seniority": SENIORITY_ALIASES.get(seniority_key, "Junior"),
        "Current_Capacity": min(curr_cap, max_cap),
        "Max_Capacity": max_cap,
    }


def load_and_clean_leads(filepath):
    """
    Load a leads CSV file from disk and return a list of sanitized lead records.

    Why it works:
        Streams rows sequentially in O(n) time with utf-8-sig decoding to strip
        hidden Excel BOM characters without modifying the source file on disk.

    Args:
        filepath (str): Path to leads_sample.csv or leads_scale.csv.

    Returns:
        list[dict]: Cleaned lead dictionaries.
    """
    cleaned_leads = []
    with open(filepath, mode="r", encoding="utf-8-sig", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        for row in reader:
            cleaned_leads.append(clean_lead_record(row))
    return cleaned_leads


def load_and_clean_reps(filepath):
    """
    Load a representatives CSV file from disk and return a list of sanitized rep records.

    Why it works:
        Processes all representative records in a single O(m) pass so the routing
        engine can immediately index them by skill tuple and seniority.

    Args:
        filepath (str): Path to reps_sample.csv or reps_scale.csv.

    Returns:
        list[dict]: Cleaned representative dictionaries.
    """
    cleaned_reps = []
    with open(filepath, mode="r", encoding="utf-8-sig", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        for row in reader:
            cleaned_reps.append(clean_rep_record(row))
    return cleaned_reps


def clean_all_datasets(data_dir="data"):
    """
    Load and clean all four sample and scale CSV datasets in the data directory.

    Why it works:
        Provides a single entry point to batch-clean leads_sample, reps_sample,
        leads_scale, and reps_scale while skipping any file that is not present yet.

    Args:
        data_dir (str): Directory containing the CSV files (defaults to "data").

    Returns:
        dict: Keys 'leads_sample', 'reps_sample', 'leads_scale', 'reps_scale'
              mapped to their respective lists of cleaned records.
    """
    file_map = {
        "leads_sample": ("leads_sample.csv", load_and_clean_leads),
        "reps_sample": ("reps_sample.csv", load_and_clean_reps),
        "leads_scale": ("leads_scale.csv", load_and_clean_leads),
        "reps_scale": ("reps_scale.csv", load_and_clean_reps),
    }

    datasets = {}
    for key, (filename, loader_fn) in file_map.items():
        full_path = os.path.join(data_dir, filename)
        if os.path.exists(full_path):
            datasets[key] = loader_fn(full_path)
        else:
            datasets[key] = []
    return datasets


# Run this to test the data in the terminal

if __name__ == "__main__":
    # Run from project root: python src/cleaner.py
    all_data = clean_all_datasets(data_dir="data")

    for name, records in all_data.items():
        print(f"=== {name}: {len(records)} cleaned records ===")
        if records:
            print("Sample row:", records[0])
            # Audit unique categorical values to verify no messy aliases slipped through
            check_cols = [
                col for col in ["Region", "Language", "Industry_Vertical", "Industry_Expertise", "Seniority", "Recent_Activity"]
                if col in records[0]
            ]
            for col in check_cols:
                uniques = sorted(set(str(r[col]) for r in records))
                print(f"  {col}: {uniques}")
        print()