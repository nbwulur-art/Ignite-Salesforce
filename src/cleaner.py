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

    Why it works:
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
    Safely convert messy numeric strings into non-negative integers (or default).

    Why it works:
        Both leads (Company_Size) and reps (Current_Capacity, Max_Capacity) can
        contain comma-formatted numbers ("1,000"), shorthand suffixes ("5k"),
        negative values, or missing placeholders ("None", "N/A", ""). Returning
        `default` (such as None for missing Company_Size) lets scorer.py distinguish
        blank company sizes (+20 pts) from small companies (+0 pts), while
        clamping valid numbers at 0 prevents negative capacities.

    Args:
        raw_value (str): The raw text value from a numeric CSV column.
        default (int | None): Fallback value if missing or unparseable.
        allow_k_suffix (bool): Whether to parse shorthand like "5k" as 5000.

    Returns:
        int | None: A sanitized non-negative integer, or `default`.
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
        every lead dictionary exiting the ingestion layer follows the exact Data
        Dictionary schema before entering the scoring and routing engines.

    Args:
        row (dict): A raw row dictionary produced by csv.DictReader.

    Returns:
        dict: A sanitized lead dictionary with standardized strings, ints/None, and bools.
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

    Why it works:
        Matches the exact Data Dictionary schema ('Name',
        'Industry_Vertical_Expertise', 'Seniority_Level') while normalizing
        skill strings with the exact same alias dictionaries as leads so routing
        lookups never fail due to casing or typo mismatches.

    Args:
        row (dict): A raw row dictionary produced by csv.DictReader.

    Returns:
        dict: A sanitized representative dictionary ready for skill indexing.
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


def save_clean_csv(records, output_path):
    """
    Write a list of cleaned record dictionaries out to a new CSV file.

    Why it works:
        Uses csv.DictWriter to serialize standardized dictionaries back into a
        clean, Excel-compatible CSV file using the exact keys of the first record,
        enabling easy visual inspection and audit trails without overwriting raw data.

    Args:
        records (list[dict]): Cleaned records to write.
        output_path (str): Destination file path for the exported CSV.
    """
    if not records:
        return
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    fieldnames = list(records[0].keys())
    with open(output_path, mode="w", encoding="utf-8", newline="") as out_file:
        writer = csv.DictWriter(out_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(records)


def clean_all_datasets(data_dir=None, export_csv=False):
    """
    Locate, clean, and optionally export all four sample and scale CSV datasets.

    Why it works:
        Searches the current working directory, `<repo_root>/data/`, `<repo_root>/Data/`,
        and `<repo_root>/` automatically so CSV files are found regardless of folder
        casing or working directory.

    Args:
        data_dir (str, optional): Optional explicit directory to search first.
        export_csv (bool): Whether to write cleaned CSVs to `cleaned_data/`.

    Returns:
        dict: Dataset names mapped to lists of cleaned records.
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
        "leads_sample": ("leads_sample.csv", load_and_clean_leads),
        "reps_sample": ("reps_sample.csv", load_and_clean_reps),
        "leads_scale": ("leads_scale.csv", load_and_clean_leads),
        "reps_scale": ("reps_scale.csv", load_and_clean_reps),
    }

    output_dir = os.path.join(repo_root, "cleaned_data")
    datasets = {}

    for key, (filename, loader_fn) in file_map.items():
        found_path = None
        for folder in search_dirs:
            candidate = os.path.join(folder, filename)
            if os.path.exists(candidate):
                found_path = candidate
                break

        if found_path:
            cleaned = loader_fn(found_path)
            datasets[key] = cleaned
            if export_csv:
                out_file = os.path.join(output_dir, f"cleaned_{filename}")
                save_clean_csv(cleaned, out_file)
                print(f"[OK] Loaded {len(cleaned)} rows from '{found_path}' -> saved to '{out_file}'")
            else:
                print(f"[OK] Loaded {len(cleaned)} rows from '{found_path}'")
        else:
            print(f"[MISSING] Could not find '{filename}'")
            datasets[key] = []

    return datasets


if __name__ == "__main__":
    print("Running data cleaner...\n")
    all_data = clean_all_datasets(export_csv=True)

    for name, records in all_data.items():
        if records:
            print(f"\n=== {name} ({len(records)} records) ===")
            print("Sample row:", records[0])
            check_cols = [
                col
                for col in [
                    "Region",
                    "Language",
                    "Industry_Vertical",
                    "Industry_Vertical_Expertise",
                    "Seniority_Level",
                    "Recent_Activity",
                ]
                if col in records[0]
            ]
            for col in check_cols:
                uniques = sorted(set(str(r[col]) for r in records))
                print(f"  {col}: {uniques}")