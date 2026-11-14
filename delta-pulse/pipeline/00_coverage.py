"""
Stage 0: Coverage check for NISAR L2 GCOV over candidate study areas in Bangladesh.
Queries ASF DAAC via asf_search / ASF Search API, filters out QA_STATS side files,
groups scenes by relativeOrbit (track), frame, flightDirection, and dataMaturity
(PROVISIONAL from 2026-06-17 onward vs BETA from 2025-10-17 to 2026-01-20),
ranks candidate study areas, and writes evidence to docs/aoi_decision.md and
precomputed coverage catalog JSON for the web app.
"""

import json
import os
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = REPO_ROOT / "docs"
WEB_DATA_DIR = REPO_ROOT / "web" / "data"

CANDIDATE_AOIS = {
    "jamuna": {
        "id": "jamuna",
        "name": "Brahmaputra-Jamuna Floodplain & Char Lands (Sirajganj / Bogura / Jamalpur)",
        "priority": 1,
        "bbox": [89.55, 24.15, 89.90, 24.95],  # [min_lon, min_lat, max_lon, max_lat]
        "wkt": "POLYGON((89.55 24.15, 89.90 24.15, 89.90 24.95, 89.55 24.95, 89.55 24.15))",
        "description": "Braided river floodplain and dynamic sandbars (chars) with strong monsoon flood expansion and bank migration.",
    },
    "haor": {
        "id": "haor",
        "name": "Haor Basin (Sylhet & Sunamganj Tectonic Wetlands)",
        "priority": 2,
        "bbox": [90.95, 24.55, 91.55, 25.10],
        "wkt": "POLYGON((90.95 24.55, 91.55 24.55, 91.55 25.10, 90.95 25.10, 90.95 24.55))",
        "description": "Bowl-shaped tectonic depressions (haors) that transform into a vast inland sea during the monsoon and drain in the dry season for Boro rice cultivation.",
    },
    "chattogram_coastal": {
        "id": "chattogram_coastal",
        "name": "Chattogram Coastal Belt & Halda/Karnaphuli Estuary",
        "priority": 3,
        "bbox": [91.65, 22.15, 92.05, 22.65],
        "wkt": "POLYGON((91.65 22.15, 92.05 22.15, 92.05 22.65, 91.65 22.65, 91.65 22.15))",
        "description": "Coastal estuary, tidal flats, and hills near Chattogram with tidal, monsoon runoff, and cyclone surge exposure.",
    },
    "sundarbans": {
        "id": "sundarbans",
        "name": "Sundarbans Mangrove Edge & Khulna Polders",
        "priority": 4,
        "bbox": [89.15, 22.00, 89.65, 22.55],
        "wkt": "POLYGON((89.15 22.00, 89.65 22.00, 89.65 22.55, 89.15 22.55, 89.15 22.00))",
        "description": "Mangrove forest boundary and coastal agricultural polders subject to tidal inundation, waterlogging, and salinity intrusion.",
    },
}


def parse_nisar_granule_id(granule_id: str) -> dict:
    """
    Parse NISAR L2 GCOV granule naming convention:
    NISAR_L2_PR_GCOV_008_130_A_091_2005_DHDH_A_20260625T120411_20260625T120446_P05006_F_F_J_001
    Fields:
      mission: NISAR
      level: L2
      prod_type: PR (Provisional/Standard) or UR (Urgent)
      product: GCOV
      cycle: 3 digits
      rel_orbit (track): 3 digits
      direction: A or D
      frame: 3 digits
      mode: 4 digits (e.g. 2005, 2000, 4005)
      pol_code: 4 chars (e.g. DHDH = Dual HH/HV, DVDV = Dual VV/VH, QPQp = Quad, SHNA = Single HH, DVNA = Single VV)
      start_dt, end_dt
      crid: e.g. P05006 (P = Provisional, B or R04 = Beta)
    """
    info = {
        "cycle": None,
        "track": None,
        "direction": None,
        "frame": None,
        "mode": None,
        "pol_code": None,
        "polarizations": [],
        "crid": None,
        "maturity": "UNKNOWN",
    }
    m = re.match(
        r"NISAR_L2_([A-Z]{2})_GCOV_(\d{3})_(\d{3})_([AD])_(\d{3})_(\d{4})_([A-Z0-9]{4})_[A-Z]_(\d{8}T\d{6})_(\d{8}T\d{6})_([A-Z0-9]+)_",
        granule_id,
    )
    if m:
        prod_type, cycle, track, direction, frame, mode, pol_code, start_str, end_str, crid = m.groups()
        info["prod_type"] = prod_type
        info["cycle"] = int(cycle)
        info["track"] = int(track)
        info["direction"] = "ASCENDING" if direction == "A" else "DESCENDING"
        info["frame"] = int(frame)
        info["mode"] = mode
        info["pol_code"] = pol_code
        info["crid"] = crid

        pols = []
        if pol_code.startswith("DH"):
            pols.extend(["HH", "HV"])
        elif pol_code.startswith("DV"):
            if pol_code == "DVNA":
                pols.append("VV")
            else:
                pols.extend(["VV", "VH"])
        elif pol_code.startswith("SH"):
            pols.append("HH")
        elif pol_code.startswith("SV"):
            pols.append("VV")
        elif pol_code.startswith("QP"):
            pols.extend(["HH", "HV", "VH", "VV"])
        info["polarizations"] = pols

        start_date = start_str[:8]
        if start_date >= "20260617" or crid.startswith("P"):
            info["maturity"] = "PROVISIONAL"
        else:
            info["maturity"] = "BETA"
    return info


def query_asf_gcov(wkt: str) -> list:
    url = "https://api.daac.asf.alaska.edu/services/search/param"
    params = {
        "dataset": "NISAR",
        "processingLevel": "GCOV",
        "intersectsWith": wkt,
        "output": "json",
    }
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if isinstance(data, list) and len(data) > 0 and isinstance(data[0], list):
        records = data[0]
    elif isinstance(data, dict) and "results" in data:
        records = data["results"]
    else:
        records = data

    # Filter out QA_STATS or non-H5 records if any
    filtered = []
    seen_granules = set()
    for r in records:
        gid = r.get("granuleName") or r.get("fileID") or ""
        if "QA_STATS" in gid or "STATS" in (r.get("processingTypeDisplay") or ""):
            continue
        dl_url = r.get("downloadUrl") or ""
        if "QA_STATS" in dl_url:
            continue
        # Ensure we deduplicate by granuleName
        base_gid = gid.replace("-GCOV", "")
        if base_gid in seen_granules:
            continue
        seen_granules.add(base_gid)
        filtered.append(r)
    return filtered


def main():
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    WEB_DATA_DIR.mkdir(parents=True, exist_ok=True)

    summary = {}
    for aoi_id, aoi in CANDIDATE_AOIS.items():
        print(f"Querying ASF for {aoi['name']}...")
        records = query_asf_gcov(aoi["wkt"])
        print(f"  -> Found {len(records)} unique GCOV granules")

        tracks = defaultdict(list)
        for r in records:
            gid = r.get("granuleName") or r.get("fileID") or ""
            parsed = parse_nisar_granule_id(gid)
            start_time = r.get("startTime") or ""
            date_str = start_time[:10] if start_time else ""
            pol_field = r.get("polarization") or ",".join(parsed["polarizations"])
            browse_urls = r.get("browse") or []

            scene_item = {
                "granule": gid.replace("-GCOV", ""),
                "date": date_str,
                "startTime": start_time,
                "track": parsed["track"] or r.get("relativeOrbit"),
                "frame": parsed["frame"] or r.get("frameNumber"),
                "direction": parsed["direction"] or r.get("flightDirection"),
                "cycle": parsed["cycle"],
                "mode": parsed["mode"],
                "pol_code": parsed["pol_code"],
                "polarizations": parsed["polarizations"],
                "polarization_str": pol_field,
                "crid": parsed["crid"],
                "maturity": parsed["maturity"],
                "sizeMB": r.get("sizeMB"),
                "downloadUrl": r.get("downloadUrl"),
                "s3Urls": r.get("s3Urls", []),
                "browse": browse_urls[0] if browse_urls else None,
                "wkt": r.get("stringFootprint"),
            }
            key = f"T{scene_item['track']:03d}_F{scene_item['frame']:03d}_{scene_item['direction'][0]}"
            tracks[key].append(scene_item)

        # Sort dates in each track
        track_summaries = {}
        for k, scenes in sorted(tracks.items()):
            scenes.sort(key=lambda x: x["startTime"])
            prov_scenes = [s for s in scenes if s["maturity"] == "PROVISIONAL"]
            beta_scenes = [s for s in scenes if s["maturity"] == "BETA"]
            hh_hv_prov = [s for s in prov_scenes if "HH" in s["polarizations"] and "HV" in s["polarizations"]]
            track_summaries[k] = {
                "track_key": k,
                "track": scenes[0]["track"],
                "frame": scenes[0]["frame"],
                "direction": scenes[0]["direction"],
                "total_scenes": len(scenes),
                "provisional_count": len(prov_scenes),
                "beta_count": len(beta_scenes),
                "provisional_dual_pol_hh_hv": len(hh_hv_prov),
                "polarizations_observed": sorted(list({s["pol_code"] for s in scenes if s["pol_code"]})),
                "first_date": scenes[0]["date"],
                "last_date": scenes[-1]["date"],
                "provisional_dates": [s["date"] for s in prov_scenes],
                "beta_dates": [s["date"] for s in beta_scenes],
                "scenes": scenes,
            }

        summary[aoi_id] = {
            "aoi": aoi,
            "total_granules": len(records),
            "tracks": track_summaries,
        }

    out_json = WEB_DATA_DIR / "aoi_coverage_raw.json"
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    print(f"Saved detailed coverage JSON to {out_json}")

    # Print quick summary table to stdout
    for aoi_id, data in summary.items():
        print(f"\n=== {data['aoi']['name']} (Total: {data['total_granules']}) ===")
        for tk, ts in data["tracks"].items():
            print(
                f"  {tk}: total={ts['total_scenes']} | PROV={ts['provisional_count']} (HH+HV={ts['provisional_dual_pol_hh_hv']}) | BETA={ts['beta_count']} | pols={ts['polarizations_observed']} | range={ts['first_date']}..{ts['last_date']}"
            )


if __name__ == "__main__":
    main()
