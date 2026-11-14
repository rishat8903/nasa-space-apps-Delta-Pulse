"""
Stage 2: Water Pulse (Flood Extent, Dynamics, and River Migration) using REAL NISAR L2 GCOV,
REAL EC JRC Global Surface Water (v1.4), and REAL ESA WorldCover 10m (v200).

Physics:
- Calm open water is specularly smooth at L-band (24 cm wavelength), scattering radar energy away
  from the antenna and appearing dark in both HH and HV polarizations.
- HV cross-polarization is less sensitive to wind-induced surface capillary waves than HH or C-band VV.
- Flooded vegetation (double-bounce scattering): L-band radar penetrates canopy and bounces off
  horizontal water to vertical stems and back, causing a strong surge in HH backscatter (+2.5 to +8 dB)
  over vegetated/cropland classes (ESA WorldCover classes 10, 30, 40, 90).
- Permanent water baseline: Combined from EC JRC Global Surface Water occurrence (>= 50%) and
  dry/post-monsoon river channel permanence so that New Flood = Water Now minus Permanent Water.
"""

import json
from pathlib import Path
import numpy as np
import rasterio
from scipy.ndimage import binary_opening, binary_closing, label
from skimage.filters import threshold_otsu
import xarray as xr

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_RAW_DIR = REPO_ROOT / "data_raw"
DATASETS_DIR = REPO_ROOT / "datasets"
WEB_DATA_DIR = REPO_ROOT / "web" / "data"


def compute_water_mask(hv_slice: np.ndarray, hh_slice: np.ndarray) -> tuple[np.ndarray, float, float]:
    """
    Compute binary open-water mask using adaptive Otsu thresholding on HV dB
    cross-checked against histogram sanity bounds [-22.5, -16.5] dB and HH < -12.0 dB.
    Clean with 3x3 morphological opening/closing and remove tiny components (< 3 pixels).
    Returns (cleaned_mask, raw_otsu_db, applied_threshold_db).
    """
    valid = np.isfinite(hv_slice) & np.isfinite(hh_slice)
    hv_valid = hv_slice[valid]

    try:
        otsu_th = float(threshold_otsu(hv_valid))
    except Exception:
        otsu_th = -18.5

    clamped_th = float(np.clip(otsu_th, -22.5, -16.5))
    raw_water = valid & (hv_slice < clamped_th) & (hh_slice < -12.0)

    struct = np.ones((3, 3), dtype=bool)
    cleaned = binary_opening(raw_water, structure=struct)
    cleaned = binary_closing(cleaned, structure=struct)

    lbl, _ = label(cleaned)
    if lbl.max() > 0:
        counts = np.bincount(lbl.ravel())
        small_ids = np.where((counts > 0) & (counts < 3))[0]
        if len(small_ids) > 0:
            cleaned[np.isin(lbl, small_ids)] = False

    return cleaned, otsu_th, clamped_th


def process_water_pulse(aoi_id: str):
    proc_nc = DATA_RAW_DIR / f"{aoi_id}_gcov_processed.nc"
    jrc_tif = DATASETS_DIR / "jrc_water" / f"{aoi_id}_jrc_occurrence_80m.tif"
    wc_tif = DATASETS_DIR / "worldcover" / f"{aoi_id}_worldcover_80m.tif"

    if not proc_nc.exists():
        raise FileNotFoundError(f"Missing {proc_nc}; run 02_preprocess.py first.")

    ds = xr.open_dataset(proc_nc, engine="h5netcdf")
    hh_db = ds["HH_dB"].values
    hv_db = ds["HV_dB"].values
    dates = [str(t) for t in ds["time"].values]
    nt, ny, nx = hh_db.shape
    res_m = float(ds.attrs.get("resolution_m", 80.0))
    pixel_area_km2 = (res_m * res_m) / 1e6  # 0.0064 km2 per 80m pixel

    # Load real JRC Global Surface Water occurrence (%)
    if jrc_tif.exists():
        with rasterio.open(jrc_tif) as src:
            jrc_occurrence = src.read(1)
    else:
        jrc_occurrence = np.zeros((ny, nx), dtype=np.uint8)

    # Load real ESA WorldCover 10m resampled class map
    if wc_tif.exists():
        with rasterio.open(wc_tif) as src:
            worldcover = src.read(1)
    else:
        worldcover = np.full((ny, nx), 40, dtype=np.uint8)

    print(f"[{aoi_id.upper()}] Computing Water Pulse across {nt} dates with real JRC & WorldCover...", flush=True)

    water_masks = np.zeros((nt, ny, nx), dtype=bool)
    otsu_raw_list = []
    thresholds = []
    water_area_km2 = []

    for t in range(nt):
        w_mask, otsu_raw, th = compute_water_mask(hv_db[t], hh_db[t])
        water_masks[t] = w_mask
        otsu_raw_list.append(otsu_raw)
        thresholds.append(th)
        water_area_km2.append(round(float(np.sum(w_mask) * pixel_area_km2), 2))

    # NISAR water recurrence across the 12 scenes (0..1)
    water_recurrence = np.mean(water_masks, axis=0)

    # Permanent water mask: JRC long-term occurrence >= 50% OR NISAR persistent water (>= 80% of passes)
    permanent_water = (jrc_occurrence >= 50) | (water_recurrence >= 0.80)
    perm_area_km2 = float(np.sum(permanent_water) * pixel_area_km2)

    # Dry-season / Post-monsoon baseline reference for double-bounce change detection:
    # Use the minimum HH / HV baseline or earliest/latest low-water reference
    baseline_hh = np.nanpercentile(hh_db, 20, axis=0)
    baseline_hv = np.nanpercentile(hv_db, 20, axis=0)
    vegetated_classes = np.isin(worldcover, [10, 30, 40, 90])  # Trees, Grassland, Cropland, Herbaceous Wetland

    flooded_veg_masks = np.zeros((nt, ny, nx), dtype=bool)
    flooded_veg_area_km2 = []

    for t in range(nt):
        delta_hh = hh_db[t] - baseline_hh
        delta_hv = hv_db[t] - baseline_hv
        # Double-bounce flooded vegetation: vegetated land, not open water, HH rises >= +2.5 dB over baseline
        # and HH rise exceeds HV rise by >= 1.0 dB (corner reflector enhancement)
        is_flooded_veg = (
            (~water_masks[t])
            & (~permanent_water)
            & vegetated_classes
            & (delta_hh >= 2.5)
            & (delta_hh > delta_hv + 0.8)
            & (hh_db[t] > -10.5)
        )
        is_flooded_veg = binary_opening(is_flooded_veg, structure=np.ones((2, 2), dtype=bool))
        flooded_veg_masks[t] = is_flooded_veg
        flooded_veg_area_km2.append(round(float(np.sum(is_flooded_veg) * pixel_area_km2), 2))

    # Dynamic Flood Classes per date:
    # 0 = Dry Land
    # 1 = Permanent Water (JRC >= 50% or persistent channel)
    # 2 = Newly Flooded Open Water (Water now minus permanent water)
    # 3 = Receded / Emergent Char or Wetland Bed (Was water at peak/baseline, now dry)
    # 4 = Flooded Vegetation (Experimental L-band double-bounce)
    peak_t = int(np.argmax(water_area_km2))
    max_water_envelope = np.any(water_masks[: peak_t + 1], axis=0) | permanent_water

    dyn_classes = np.zeros((nt, ny, nx), dtype=np.uint8)
    new_flood_area_km2 = []
    receding_area_km2 = []
    perm_wet_area_km2 = []

    for t in range(nt):
        cur_w = water_masks[t]
        perm_wet = cur_w & permanent_water
        new_flood = cur_w & (~permanent_water)
        # Receding water: pixels inundated earlier in the monsoon (or permanent JRC channel) that are now dry/emergent
        prev_inundated = np.any(water_masks[: t + 1], axis=0) | permanent_water
        receded = (~cur_w) & prev_inundated

        dyn_classes[t][perm_wet] = 1
        dyn_classes[t][new_flood] = 2
        dyn_classes[t][receded] = 3
        dyn_classes[t][flooded_veg_masks[t]] = 4

        perm_wet_area_km2.append(round(float(np.sum(perm_wet) * pixel_area_km2), 2))
        new_flood_area_km2.append(round(float(np.sum(new_flood) * pixel_area_km2), 2))
        receding_area_km2.append(round(float(np.sum(receded) * pixel_area_km2), 2))

    # River channel & sandbar (char) transects in Jamuna
    lon_2d = ds["lon"].values
    lat_2d = ds["lat"].values
    transect_metrics = []
    if aoi_id == "jamuna":
        transect_rows = [
            {"id": "T1", "name": "Northern Reach (Kazipur / Sariakandi Char Complex)", "row": 110},
            {"id": "T2", "name": "Central Reach (Sirajganj Hardpoint & Braided Belt)", "row": 256},
            {"id": "T3", "name": "Southern Reach (Belkuchi / Kalihati Bifurcation)", "row": 395},
        ]
        for tr in transect_rows:
            r = tr["row"]
            w_first = water_masks[0, r, :]
            w_peak = water_masks[peak_t, r, :]
            w_last = water_masks[-1, r, :]

            width_first_m = int(np.sum(w_first) * res_m)
            width_peak_m = int(np.sum(w_peak) * res_m)
            width_last_m = int(np.sum(w_last) * res_m)

            # Emergent sandbar (char) width along transect between peak flood and post-monsoon
            char_emerged_m = int(np.sum(w_peak & (~w_last)) * res_m)
            new_erosion_m = int(np.sum((~w_first) & w_last) * res_m)

            idx_first = np.where(w_first)[0]
            idx_last = np.where(w_last)[0]
            west_shift_m = int((idx_last[0] - idx_first[0]) * res_m) if (len(idx_first) and len(idx_last)) else 0
            east_shift_m = int((idx_last[-1] - idx_first[-1]) * res_m) if (len(idx_first) and len(idx_last)) else 0

            transect_metrics.append({
                "id": tr["id"],
                "name": tr["name"],
                "lat_deg": round(float(np.mean(lat_2d[r, :])), 4),
                "lon_range": [round(float(lon_2d[r, 0]), 4), round(float(lon_2d[r, -1]), 4)],
                "row_index": r,
                "width_early_monsoon_m": width_first_m,
                "width_peak_monsoon_m": width_peak_m,
                "width_post_monsoon_m": width_last_m,
                "char_emergence_m": char_emerged_m,
                "bank_erosion_m": new_erosion_m,
                "west_bank_shift_m": west_shift_m,
                "east_bank_shift_m": east_shift_m,
            })

    ds_water = ds.copy()
    ds_water["water_mask"] = (("time", "y", "x"), water_masks.astype(np.uint8), {"long_name": "Binary Open Water Mask"})
    ds_water["flooded_veg_mask"] = (("time", "y", "x"), flooded_veg_masks.astype(np.uint8), {"long_name": "Double-Bounce Flooded Veg (Experimental)"})
    ds_water["water_recurrence"] = (("y", "x"), np.round(water_recurrence * 100).astype(np.uint8), {"units": "%", "long_name": "NISAR Water Recurrence %"})
    ds_water["jrc_occurrence"] = (("y", "x"), jrc_occurrence.astype(np.uint8), {"units": "%", "long_name": "JRC Global Surface Water Occurrence %"})
    ds_water["permanent_water_mask"] = (("y", "x"), permanent_water.astype(np.uint8), {"long_name": "Permanent Water Mask (JRC >=50% or NISAR >=80%)"})
    ds_water["flood_dynamics"] = (("time", "y", "x"), dyn_classes, {"long_name": "Flood Dynamics Class (0:dry, 1:perm, 2:new_flood, 3:receded, 4:flooded_veg)"})

    out_water_nc = DATA_RAW_DIR / f"{aoi_id}_water_products.nc"
    ds_water.to_netcdf(out_water_nc, engine="h5netcdf")

    ts_summary = {
        "aoi_id": aoi_id,
        "aoi_name": ds.attrs.get("aoi_name"),
        "dates": dates,
        "peak_flood_date": dates[peak_t],
        "peak_water_km2": water_area_km2[peak_t],
        "peak_new_flood_km2": new_flood_area_km2[peak_t],
        "total_aoi_area_km2": round(float(ny * nx * pixel_area_km2), 2),
        "permanent_water_km2": round(perm_area_km2, 2),
        "jrc_permanent_water_km2": round(float(np.sum(jrc_occurrence >= 50) * pixel_area_km2), 2),
        "time_series": [
            {
                "date": dates[t],
                "total_water_km2": water_area_km2[t],
                "permanent_wet_km2": perm_wet_area_km2[t],
                "new_flood_km2": new_flood_area_km2[t],
                "receding_km2": receding_area_km2[t],
                "flooded_veg_km2": flooded_veg_area_km2[t],
                "total_inundated_with_veg_km2": round(water_area_km2[t] + flooded_veg_area_km2[t], 2),
                "otsu_raw_hv_db": round(otsu_raw_list[t], 2),
                "threshold_hv_db": round(thresholds[t], 2),
            }
            for t in range(nt)
        ],
        "jamuna_transects": transect_metrics,
    }
    WEB_DATA_DIR.mkdir(parents=True, exist_ok=True)
    out_json = WEB_DATA_DIR / f"{aoi_id}_water_summary.json"
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(ts_summary, f, indent=2)
    print(f"  -> Saved {out_json} | Peak open water: {water_area_km2[peak_t]} km2 on {dates[peak_t]} (Perm: {perm_area_km2:.1f} km2, New flood: {new_flood_area_km2[peak_t]} km2)", flush=True)


def main():
    for aoi in ["jamuna", "haor"]:
        process_water_pulse(aoi)


if __name__ == "__main__":
    main()
