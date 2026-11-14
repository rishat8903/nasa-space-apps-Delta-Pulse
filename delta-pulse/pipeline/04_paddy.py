"""
Stage 3: Paddy Rhythm (Crop Radar Phenology & Temporal Clustering) using REAL NISAR L2 GCOV
and REAL ESA WorldCover 10m (v200) Cropland Mask (Class 40).

Physics of L-Band SAR over Paddy Rice:
- Restricted strictly to ESA WorldCover Cropland (Class 40) pixels.
- Extracts per-pixel time series of HH (dB), HV (dB), and HV - HH difference (dB).
- Clusters normalized temporal trajectories using unsupervised k-means (k=4), ordering clusters
  by timing of minimum HV (flooded/transplanting phase) and peak HV (vegetative/heading phase).
- Interprets each cluster cautiously as a physical hypothesis (no field-survey ground truth used).
"""

import json
from pathlib import Path
import numpy as np
import rasterio
from sklearn.cluster import MiniBatchKMeans
import xarray as xr

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_RAW_DIR = REPO_ROOT / "data_raw"
DATASETS_DIR = REPO_ROOT / "datasets"
WEB_DATA_DIR = REPO_ROOT / "web" / "data"


def process_paddy_rhythm(aoi_id: str):
    proc_nc = DATA_RAW_DIR / f"{aoi_id}_gcov_processed.nc"
    wc_tif = DATASETS_DIR / "worldcover" / f"{aoi_id}_worldcover_80m.tif"
    if not proc_nc.exists():
        raise FileNotFoundError(f"Missing {proc_nc}; run 02_preprocess.py first.")

    ds = xr.open_dataset(proc_nc, engine="h5netcdf")
    hh_db = ds["HH_dB"].values
    hv_db = ds["HV_dB"].values
    hv_minus_hh = ds["HV_minus_HH_dB"].values
    dates = [str(t) for t in ds["time"].values]
    nt, ny, nx = hh_db.shape
    res_m = float(ds.attrs.get("resolution_m", 80.0))
    pixel_area_km2 = (res_m * res_m) / 1e6

    if not wc_tif.exists():
        raise FileNotFoundError(f"Missing real WorldCover raster {wc_tif}; run 01b_fetch_ancillary.py first.")

    with rasterio.open(wc_tif) as src:
        worldcover = src.read(1)

    # Strictly restrict to ESA WorldCover Class 40 (Cropland) with valid radar time series across all dates
    valid_ts = np.all(np.isfinite(hv_db) & np.isfinite(hh_db), axis=0)
    cropland_mask = (worldcover == 40) & valid_ts

    print(
        f"[{aoi_id.upper()}] Real ESA WorldCover Class 40 (Cropland) pixels: {int(np.sum(cropland_mask)):,} ({np.mean(cropland_mask)*100:.1f}% of AOI, {np.sum(cropland_mask)*pixel_area_km2:.1f} km2)",
        flush=True,
    )

    hv_crop = hv_db[:, cropland_mask].T       # [N, nt]
    diff_crop = hv_minus_hh[:, cropland_mask].T  # [N, nt]

    # Z-score normalize each pixel's temporal trajectory so clustering groups by temporal rhythm shape
    hv_norm = (hv_crop - np.mean(hv_crop, axis=1, keepdims=True)) / (np.std(hv_crop, axis=1, keepdims=True) + 1e-6)
    diff_norm = (diff_crop - np.mean(diff_crop, axis=1, keepdims=True)) / (np.std(diff_crop, axis=1, keepdims=True) + 1e-6)
    features = np.hstack([hv_norm, diff_norm])

    k = 4
    kmeans = MiniBatchKMeans(n_clusters=k, random_state=42, batch_size=4096, n_init=10)
    raw_labels = kmeans.fit_predict(features)

    # Sort clusters deterministically by mean HV dynamic range / timing of min HV so class IDs are meaningful
    cluster_stats = []
    for c in range(k):
        c_mask = raw_labels == c
        c_hv = np.nanmean(hv_db[:, cropland_mask][:, c_mask], axis=1)
        c_hh = np.nanmean(hh_db[:, cropland_mask][:, c_mask], axis=1)
        cluster_stats.append((c, int(np.argmin(c_hv)), float(np.max(c_hv) - np.min(c_hv)), c_hv, c_hh))

    # Order clusters by (min_hv_date_index, -dynamic_range)
    cluster_stats.sort(key=lambda x: (x[1], -x[2]))
    remap = {old_c: new_idx for new_idx, (old_c, _, _, _, _) in enumerate(cluster_stats)}
    ordered_labels = np.vectorize(remap.get)(raw_labels)

    rhythm_map = np.zeros((ny, nx), dtype=np.uint8)
    rhythm_map[cropland_mask] = (ordered_labels + 1).astype(np.uint8)

    class_meta = [
        {
            "name": "Early Transplanted Aman Paddy (June Inundation -> Sept Peak)",
            "color": "#10b981",
        },
        {
            "name": "Mid-Monsoon Flooded Cropland -> Late Aman Recovery",
            "color": "#0ea5e9",
        },
        {
            "name": "Deepwater / Haor Margin Submergent Cropland",
            "color": "#f59e0b",
        },
        {
            "name": "Elevated Levee / Char Multi-Crop & Jute-Aman Rotation",
            "color": "#a855f7",
        },
    ]

    cluster_profiles = []
    for c in range(k):
        c_mask = ordered_labels == c
        count = int(np.sum(c_mask))
        c_hh_mean = np.nanmean(hh_db[:, cropland_mask][:, c_mask], axis=1)
        c_hv_mean = np.nanmean(hv_db[:, cropland_mask][:, c_mask], axis=1)
        c_diff_mean = c_hv_mean - c_hh_mean

        min_idx = int(np.argmin(c_hv_mean))
        peak_idx = int(np.argmax(c_hv_mean))
        amp_hv = float(c_hv_mean[peak_idx] - c_hv_mean[min_idx])

        cluster_profiles.append({
            "class_id": c + 1,
            "name": class_meta[c]["name"],
            "color": class_meta[c]["color"],
            "pixel_count": count,
            "area_km2": round(count * pixel_area_km2, 2),
            "area_ha": round(count * pixel_area_km2 * 100.0, 1),
            "share_of_cropland_pct": round(count / max(1, int(np.sum(cropland_mask))) * 100.0, 1),
            "hh_db_series": [round(float(v), 2) for v in c_hh_mean],
            "hv_db_series": [round(float(v), 2) for v in c_hv_mean],
            "diff_db_series": [round(float(v), 2) for v in c_diff_mean],
            "flooded_transplant_date": dates[min_idx],
            "peak_vegetative_date": dates[peak_idx],
            "hv_dynamic_range_db": round(amp_hv, 2),
            "hypothesis": (
                f"Hypothesis (no field-survey ground truth): Cluster {c+1} ({count * pixel_area_km2:.1f} km² of ESA WorldCover cropland) "
                f"reaches its lowest HV backscatter ({c_hv_mean[min_idx]:.2f} dB) on {dates[min_idx]} during field inundation/transplanting, "
                f"and peaks at {c_hv_mean[peak_idx]:.2f} dB on {dates[peak_idx]} (ΔHV = +{amp_hv:.2f} dB from canopy volume scattering)."
            ),
        })

    ds_paddy = ds.copy()
    ds_paddy["worldcover_class"] = (("y", "x"), worldcover.astype(np.uint8), {"long_name": "ESA WorldCover 10m Class (40=Cropland)"})
    ds_paddy["paddy_rhythm_class"] = (("y", "x"), rhythm_map, {"long_name": "Unsupervised Paddy Rhythm Class (1-4 on WorldCover Cropland)"})
    out_paddy_nc = DATA_RAW_DIR / f"{aoi_id}_paddy_products.nc"
    ds_paddy.to_netcdf(out_paddy_nc, engine="h5netcdf")

    paddy_summary = {
        "aoi_id": aoi_id,
        "aoi_name": ds.attrs.get("aoi_name"),
        "dates": dates,
        "k_clusters": k,
        "total_cropland_km2": round(float(np.sum(cropland_mask) * pixel_area_km2), 2),
        "total_cropland_ha": round(float(np.sum(cropland_mask) * pixel_area_km2 * 100.0), 1),
        "cropland_fraction_pct": round(float(np.mean(cropland_mask) * 100.0), 1),
        "data_maturity_caveat": (
            "Calibrated PROVISIONAL NISAR data covers June 18 to Nov 9, 2026 (~5 months, Kharif-II / Aman monsoon season). "
            "Dry-season Boro rice (Nov–May) is outside this calibrated window; pre-calibration BETA scenes (Oct 2025–Jan 2026) "
            "exist on western tracks but are not mixed here due to calibration caveats. All cluster labels are unsupervised hypotheses without field surveys."
        ),
        "clusters": cluster_profiles,
    }
    WEB_DATA_DIR.mkdir(parents=True, exist_ok=True)
    out_json = WEB_DATA_DIR / f"{aoi_id}_paddy_summary.json"
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(paddy_summary, f, indent=2)
    print(f"  -> Saved {out_json}", flush=True)


def main():
    for aoi in ["jamuna", "haor"]:
        process_paddy_rhythm(aoi)


if __name__ == "__main__":
    main()
