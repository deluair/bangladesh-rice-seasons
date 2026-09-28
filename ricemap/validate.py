"""BBS Ground-Truth Validation Module for District-Level Rice Area.

Joins predicted district rice areas with BBS Yearbook of Agricultural Statistics 2023 data.
Uses the printed season Total tables.
Handles the explicit district name reconciliation between geoBoundaries and BBS,
and implements the exact seasonal crop calendar year mapping:
  - Calendar 2022:
      Aus -> BBS 2022-23
      Aman -> BBS 2022-23
      Boro -> BBS 2021-22 (Jan-May 2022 crop)
  - Calendar 2023:
      Boro -> BBS 2022-23 (Jan-May 2023 crop)
      Aus & Aman -> Not in 2022-23 BBS yearbook (2023-24 crop)
  - Note: 2021 is not in the run, so only Boro 2021-22 (2022 crop) and all 2022-23 seasons can be validated.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

# Explicit 1-to-1 name mapping between geoBoundaries ADM2 and BBS 64 districts
GEOBOUNDARIES_TO_BBS_DISTRICTS: dict[str, str] = {
    "Barisal": "Barishal",
    "Bogra": "Bogura",
    "Brahamanbaria": "Brahmanbaria",
    "Chittagong": "Chattogram",
    "Comilla": "Cumilla",
    "Cox's Bazar": "Cox’s Bazar",  # ascii apostrophe to right curly apostrophe \u2019
    "Jessore": "Jashore",
    "Jhalokati": "Jhallokati",
    "Khagrachhari": "Khagrachari",
    "Maulvibazar": "Moulvibazar",
    "Nawabganj": "Chapai Nawabganj",
    "Netrakona": "Netrokona",
    "Panchagarh": "Panchagar",
}


def build_district_name_map(
    geoboundaries_districts: list[str],
    bbs_districts: list[str],
    out_csv: str | Path | None = None,
) -> pd.DataFrame:
    """Build explicit district name mapping table between geoBoundaries and BBS."""
    rows = []
    bbs_set = set(bbs_districts)

    for g_name in sorted(geoboundaries_districts):
        if g_name in GEOBOUNDARIES_TO_BBS_DISTRICTS:
            b_name = GEOBOUNDARIES_TO_BBS_DISTRICTS[g_name]
            status = "RENAMED_MATCH"
        elif g_name in bbs_set:
            b_name = g_name
            status = "EXACT_MATCH"
        else:
            b_name = ""
            status = "UNMATCHED"

        rows.append({
            "geoboundaries_district": g_name,
            "bbs_district": b_name,
            "match_status": status,
        })

    df_map = pd.DataFrame(rows)
    if out_csv:
        out_p = Path(out_csv)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        df_map.to_csv(out_p, index=False)
        print(f"Saved district name map to {out_p}")

    return df_map


def load_bbs_season_totals(bbs_csv_path: str | Path) -> pd.DataFrame:
    """Load BBS district season totals from the printed Total tables.

    Each season has one printed total table (Aus TOTAL=LOCAL+HYV, Total Aman, Total Boro).
    The printed totals are used rather than summing the component tables, so a misprint
    in a component row (Barguna HYV Aman 2021-22 reads 19 acres) does not propagate.
    """
    df = pd.read_csv(bbs_csv_path)
    df = df[df["district"].str.strip().str.upper() != "BANGLADESH"]
    totals = df[df["table_title"].str.contains("total", case=False, na=False)]
    assert not totals.duplicated(["season", "year", "district"]).any(), "one total row per district expected"
    return totals[["season", "year", "district", "area_ha"]].reset_index(drop=True)


def validate_district_predictions(
    pred_district_csv: str | Path,
    bbs_csv_path: str | Path,
    calendar_year: int,
    out_csv: str | Path | None = None,
    name_map_csv: str | Path | None = None,
) -> pd.DataFrame:
    """Join predicted district areas with BBS ground truth data.

    Applies the BBS crop calendar mapping:
      - Aus and Aman '2022-23' = calendar 2022 crop
      - Boro '2022-23' = the Jan-May 2023 crop
      - '2021-22' likewise (Aus/Aman 2021, Boro 2022)
    Note that 2021 is not in the run, so only Boro 2021-22 (2022 crop) and all 2022-23 seasons can be validated.
    """
    df_pred = pd.read_csv(pred_district_csv)
    df_bbs = load_bbs_season_totals(bbs_csv_path)

    # Export name map
    bbs_districts = sorted(df_bbs["district"].unique())
    pred_districts = sorted(df_pred["unit_name"].unique())
    df_name_map = build_district_name_map(pred_districts, bbs_districts, out_csv=name_map_csv)

    name_dict = dict(zip(df_name_map["geoboundaries_district"], df_name_map["bbs_district"], strict=False))

    results = []

    # Filter to districts with predicted rice > 0
    active_pred = df_pred[df_pred["pixel_count_total"] > 0]

    for _, row in active_pred.iterrows():
        g_name = row["unit_name"]
        b_name = name_dict.get(g_name, g_name)

        # Check each season
        for season in ["Aus", "Aman", "Boro"]:
            col_name = f"{season.lower()}_area_ha"
            pred_ha = row.get(col_name, 0.0)

            # Determine BBS year
            if calendar_year == 2022:
                bbs_year = "2021-22" if season == "Boro" else "2022-23"
                validatable = True
                note = "Validatable against BBS 2023 yearbook"
            elif calendar_year == 2023:
                if season == "Boro":
                    bbs_year = "2022-23"
                    validatable = True
                    note = "Boro 2022-23 validatable (Jan-May 2023 harvest)"
                else:
                    bbs_year = "2023-24"
                    validatable = False
                    note = "Not in run/yearbook (Aus/Aman 2023-24 requires 2024 yearbook)"
            else:
                bbs_year = f"{calendar_year}-{str(calendar_year+1)[-2:]}"
                validatable = False
                note = f"Year {calendar_year} not in BBS 2023 yearbook (covers 2021-22 to 2022-23)"

            bbs_val = None
            if validatable:
                match = df_bbs[
                    (df_bbs["district"] == b_name)
                    & (df_bbs["season"] == season)
                    & (df_bbs["year"] == bbs_year)
                ]
                if not match.empty:
                    bbs_val = float(match["area_ha"].values[0])

            diff_ha = round(pred_ha - bbs_val, 2) if bbs_val is not None else None
            ratio = round(pred_ha / bbs_val, 4) if (bbs_val is not None and bbs_val > 0) else None

            results.append({
                "calendar_year": calendar_year,
                "season": season,
                "geoboundaries_district": g_name,
                "bbs_district": b_name,
                "bbs_year": bbs_year,
                "validatable": validatable,
                "predicted_area_ha": pred_ha,
                "bbs_area_ha": bbs_val,
                "diff_ha": diff_ha,
                "pred_to_bbs_ratio": ratio,
                "notes": note,
            })

    df_res = pd.DataFrame(results)
    if out_csv:
        out_p = Path(out_csv)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        df_res.to_csv(out_p, index=False)
        print(f"Saved validation comparison to {out_p}")

    return df_res
