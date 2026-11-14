"""
Stage 4: Human Impact (Exposure of Population and Cropland to Monsoon Flooding)
using 100% REAL downloaded datasets:
  1. WorldPop 100m UN-Adjusted Constrained Population (`datasets/worldpop/{aoi_id}_worldpop_80m.tif`)
  2. ESA WorldCover 10m v200 Cropland Class 40 (`datasets/worldcover/{aoi_id}_worldcover_80m.tif`)
  3. geoBoundaries Bangladesh ADM2 Districts & ADM3 Upazilas (`datasets/admin_boundaries/{aoi_id}_upazilas_80m.tif`)
  4. NISAR L2 GCOV New-Flood Masks (`data_raw/{aoi_id}_water_products.nc`)
"""

import json
from collections import defaultdict
from pathlib import Path
import numpy as np
import rasterio
import xarray as xr

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_RAW_DIR = REPO_ROOT / "data_raw"
DATASETS_DIR = REPO_ROOT / "datasets"
WEB_DATA_DIR = REPO_ROOT / "web" / "data"


def process_human_impact(aoi_id: str):
    water_nc = DATA_RAW_DIR / f"{aoi_id}_water_products.nc"
    wp_tif = DATASETS_DIR / "worldpop" / f"{aoi_id}_worldpop_80m.tif"
    wc_tif = DATASETS_DIR / "worldcover" / f"{aoi_id}_worldcover_80m.tif"
    upz_tif = DATASETS_DIR / "admin_boundaries" / f"{aoi_id}_upazilas_80m.tif"
    upz_json = DATASETS_DIR / "admin_boundaries" / f"{aoi_id}_upazilas_lookup.json"

    if not water_nc.exists():
        raise FileNotFoundError(f"Missing {water_nc}; run 03_water.py first.")

    ds_w = xr.open_dataset(water_nc, engine="h5netcdf")
    dates = [str(t) for t in ds_w["time"].values]
    dyn_classes = ds_w["flood_dynamics"].values  # 1=perm, 2=new_flood, 3=receded, 4=flooded_veg
    nt, ny, nx = dyn_classes.shape
    res_m = float(ds_w.attrs.get("resolution_m", 80.0))
    pixel_area_ha = (res_m * res_m) / 10000.0  # 0.64 ha per 80m pixel

    with rasterio.open(wp_tif) as src:
        pop_grid = src.read(1).astype(np.float32)
        pop_grid = np.where(np.isfinite(pop_grid) & (pop_grid > 0), pop_grid, 0.0)

    with rasterio.open(wc_tif) as src:
        worldcover = src.read(1)
        cropland_mask = worldcover == 40

    with rasterio.open(upz_tif) as src:
        upz_grid = src.read(1)

    with open(upz_json, "r", encoding="utf-8") as f:
        upz_lookup = json.load(f)

    print(
        f"[{aoi_id.upper()}] Computing Human & Cropland Impact from REAL WorldPop ({int(round(float(np.sum(pop_grid)))):,} people) & WorldCover ({np.sum(cropland_mask)*pixel_area_ha:,.1f} ha cropland)...",
        flush=True,
    )

    impact_series = []
    peak_idx = 0
    max_exposed_score = -1.0

    for t in range(nt):
        new_open_flood = dyn_classes[t] == 2
        flooded_veg = dyn_classes[t] == 4
        new_flood_total = new_open_flood | flooded_veg

        people_exposed = float(np.sum(pop_grid[new_flood_total]))
        people_open_water = float(np.sum(pop_grid[new_open_flood]))

        crop_flooded_ha = round(float(np.sum(new_flood_total & cropland_mask) * pixel_area_ha), 1)
        crop_open_water_ha = round(float(np.sum(new_open_flood & cropland_mask) * pixel_area_ha), 1)

        # Report ranges (+/- 15%) rather than false precision because WorldPop is a spatial disaggregation model
        pop_est = int(round(people_exposed))
        pop_low = int(round(people_exposed * 0.85))
        pop_high = int(round(people_exposed * 1.15))

        crop_low = round(crop_flooded_ha * 0.90, 1)
        crop_high = round(crop_flooded_ha * 1.10, 1)

        score = people_exposed + crop_flooded_ha * 5.0
        if score > max_exposed_score:
            max_exposed_score = score
            peak_idx = t

        impact_series.append({
            "date": dates[t],
            "people_exposed_estimate": pop_est,
            "people_exposed_open_water": int(round(people_open_water)),
            "people_exposed_range": [pop_low, pop_high],
            "cropland_flooded_ha": crop_flooded_ha,
            "cropland_open_water_ha": crop_open_water_ha,
            "cropland_flooded_range_ha": [crop_low, crop_high],
            "uncertainty_note": "WorldPop 100m UN-adjusted constrained estimate (±15% range); ESA WorldCover 10m cropland (±10% range).",
        })

    # Aggregate peak flood exposure by real Upazila (ADM3) and District (ADM2) from geoBoundaries polygons
    peak_new_flood = (dyn_classes[peak_idx] == 2) | (dyn_classes[peak_idx] == 4)
    upazila_rows = []
    district_agg = defaultdict(lambda: {"upazilas": [], "people": 0.0, "cropland_ha": 0.0, "total_pop": 0.0})

    for code_str, info in upz_lookup.items():
        code = int(code_str)
        u_mask = upz_grid == code
        if not np.any(u_mask):
            continue
        u_flood = u_mask & peak_new_flood
        u_pop_exposed = float(np.sum(pop_grid[u_flood]))
        u_pop_total = float(np.sum(pop_grid[u_mask]))
        u_crop_ha = float(np.sum(u_flood & cropland_mask) * pixel_area_ha)
        u_area_km2 = float(np.sum(u_mask) * (res_m * res_m) / 1e6)

        if u_area_km2 < 2.0:
            continue

        upz_name = info["upazila"]
        dist_name = info["district"]
        upazila_rows.append({
            "upazila": upz_name,
            "district": dist_name,
            "aoi_footprint_km2": round(u_area_km2, 1),
            "total_population_in_aoi": int(round(u_pop_total)),
            "people_affected_peak": int(round(u_pop_exposed)),
            "people_affected_range": [int(round(u_pop_exposed * 0.85)), int(round(u_pop_exposed * 1.15))],
            "cropland_affected_ha": round(u_crop_ha, 1),
        })

        d_entry = district_agg[dist_name]
        d_entry["upazilas"].append((upz_name, u_pop_exposed + u_crop_ha))
        d_entry["people"] += u_pop_exposed
        d_entry["cropland_ha"] += u_crop_ha
        d_entry["total_pop"] += u_pop_total

    upazila_rows.sort(key=lambda x: (x["people_affected_peak"] + x["cropland_affected_ha"]), reverse=True)
    for rank, r in enumerate(upazila_rows, start=1):
        r["severity_rank"] = rank

    ranked_districts = []
    for dist_name, d_val in district_agg.items():
        d_val["upazilas"].sort(key=lambda x: x[1], reverse=True)
        top_upz = [u[0] for u in d_val["upazilas"][:4]]
        ranked_districts.append({
            "district": dist_name,
            "key_upazilas": ", ".join(top_upz),
            "total_population_in_aoi": int(round(d_val["total_pop"])),
            "people_affected_peak": int(round(d_val["people"])),
            "people_affected_range": [int(round(d_val["people"] * 0.85)), int(round(d_val["people"] * 1.15))],
            "cropland_affected_ha": round(d_val["cropland_ha"], 1),
        })

    ranked_districts.sort(key=lambda x: (x["people_affected_peak"] + x["cropland_affected_ha"]), reverse=True)
    for rank, rd in enumerate(ranked_districts, start=1):
        rd["severity_rank"] = rank

    summary = {
        "aoi_id": aoi_id,
        "aoi_name": ds_w.attrs.get("aoi_name"),
        "peak_flood_date": dates[peak_idx],
        "total_population_in_aoi": int(round(float(np.sum(pop_grid)))),
        "total_cropland_in_aoi_ha": round(float(np.sum(cropland_mask) * pixel_area_ha), 1),
        "time_series": impact_series,
        "ranked_district_impact": ranked_districts,
        "ranked_upazila_impact": upazila_rows[:12],
        "methodology": (
            "Intersected real NISAR L2 GCOV new-flood masks (open water minus JRC permanent water, plus double-bounce flooded vegetation) "
            "with real WorldPop 100m UN-adjusted constrained population counts (bgd_ppp_2020_UNadj_constrained.tif), "
            "real ESA WorldCover 10m v200 Cropland (Class 40), and real geoBoundaries ADM2/ADM3 polygons."
        ),
    }

    WEB_DATA_DIR.mkdir(parents=True, exist_ok=True)
    out_json = WEB_DATA_DIR / f"{aoi_id}_impact_summary.json"
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    print(
        f"  -> Saved {out_json} | Peak ({dates[peak_idx]}): {impact_series[peak_idx]['people_exposed_estimate']:,} people, {impact_series[peak_idx]['cropland_flooded_ha']:,.1f} ha cropland across {len(ranked_districts)} districts",
        flush=True,
    )


def main():
    for aoi in ["jamuna", "haor"]:
        process_human_impact(aoi)


if __name__ == "__main__":
    main()
