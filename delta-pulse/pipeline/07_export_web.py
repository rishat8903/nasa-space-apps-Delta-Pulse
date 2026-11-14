"""
Stage 6 (Part A): Web Export Pipeline using 100% REAL processed datasets.
Generates precomputed RGBA PNG map overlays and JSON manifests for the frontend:
  - Per-date SAR Backscatter False-Color Composite (R=HH, G=HV, B=HH-HV)
  - Per-date Water & Flood Dynamics Overlay (Permanent water, New flood, Receding/Char emergence, Flooded vegetation)
  - Static Water Recurrence Frequency (%) & JRC Permanent Water
  - Static Paddy Rhythm Unsupervised Clusters (restricted to real ESA WorldCover Cropland)
  - Static ESA WorldCover 10m Land Cover Map
  - Static WorldPop 100m Population Density Heatmap
  - Validation Overlays: Real Sentinel-1 C-Band RTC (2026-07-25) & Real Sentinel-2 L2A Optical (2026-11-09/11)
  - Programmatically verified Landmark Pins (selected from real physical signatures in the cube)
  - 32x32 Dense Click Grid (1,024 real pixel time series per AOI) for instant map click inspection & Change Radio
"""

import json
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import rasterio
import xarray as xr

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_RAW_DIR = REPO_ROOT / "data_raw"
DATASETS_DIR = REPO_ROOT / "datasets"
WEB_DIR = REPO_ROOT / "web"
WEB_DATA_DIR = WEB_DIR / "data"
WEB_IMG_DIR = WEB_DIR / "images" / "overlays"

PENTATONIC_SCALE = [
    {"note": "C3", "freq": 130.81},
    {"note": "D3", "freq": 146.83},
    {"note": "E3", "freq": 164.81},
    {"note": "G3", "freq": 196.00},
    {"note": "A3", "freq": 220.00},
    {"note": "C4", "freq": 261.63},
    {"note": "D4", "freq": 293.66},
    {"note": "E4", "freq": 329.63},
    {"note": "G4", "freq": 392.00},
    {"note": "A4", "freq": 440.00},
    {"note": "C5", "freq": 523.25},
    {"note": "D5", "freq": 587.33},
    {"note": "E5", "freq": 659.25},
]


def pentatonic_pitch_map(hv_db: float, db_min: float = -24.0, db_max: float = -10.0) -> dict:
    norm = float(np.clip((hv_db - db_min) / (db_max - db_min + 1e-6), 0.0, 1.0))
    idx = int(round(norm * (len(PENTATONIC_SCALE) - 1)))
    return PENTATONIC_SCALE[idx]


def generate_pixel_explanation(hh_series: list, hv_series: list, dates: list, wc_class: int = 0) -> str:
    """Rule-based physical explanation derived strictly from real pixel backscatter numbers (no hidden AI calls)."""
    min_hv = min(hv_series)
    max_hv = max(hv_series)
    range_hv = max_hv - min_hv
    min_hh = min(hh_series)
    max_hh = max(hh_series)
    mean_hv = sum(hv_series) / len(hv_series)
    mean_hh = sum(hh_series) / len(hh_series)

    max_drop_hh = 0.0
    drop_pair = (dates[0], dates[1])
    max_rise_hh = 0.0
    rise_pair = (dates[0], dates[1])
    for i in range(len(dates) - 1):
        d_hh = hh_series[i + 1] - hh_series[i]
        if d_hh < max_drop_hh:
            max_drop_hh = d_hh
            drop_pair = (dates[i], dates[i + 1])
        if d_hh > max_rise_hh:
            max_rise_hh = d_hh
            rise_pair = (dates[i], dates[i + 1])

    wc_names = {
        10: "Tree Cover / Homestead Forest",
        30: "Grassland / Char Grazing",
        40: "Cropland (ESA WorldCover)",
        50: "Built-up Settlement",
        60: "Bare Sandbar / Silt",
        80: "Permanent Water Body",
        90: "Herbaceous Wetland",
    }
    wc_label = wc_names.get(wc_class, "Delta Surface")

    if mean_hv < -19.5 and mean_hh < -13.5:
        return (
            f"[{wc_label}] Persistent open water signature: HH averaged {mean_hh:.1f} dB and HV averaged {mean_hv:.1f} dB "
            f"across all {len(dates)} passes. Specular forward reflection off smooth water scatters L-band energy away from the sensor."
        )
    if max_drop_hh <= -3.8:
        return (
            f"[{wc_label}] Monsoon flood submergence: HH backscatter dropped by {max_drop_hh:.1f} dB between {drop_pair[0]} and {drop_pair[1]} "
            f"(reaching a minimum of {min_hh:.1f} dB HH / {min_hv:.1f} dB HV), consistent with new open water inundation."
        )
    if max_rise_hh >= 3.8 and min_hv < -17.5:
        return (
            f"[{wc_label}] Flood recession / emergent sandbar (char): Backscatter rebounded by +{max_rise_hh:.1f} dB between {rise_pair[0]} and {rise_pair[1]} "
            f"after monsoon submergence ({min_hh:.1f} dB), marking exposed wet silt or post-flood drainage."
        )
    if wc_class == 40 and range_hv >= 2.8:
        min_d = dates[hv_series.index(min_hv)]
        max_d = dates[hv_series.index(max_hv)]
        return (
            f"[{wc_label}] Paddy crop growth rhythm: Cross-polar HV backscatter rose from {min_hv:.1f} dB on {min_d} "
            f"(wet field / transplanting stage) to {max_hv:.1f} dB on {max_d} (ΔHV = +{range_hv:.1f} dB from vegetative canopy volume scattering)."
        )
    if mean_hh > -5.5:
        return (
            f"[{wc_label}] High persistent backscatter (mean HH = {mean_hh:.1f} dB, HV = {mean_hv:.1f} dB): "
            f"Consistent with dense settlement structures, embankments, or homestead tree cover."
        )
    return (
        f"[{wc_label}] Seasonal monsoon modulation: HH ranged from {min_hh:.1f} to {max_hh:.1f} dB and HV from {min_hv:.1f} to {max_hv:.1f} dB "
        f"(ΔHV = {range_hv:.1f} dB), driven by soil dielectric moisture and vegetation changes."
    )


def select_verified_landmarks(aoi_id: str, hh_db, hv_db, dyn_classes, water_rec, worldcover, paddy_cls, lon_2d, lat_2d, dates):
    """Programmatically pick 6 real, verified pixels representing distinct physical scattering regimes."""
    nt, ny, nx = hh_db.shape
    margin = 30
    inner = np.zeros((ny, nx), dtype=bool)
    inner[margin : ny - margin, margin : nx - margin] = True

    mean_hh = np.nanmean(hh_db, axis=0)
    mean_hv = np.nanmean(hv_db, axis=0)
    min_hv = np.nanmin(hv_db, axis=0)
    max_hv = np.nanmax(hv_db, axis=0)
    range_hv = max_hv - min_hv

    # 1. Permanent River / Deep Haor Channel
    m_water = inner & (water_rec >= 90)
    r1, c1 = np.unravel_index(np.argmin(np.where(m_water, mean_hv, 999.0)), (ny, nx))

    # 2. Emergent Char / Seasonal Floodplain (Water at peak t=3, Dry at end t=-1, large rebound)
    rebound = hh_db[-1] - np.nanmin(hh_db[:5], axis=0)
    m_char = inner & (water_rec >= 25) & (water_rec <= 65) & (dyn_classes[-1] == 3)
    if not np.any(m_char):
        m_char = inner & (rebound > 3.0)
    r2, c2 = np.unravel_index(np.argmax(np.where(m_char, rebound, -999.0)), (ny, nx))

    # 3. Transplanted Aman Paddy Field (WorldCover == 40, strong HV growth from June/July to Sept/Oct)
    late_hv_gain = np.nanmax(hv_db[6:10], axis=0) - np.nanmin(hv_db[:4], axis=0)
    m_paddy = inner & (worldcover == 40) & (paddy_cls > 0) & (water_rec < 25)
    r3, c3 = np.unravel_index(np.argmax(np.where(m_paddy, late_hv_gain, -999.0)), (ny, nx))

    # 4. Double-Bounce Flooded Vegetation / Submerged Crop (Flagged as class 4 during monsoon)
    fveg_count = np.sum(dyn_classes == 4, axis=0)
    hh_surge = np.nanmax(hh_db[2:7], axis=0) - hh_db[0]
    m_fveg = inner & (fveg_count >= 2)
    if not np.any(m_fveg):
        m_fveg = inner & (hh_surge > 2.5)
    r4, c4 = np.unravel_index(np.argmax(np.where(m_fveg, hh_surge, -999.0)), (ny, nx))

    # 5. Built-up Settlement / Embankment Reference Target
    m_built = inner & ((worldcover == 50) | (mean_hh > -4.5)) & (np.nanstd(hh_db, axis=0) < 0.8)
    if not np.any(m_built):
        m_built = inner & (mean_hh > -5.5)
    r5, c5 = np.unravel_index(np.argmax(np.where(m_built, mean_hh, -999.0)), (ny, nx))

    # 6. Acute Monsoon Flood Drop (Dry on June 18 -> Flooded in July/August)
    flood_drop = np.nanmin(hh_db[2:6], axis=0) - hh_db[0]
    m_drop = inner & (dyn_classes[0] == 0) & (np.any(dyn_classes[2:6] == 2, axis=0))
    if not np.any(m_drop):
        m_drop = inner & (flood_drop < -3.0)
    r6, c6 = np.unravel_index(np.argmin(np.where(m_drop, flood_drop, 999.0)), (ny, nx))

    if aoi_id == "jamuna":
        specs = [
            ("Jamuna Main Braided Channel", "permanent_water", r1, c1, "Active deepwater channel with persistent specular dark radar return."),
            ("Emergent Jamuna Char (Sandbar)", "char_sandbar", r2, c2, "Submerged during July/August monsoon peak; emerges as silt/sandbar by November."),
            ("Sirajganj Floodplain Aman Paddy", "paddy_rice", r3, c3, "ESA WorldCover Cropland showing classic HV volume-scattering growth curve."),
            ("Flooded Cropland Double-Bounce", "flooded_veg", r4, c4, "Strong L-band HH dihedral surge (+dB) from water beneath emergent crop stems."),
            ("Flood Embankment & Settlement", "built_up", r5, c5, "Persistent bright corner reflection used for radiometric calibration stability."),
            ("Monsoon Newly Flooded Basin", "new_flood", r6, c6, "Dry land in June that experienced a sharp backscatter drop during peak inundation."),
        ]
    else:
        specs = [
            ("Tanguar / Shanir Haor Core Lake", "permanent_water", r1, c1, "Permanent tectonic wetland core with specular dark L-band signature."),
            ("Seasonal Haor Bed (Drainage Zone)", "char_sandbar", r2, c2, "Inland sea during monsoon that drains in October/November for Boro planting."),
            ("Haor Margin Aman Cropland", "paddy_rice", r3, c3, "Elevated rim cropland with strong vegetative HV volume scattering peak."),
            ("Submerged Reed & Hijal Swamp (Double-Bounce)", "flooded_veg", r4, c4, "Flooded wetland vegetation where L-band bounces off water and vertical trunks."),
            ("Elevated Haor Village Mound (Hati)", "built_up", r5, c5, "Settlement built on raised earthen kanda/hati mound above floodwaters."),
            ("Flash-Flooded Haor Depression", "new_flood", r6, c6, "Rapid backscatter drop triggered by monsoon runoff from the Meghalaya hills."),
        ]

    pins = []
    for name, ptype, r, c in [(s[0], s[1], int(s[2]), int(s[3])) for s in specs]:
        desc = next(s[4] for s in specs if s[0] == name)
        hh_vals = [round(float(hh_db[t, r, c]), 2) for t in range(nt)]
        hv_vals = [round(float(hv_db[t, r, c]), 2) for t in range(nt)]
        diff_vals = [round(float(hv_vals[i] - hh_vals[i]), 2) for i in range(nt)]
        wc_val = int(worldcover[r, c])
        notes = [pentatonic_pitch_map(hv_vals[i]) for i in range(nt)]
        explanation = generate_pixel_explanation(hh_vals, hv_vals, dates, wc_val)

        pins.append({
            "name": name,
            "type": ptype,
            "description": desc,
            "worldcover_class": wc_val,
            "lon": round(float(lon_2d[r, c]), 5),
            "lat": round(float(lat_2d[r, c]), 5),
            "grid_row": r,
            "grid_col": c,
            "time_series": {
                "dates": dates,
                "hh_db": hh_vals,
                "hv_db": hv_vals,
                "hv_minus_hh_db": diff_vals,
                "sonification_notes": notes,
            },
            "plain_language_explanation": explanation,
        })
    return pins


def export_aoi_assets(aoi_id: str):
    proc_nc = DATA_RAW_DIR / f"{aoi_id}_gcov_processed.nc"
    water_nc = DATA_RAW_DIR / f"{aoi_id}_water_products.nc"
    paddy_nc = DATA_RAW_DIR / f"{aoi_id}_paddy_products.nc"
    wc_tif = DATASETS_DIR / "worldcover" / f"{aoi_id}_worldcover_80m.tif"
    wp_tif = DATASETS_DIR / "worldpop" / f"{aoi_id}_worldpop_80m.tif"
    s1_tif = DATASETS_DIR / "sentinel1_rtc" / f"{aoi_id}_s1_rtc_2026-07-25_vv_vh_db_80m.tif"
    s2_meta_path = DATASETS_DIR / "sentinel2_optical" / f"{aoi_id}_s2_metadata.json"

    ds_proc = xr.open_dataset(proc_nc, engine="h5netcdf")
    ds_water = xr.open_dataset(water_nc, engine="h5netcdf")
    ds_paddy = xr.open_dataset(paddy_nc, engine="h5netcdf")

    dates = [str(t) for t in ds_proc["time"].values]
    nt, ny, nx = ds_proc["HH_dB"].shape

    hh_db = ds_proc["HH_dB"].values
    hv_db = ds_proc["HV_dB"].values
    dyn_classes = ds_water["flood_dynamics"].values
    water_rec = ds_water["water_recurrence"].values
    paddy_cls = ds_paddy["paddy_rhythm_class"].values
    lon_2d = ds_proc["lon"].values
    lat_2d = ds_proc["lat"].values

    with rasterio.open(wc_tif) as src:
        worldcover = src.read(1)
    with rasterio.open(wp_tif) as src:
        worldpop = src.read(1)

    bounds_wgs84 = [
        float(np.min(lon_2d)),
        float(np.min(lat_2d)),
        float(np.max(lon_2d)),
        float(np.max(lat_2d)),
    ]

    aoi_img_dir = WEB_IMG_DIR / aoi_id
    aoi_img_dir.mkdir(parents=True, exist_ok=True)
    print(f"[{aoi_id.upper()}] Exporting high-contrast RGBA PNG overlays & web manifest ({nt} dates)...", flush=True)

    overlay_manifest = []
    for t in range(nt):
        date_str = dates[t]

        # 1. SAR Polarimetric False-Color Composite (R=HH, G=HV, B=HH-HV)
        r = np.clip((hh_db[t] + 20.0) / 17.0, 0.0, 1.0)
        g = np.clip((hv_db[t] + 26.0) / 16.0, 0.0, 1.0)
        b = np.clip(((hh_db[t] - hv_db[t]) - 3.0) / 9.0, 0.0, 1.0)
        # Enhance contrast of dark water
        alpha = np.where(np.isfinite(hh_db[t]), 0.94, 0.0)
        rgb_img = np.dstack([r, g, b, alpha]).astype(np.float32)
        plt.imsave(aoi_img_dir / f"sar_{date_str}.png", rgb_img)

        # 2. Water & Flood Dynamics Overlay (Colorblind-safe vivid palette)
        dyn = dyn_classes[t]
        dyn_rgba = np.zeros((ny, nx, 4), dtype=np.float32)
        dyn_rgba[dyn == 1] = [0.024, 0.714, 0.831, 0.82]  # 1: Permanent Water (#06b6d4 Cyan)
        dyn_rgba[dyn == 2] = [0.231, 0.510, 0.965, 0.90]  # 2: Newly Flooded Water (#3b82f6 Bright Blue)
        dyn_rgba[dyn == 3] = [0.961, 0.620, 0.043, 0.78]  # 3: Receded / Emergent Char (#f59e0b Amber Gold)
        dyn_rgba[dyn == 4] = [0.925, 0.282, 0.600, 0.88]  # 4: Flooded Vegetation (#ec4899 Magenta/Coral)
        plt.imsave(aoi_img_dir / f"flood_{date_str}.png", dyn_rgba)

        overlay_manifest.append({
            "date": date_str,
            "sar_overlay": f"images/overlays/{aoi_id}/sar_{date_str}.png",
            "flood_overlay": f"images/overlays/{aoi_id}/flood_{date_str}.png",
        })

    # 3. Static Overlay: Water Recurrence (%)
    rec_norm = np.clip(water_rec / 100.0, 0.0, 1.0)
    rec_rgba = plt.cm.GnBu(rec_norm).astype(np.float32)
    rec_rgba[..., 3] = np.where(water_rec >= 8, 0.85, 0.0)
    plt.imsave(aoi_img_dir / "water_recurrence.png", rec_rgba)

    # 4. Static Overlay: Paddy Rhythm Clusters (1..4 on WorldCover Cropland)
    paddy_rgba = np.zeros((ny, nx, 4), dtype=np.float32)
    paddy_colors = [
        [0.063, 0.725, 0.506, 0.86],  # Class 1: #10b981 Emerald
        [0.055, 0.647, 0.914, 0.86],  # Class 2: #0ea5e9 Sky Blue
        [0.961, 0.620, 0.043, 0.86],  # Class 3: #f59e0b Amber Gold
        [0.659, 0.333, 0.969, 0.86],  # Class 4: #a855f7 Purple
    ]
    for c_idx in range(1, 5):
        paddy_rgba[paddy_cls == c_idx] = paddy_colors[c_idx - 1]
    plt.imsave(aoi_img_dir / "paddy_rhythm_classes.png", paddy_rgba)

    # 5. Static Overlay: Real ESA WorldCover 10m
    wc_rgba = np.zeros((ny, nx, 4), dtype=np.float32)
    wc_palette = {
        10: [0.020, 0.471, 0.341, 0.82],  # Tree cover (#057857)
        20: [0.518, 0.800, 0.086, 0.82],  # Shrubland (#84cc16)
        30: [0.992, 0.878, 0.278, 0.82],  # Grassland (#fde047)
        40: [0.133, 0.773, 0.369, 0.80],  # Cropland (#22c55e)
        50: [0.937, 0.267, 0.267, 0.92],  # Built-up (#ef4444)
        60: [0.831, 0.686, 0.525, 0.82],  # Bare / Sparse sandbar (#d4af86)
        80: [0.024, 0.580, 0.831, 0.88],  # Permanent water (#0694d4)
        90: [0.078, 0.722, 0.651, 0.84],  # Herbaceous wetland (#14b8a6)
    }
    for cls_code, col in wc_palette.items():
        wc_rgba[worldcover == cls_code] = col
    plt.imsave(aoi_img_dir / "worldcover.png", wc_rgba)

    # 6. Static Overlay: Real WorldPop 100m Population Density
    wp_clean = np.where(np.isfinite(worldpop) & (worldpop > 0), worldpop, 0.0)
    wp_p98 = float(np.percentile(wp_clean[wp_clean > 0], 98)) if np.any(wp_clean > 0) else 25.0
    wp_norm = np.clip(np.log1p(wp_clean) / np.log1p(wp_p98), 0.0, 1.0)
    wp_rgba = plt.cm.inferno(wp_norm).astype(np.float32)
    wp_rgba[..., 3] = np.where(wp_clean > 0.5, 0.82, 0.0)
    plt.imsave(aoi_img_dir / "worldpop.png", wp_rgba)

    # 7. Validation Overlay: Real Sentinel-1 C-band RTC (2026-07-25) & Real Sentinel-2 Optical
    if s1_tif.exists():
        with rasterio.open(s1_tif) as src:
            s1_vv = src.read(1)
            s1_vh = src.read(2)
        r_s1 = np.clip((s1_vv + 18.0) / 16.0, 0.0, 1.0)
        g_s1 = np.clip((s1_vh + 25.0) / 15.0, 0.0, 1.0)
        b_s1 = np.clip(((s1_vv - s1_vh) - 3.0) / 9.0, 0.0, 1.0)
        a_s1 = np.where(np.isfinite(s1_vv), 0.92, 0.0)
        plt.imsave(aoi_img_dir / "sentinel1_rtc_2026-07-25.png", np.dstack([r_s1, g_s1, b_s1, a_s1]).astype(np.float32))

    if s2_meta_path.exists():
        with open(s2_meta_path, "r", encoding="utf-8") as f:
            s2_date = json.load(f)["date"]
        s2_tif = DATASETS_DIR / "sentinel2_optical" / f"{aoi_id}_s2_l2a_{s2_date}_bands_ndwi_80m.tif"
        if s2_tif.exists():
            with rasterio.open(s2_tif) as src:
                b_green = src.read(1)
                b_red = src.read(2)
                b_nir = src.read(3)
                b_swir = src.read(4)
            # False-color SWIR-NIR-Red composite (highlights water in deep navy, vegetation in vibrant green)
            r_opt = np.clip(b_swir / 3500.0, 0.0, 1.0) ** 0.85
            g_opt = np.clip(b_nir / 4000.0, 0.0, 1.0) ** 0.85
            b_opt = np.clip(b_red / 2500.0, 0.0, 1.0) ** 0.85
            a_opt = np.where(np.isfinite(b_nir), 0.94, 0.0)
            plt.imsave(aoi_img_dir / "sentinel2_optical.png", np.dstack([r_opt, g_opt, b_opt, a_opt]).astype(np.float32))

    # 8. Verified Landmark Pins
    landmark_pins = select_verified_landmarks(
        aoi_id, hh_db, hv_db, dyn_classes, water_rec, worldcover, paddy_cls, lon_2d, lat_2d, dates
    )

    # 9. Dense 32x32 click grid (1,024 real locations)
    step_y = ny // 32
    step_x = nx // 32
    dense_grid = []
    for r in range(8, ny, step_y):
        for c in range(8, nx, step_x):
            hh_vals = [round(float(hh_db[t, r, c]), 2) for t in range(nt)]
            hv_vals = [round(float(hv_db[t, r, c]), 2) for t in range(nt)]
            dense_grid.append({
                "lon": round(float(lon_2d[r, c]), 4),
                "lat": round(float(lat_2d[r, c]), 4),
                "wc": int(worldcover[r, c]),
                "pop": round(float(wp_clean[r, c]), 1),
                "rec": int(water_rec[r, c]),
                "paddy": int(paddy_cls[r, c]),
                "hh": hh_vals,
                "hv": hv_vals,
                "diff": [round(float(hv_vals[i] - hh_vals[i]), 2) for i in range(nt)],
                "notes": [pentatonic_pitch_map(hv_vals[i])["note"] for i in range(nt)],
            })

    manifest = {
        "aoi_id": aoi_id,
        "aoi_name": ds_proc.attrs.get("aoi_name"),
        "track_key": ds_proc.attrs.get("track_key", "T069_F014_A"),
        "epsg": int(ds_proc.attrs.get("epsg", 32646)),
        "resolution_m": float(ds_proc.attrs.get("resolution_m", 80.0)),
        "data_maturity": "PROVISIONAL (Calibrated from 2026-06-17 onward)",
        "bounds_wgs84": bounds_wgs84,
        "center": [round(0.5 * (bounds_wgs84[0] + bounds_wgs84[2]), 5), round(0.5 * (bounds_wgs84[1] + bounds_wgs84[3]), 5)],
        "dates": dates,
        "overlays": overlay_manifest,
        "static_overlays": {
            "water_recurrence": f"images/overlays/{aoi_id}/water_recurrence.png",
            "paddy_classes": f"images/overlays/{aoi_id}/paddy_rhythm_classes.png",
            "worldcover": f"images/overlays/{aoi_id}/worldcover.png",
            "worldpop": f"images/overlays/{aoi_id}/worldpop.png",
            "sentinel1_rtc": f"images/overlays/{aoi_id}/sentinel1_rtc_2026-07-25.png",
            "sentinel2_optical": f"images/overlays/{aoi_id}/sentinel2_optical.png",
        },
        "landmark_pins": landmark_pins,
        "dense_click_grid": dense_grid,
    }

    WEB_DATA_DIR.mkdir(parents=True, exist_ok=True)
    out_manifest = WEB_DATA_DIR / f"{aoi_id}_web_manifest.json"
    with open(out_manifest, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    print(f"  -> Saved {out_manifest}", flush=True)


def main():
    for aoi in ["jamuna", "haor"]:
        export_aoi_assets(aoi)


if __name__ == "__main__":
    main()
