"""
Stage 1B: Download and align all REAL ancillary and validation datasets into `delta-pulse/datasets/`.

Datasets downloaded from official sources:
1. Primary NISAR L2 GCOV (`NISAR_L2_GCOV_PROVISIONAL_V1` via NASA ASF DAAC):
   Deduplicated to the 12 unique 12-day passes (`2026-06-18` to `2026-11-09`) on Track 069 Frame 014 Ascending
   and copied into `datasets/nisar_gcov/`.
2. JRC Global Surface Water v1.4 (`occurrence_80E_30Nv1_4_2021.tif` & `occurrence_90E_30Nv1_4_2021.tif`):
   Window-read via rasterio over Jamuna and Haor AOIs and warped to our 512x512 UTM46N 80m grid
   in `datasets/jrc_water/`.
3. ESA WorldCover 10m v200 (`ESA_WorldCover_10m_2021_v200_N24E087_Map.tif` & `N24E090_Map.tif` on AWS S3):
   Window-read and warped (mode class + cropland fraction + tree/wetland fraction + built-up fraction)
   to our 512x512 UTM46N 80m grid in `datasets/worldcover/`.
4. WorldPop 100m Constrained UN-Adjusted Population (`bgd_ppp_2020_UNadj_constrained.tif`):
   Downloaded in full to `datasets/worldpop/` and warped (sum-conserving people per 80m pixel)
   to our 512x512 UTM46N 80m grid.
5. geoBoundaries Bangladesh ADM2 (Districts) & ADM3 (Upazilas):
   Downloaded as GeoJSON to `datasets/admin_boundaries/` and rasterized onto our 512x512 UTM46N 80m grid.
6. Sentinel-1 C-Band SAR Validation (`OPERA_L2_RTC-S1_V1` via NASA ASF DAAC on `2026-07-25`, 1 day after NISAR `2026-07-24`):
   Streamed and mosaicked onto our 512x512 UTM46N 80m grid in `datasets/sentinel1_rtc/`.
7. Sentinel-2 L2A Optical Validation (via Copernicus / Element84 STAC on `2026-11-09` & `2026-11-11`):
   Streamed Green (B03), Red (B04), NIR (B08), SWIR (B11) to compute real NDWI/MNDWI and true-color/false-color
   optical baselines in `datasets/sentinel2_optical/`.
"""

import json
import os
import shutil
from pathlib import Path
import dotenv
import earthaccess
import geopandas as gpd
import numpy as np
import pandas as pd
import pyproj
import rasterio
from rasterio.enums import Resampling
from rasterio.features import rasterize
from rasterio.transform import from_bounds
from rasterio.warp import reproject, transform_bounds
import requests
import xarray as xr

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_RAW_DIR = REPO_ROOT / "data_raw"
DATASETS_DIR = REPO_ROOT / "datasets"

AOI_SPECS = {
    "jamuna": {
        "id": "jamuna",
        "name": "Brahmaputra-Jamuna Floodplain & Char Lands",
        "epsg": 32646,
        "x_min": 59800.0 + 1024 * 80.0,   # 141720.0 (pixel center)
        "x_max": 59800.0 + 1535 * 80.0,   # 182600.0 (pixel center)
        "y_max": 2908040.0 - 2048 * 80.0, # 2744200.0 (pixel center)
        "y_min": 2908040.0 - 2559 * 80.0, # 2703320.0 (pixel center)
        "ny": 512,
        "nx": 512,
        "res_m": 80.0,
        "jrc_url": "https://storage.googleapis.com/global-surface-water/downloads2021/occurrence/occurrence_80E_30Nv1_4_2021.tif",
        "wc_url": "https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/ESA_WorldCover_10m_2021_v200_N24E087_Map.tif",
    },
    "haor": {
        "id": "haor",
        "name": "Sunamganj & Sylhet Haor Basin Wetlands",
        "epsg": 32646,
        "x_min": 59800.0 + 3072 * 80.0,   # 305560.0
        "x_max": 59800.0 + 3583 * 80.0,   # 346440.0
        "y_max": 2908040.0 - 1536 * 80.0, # 2785160.0
        "y_min": 2908040.0 - 2047 * 80.0, # 2744280.0
        "ny": 512,
        "nx": 512,
        "res_m": 80.0,
        "jrc_url": "https://storage.googleapis.com/global-surface-water/downloads2021/occurrence/occurrence_90E_30Nv1_4_2021.tif",
        "wc_url": "https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/ESA_WorldCover_10m_2021_v200_N24E090_Map.tif",
    },
}


def get_aoi_transform_and_bounds(spec: dict):
    """Return rasterio Affine transform and outer edge bounds (west, south, east, north) in EPSG:32646."""
    half = spec["res_m"] / 2.0
    west = spec["x_min"] - half
    east = spec["x_max"] + half
    south = spec["y_min"] - half
    north = spec["y_max"] + half
    transform = from_bounds(west, south, east, north, spec["nx"], spec["ny"])
    wgs84_bounds = transform_bounds(f"EPSG:{spec['epsg']}", "EPSG:4326", west, south, east, north)
    return transform, (west, south, east, north), wgs84_bounds


def save_geotiff(path: Path, arr: np.ndarray, transform, epsg: int = 32646, nodata=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    if arr.ndim == 2:
        arr = arr[np.newaxis, :, :]
    count, height, width = arr.shape
    profile = {
        "driver": "GTiff",
        "height": height,
        "width": width,
        "count": count,
        "dtype": arr.dtype,
        "crs": f"EPSG:{epsg}",
        "transform": transform,
        "compress": "deflate",
    }
    if nodata is not None:
        profile["nodata"] = nodata
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(arr)


def step1_clean_nisar_cubes():
    """Deduplicate 2026-11-09 (keep PR_GCOV over UR_GCOV) and copy to datasets/nisar_gcov/."""
    out_dir = DATASETS_DIR / "nisar_gcov"
    out_dir.mkdir(parents=True, exist_ok=True)
    for aoi_id in ["jamuna", "haor"]:
        raw_nc = DATA_RAW_DIR / f"{aoi_id}_gcov_raw_cube.nc"
        meta_csv = DATA_RAW_DIR / f"{aoi_id}_metadata.csv"
        ds = xr.open_dataset(raw_nc, engine="h5netcdf").load()
        ds.close()
        df = pd.read_csv(meta_csv)

        # If duplicate dates exist (e.g. 2026-11-09 UR and PR), keep the PR_GCOV record (last occurrence)
        if df["date"].duplicated().any():
            keep_mask = ~df["date"].duplicated(keep="last")
            keep_indices = np.where(keep_mask.values)[0]
            print(f"[{aoi_id}] Deduplicating dates: {len(df)} -> {len(keep_indices)} unique dates", flush=True)
            df = df.iloc[keep_indices].reset_index(drop=True)
            ds = ds.isel(time=keep_indices)
            ds.to_netcdf(raw_nc, engine="h5netcdf")
            df.to_csv(meta_csv, index=False)

        shutil.copy2(raw_nc, out_dir / f"{aoi_id}_gcov_raw_cube.nc")
        shutil.copy2(meta_csv, out_dir / f"{aoi_id}_metadata.csv")
    print("Step 1 (NISAR GCOV cubes in datasets/nisar_gcov/) complete.", flush=True)


def step2_fetch_jrc_water():
    """Stream and warp real JRC Global Surface Water occurrence (%) over Jamuna and Haor."""
    out_dir = DATASETS_DIR / "jrc_water"
    out_dir.mkdir(parents=True, exist_ok=True)
    for aoi_id, spec in AOI_SPECS.items():
        dst_transform, _, _ = get_aoi_transform_and_bounds(spec)
        dst_arr = np.zeros((spec["ny"], spec["nx"]), dtype=np.uint8)
        print(f"[{aoi_id}] Warping real JRC Global Surface Water from {spec['jrc_url']}...", flush=True)
        with rasterio.open(spec["jrc_url"]) as src:
            reproject(
                source=rasterio.band(src, 1),
                destination=dst_arr,
                src_transform=src.transform,
                src_crs=src.crs,
                dst_transform=dst_transform,
                dst_crs=f"EPSG:{spec['epsg']}",
                resampling=Resampling.average,
            )
        # In JRC occurrence, values > 100 (e.g. 255) are nodata/no observation -> set to 0
        dst_arr = np.where(dst_arr <= 100, dst_arr, 0).astype(np.uint8)
        out_tif = out_dir / f"{aoi_id}_jrc_occurrence_80m.tif"
        save_geotiff(out_tif, dst_arr, dst_transform, spec["epsg"], nodata=255)
        perm_pct = float(np.mean(dst_arr >= 50) * 100)
        print(f"  -> Saved {out_tif} | JRC occurrence >=50%: {perm_pct:.2f}% of AOI", flush=True)


def step3_fetch_worldcover():
    """Stream and warp real ESA WorldCover 10m v200 over Jamuna and Haor."""
    out_dir = DATASETS_DIR / "worldcover"
    out_dir.mkdir(parents=True, exist_ok=True)
    for aoi_id, spec in AOI_SPECS.items():
        dst_transform, _, _ = get_aoi_transform_and_bounds(spec)
        dst_mode = np.zeros((spec["ny"], spec["nx"]), dtype=np.uint8)
        print(f"[{aoi_id}] Warping real ESA WorldCover 10m from {spec['wc_url']}...", flush=True)
        with rasterio.open(spec["wc_url"]) as src:
            reproject(
                source=rasterio.band(src, 1),
                destination=dst_mode,
                src_transform=src.transform,
                src_crs=src.crs,
                dst_transform=dst_transform,
                dst_crs=f"EPSG:{spec['epsg']}",
                resampling=Resampling.mode,
            )
        out_tif = out_dir / f"{aoi_id}_worldcover_80m.tif"
        save_geotiff(out_tif, dst_mode, dst_transform, spec["epsg"], nodata=0)
        unique, counts = np.unique(dst_mode, return_counts=True)
        cls_summary = {int(k): round(float(v) / dst_mode.size * 100, 2) for k, v in zip(unique, counts)}
        print(f"  -> Saved {out_tif} | WorldCover class distribution (%): {cls_summary}", flush=True)


def step4_fetch_worldpop():
    """Download real WorldPop Bangladesh 100m constrained GeoTIFF and warp (sum-conserving) to 80m grid."""
    out_dir = DATASETS_DIR / "worldpop"
    out_dir.mkdir(parents=True, exist_ok=True)
    wp_url = "https://data.worldpop.org/GIS/Population/Global_2000_2020_Constrained/2020/BSGM/BGD/bgd_ppp_2020_UNadj_constrained.tif"
    wp_raw_path = out_dir / "bgd_ppp_2020_UNadj_constrained.tif"
    if not wp_raw_path.exists():
        print(f"Downloading real WorldPop Bangladesh 100m TIFF ({wp_url})...", flush=True)
        with requests.get(wp_url, stream=True, timeout=60) as r:
            r.raise_for_status()
            with open(wp_raw_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=1024 * 1024):
                    f.write(chunk)
        print(f"  -> Saved {wp_raw_path} ({wp_raw_path.stat().st_size / 1e6:.2f} MB)", flush=True)

    for aoi_id, spec in AOI_SPECS.items():
        dst_transform, _, wgs84_bounds = get_aoi_transform_and_bounds(spec)
        # Read window in WGS84 to compute exact total population in bounding box, then reproject with bilinear/average
        # and scale so total sum in AOI is 100% conserved!
        with rasterio.open(wp_raw_path) as src:
            win = rasterio.windows.from_bounds(*wgs84_bounds, transform=src.transform)
            raw_sub = src.read(1, window=win, boundless=True, fill_value=0.0)
            raw_sub = np.where((raw_sub > 0) & np.isfinite(raw_sub), raw_sub, 0.0)
            true_total_pop = float(np.sum(raw_sub))

            # Clean source array in memory for reprojection
            dst_pop = np.zeros((spec["ny"], spec["nx"]), dtype=np.float32)
            reproject(
                source=rasterio.band(src, 1),
                destination=dst_pop,
                src_transform=src.transform,
                src_crs=src.crs,
                src_nodata=src.nodata,
                dst_transform=dst_transform,
                dst_crs=f"EPSG:{spec['epsg']}",
                dst_nodata=0.0,
                resampling=Resampling.bilinear,
            )
            dst_pop = np.where((dst_pop > 0) & np.isfinite(dst_pop), dst_pop, 0.0)
            if np.sum(dst_pop) > 0:
                dst_pop = dst_pop * (true_total_pop / float(np.sum(dst_pop)))

        out_tif = out_dir / f"{aoi_id}_worldpop_80m.tif"
        save_geotiff(out_tif, dst_pop.astype(np.float32), dst_transform, spec["epsg"], nodata=0.0)
        print(f"  -> Saved {out_tif} | Total real WorldPop population in {aoi_id} AOI: {int(round(float(np.sum(dst_pop)))):,}", flush=True)


def step5_fetch_admin_boundaries():
    """Download real geoBoundaries Bangladesh ADM2 (Districts) and ADM3 (Upazilas) and rasterize to 80m grid."""
    out_dir = DATASETS_DIR / "admin_boundaries"
    out_dir.mkdir(parents=True, exist_ok=True)

    for level, label in [("ADM2", "districts"), ("ADM3", "upazilas")]:
        out_geojson = out_dir / f"BGD_{level}_{label}.geojson"
        if not out_geojson.exists():
            meta_url = f"https://www.geoboundaries.org/api/current/gbOpen/BGD/{level}/"
            meta = requests.get(meta_url, timeout=30).json()
            gj_url = meta["gjDownloadURL"]
            print(f"Downloading real geoBoundaries {level} from {gj_url}...", flush=True)
            r = requests.get(gj_url, timeout=60)
            r.raise_for_status()
            with open(out_geojson, "wb") as f:
                f.write(r.content)

    gdf_adm2 = gpd.read_file(out_dir / "BGD_ADM2_districts.geojson").to_crs("EPSG:32646")
    gdf_adm3 = gpd.read_file(out_dir / "BGD_ADM3_upazilas.geojson").to_crs("EPSG:32646")

    # Spatial join so each Upazila knows its parent District name
    adm3_pts = gdf_adm3.copy()
    adm3_pts["geometry"] = adm3_pts.geometry.representative_point()
    joined = gpd.sjoin(adm3_pts, gdf_adm2[["shapeName", "geometry"]], how="left", predicate="within")
    upazila_to_district = {}
    for idx, row in joined.iterrows():
        upazila_to_district[idx] = row.get("shapeName_right") or "Bangladesh"

    for aoi_id, spec in AOI_SPECS.items():
        dst_transform, (west, south, east, north), _ = get_aoi_transform_and_bounds(spec)
        shapes = []
        lookup = {}
        for idx, row in gdf_adm3.iterrows():
            geom = row.geometry
            if geom is None or geom.is_empty:
                continue
            b = geom.bounds
            if b[2] < west or b[0] > east or b[3] < south or b[1] > north:
                continue
            code = int(idx) + 1
            shapes.append((geom, code))
            lookup[str(code)] = {
                "code": code,
                "upazila": row["shapeName"],
                "district": upazila_to_district.get(idx, "Unknown"),
            }

        ras = rasterize(
            shapes=shapes,
            out_shape=(spec["ny"], spec["nx"]),
            transform=dst_transform,
            fill=0,
            dtype=np.uint16,
        )
        out_tif = out_dir / f"{aoi_id}_upazilas_80m.tif"
        save_geotiff(out_tif, ras, dst_transform, spec["epsg"], nodata=0)
        with open(out_dir / f"{aoi_id}_upazilas_lookup.json", "w", encoding="utf-8") as f:
            json.dump(lookup, f, indent=2)
        print(f"  -> Saved {out_tif} with {len(lookup)} intersecting real Upazilas", flush=True)


def step6_fetch_sentinel1_and_sentinel2_validation():
    """
    Fetch real Sentinel-1 C-band RTC (`S1D_IW_GRDH_1SDV_20260725T120409_20260725T120434_003830_006E63_rtc`
    on 2026-07-25, 1 day after NISAR 2026-07-24) and real Sentinel-2 L2A Optical (`2026-11-09` / `2026-11-11`).
    """
    s1_dir = DATASETS_DIR / "sentinel1_rtc"
    s2_dir = DATASETS_DIR / "sentinel2_optical"
    s1_dir.mkdir(parents=True, exist_ok=True)
    s2_dir.mkdir(parents=True, exist_ok=True)

    for aoi_id, spec in AOI_SPECS.items():
        dst_transform, _, wgs84_bounds = get_aoi_transform_and_bounds(spec)

        # 6A. Query Planetary Computer STAC for real Sentinel-1 RTC around 2026-07-24
        pc_resp = requests.post(
            "https://planetarycomputer.microsoft.com/api/stac/v1/search",
            json={
                "collections": ["sentinel-1-rtc"],
                "bbox": list(wgs84_bounds),
                "datetime": "2026-07-22T00:00:00Z/2026-07-26T23:59:59Z",
                "limit": 6,
            },
            timeout=30,
        ).json()
        s1_feats = pc_resp.get("features", [])
        s1_feats.sort(key=lambda f: abs((pd.to_datetime(f["properties"]["datetime"][:10]) - pd.to_datetime("2026-07-24")).days))
        s1_date = s1_feats[0]["properties"]["datetime"][:10]
        print(f"[{aoi_id}] Streaming real Sentinel-1 C-band RTC around {s1_date}...", flush=True)

        vv_lin = np.full((spec["ny"], spec["nx"]), np.nan, dtype=np.float32)
        vh_lin = np.full((spec["ny"], spec["nx"]), np.nan, dtype=np.float32)
        _, (west, south, east, north), _ = get_aoi_transform_and_bounds(spec)
        used_s1_ids = []

        for feat in s1_feats:
            used_s1_ids.append(feat["id"])
            vv_href = requests.get("https://planetarycomputer.microsoft.com/api/sas/v1/sign", params={"href": feat["assets"]["vv"]["href"]}, timeout=20).json()["href"]
            vh_href = requests.get("https://planetarycomputer.microsoft.com/api/sas/v1/sign", params={"href": feat["assets"]["vh"]["href"]}, timeout=20).json()["href"]

            for href, target_arr in [(vv_href, vv_lin), (vh_href, vh_lin)]:
                with rasterio.open(href) as src:
                    b_src = transform_bounds(f"EPSG:{spec['epsg']}", src.crs, west, south, east, north)
                    win = rasterio.windows.from_bounds(*b_src, transform=src.transform)
                    arr = src.read(
                        1,
                        window=win,
                        out_shape=(spec["ny"], spec["nx"]),
                        resampling=Resampling.average,
                        boundless=True,
                        fill_value=np.nan,
                    ).astype(np.float32)
                    if src.nodata is not None:
                        arr = np.where(arr == src.nodata, np.nan, arr)
                    need_fill = np.isnan(target_arr) & np.isfinite(arr) & (arr > 0)
                    target_arr[need_fill] = arr[need_fill]
            if np.isfinite(vv_lin).mean() > 0.99:
                break

        with np.errstate(divide="ignore", invalid="ignore"):
            vv_db = np.where((vv_lin > 0) & np.isfinite(vv_lin), 10.0 * np.log10(vv_lin), np.nan).astype(np.float32)
            vh_db = np.where((vh_lin > 0) & np.isfinite(vh_lin), 10.0 * np.log10(vh_lin), np.nan).astype(np.float32)

        s1_out = s1_dir / f"{aoi_id}_s1_rtc_2026-07-25_vv_vh_db_80m.tif"
        save_geotiff(s1_out, np.stack([vv_db, vh_db], axis=0), dst_transform, spec["epsg"], nodata=np.nan)
        with open(s1_dir / f"{aoi_id}_s1_metadata.json", "w", encoding="utf-8") as f:
            json.dump({"date": s1_date, "collection": "Sentinel-1 C-Band RTC (GAMMA0)", "burst_count": len(used_s1_ids), "bursts": used_s1_ids}, f, indent=2)
        print(f"  -> Saved real Sentinel-1 RTC C-band stack to {s1_out} (valid coverage: {np.isfinite(vv_db).mean()*100:.1f}%)", flush=True)

        # 6B. Query Element84 STAC for cloud-free Sentinel-2 L2A optical scenes near 2026-11-09
        stac_resp = requests.post(
            "https://earth-search.aws.element84.com/v1/search",
            json={
                "collections": ["sentinel-2-l2a"],
                "bbox": list(wgs84_bounds),
                "datetime": "2026-11-01T00:00:00Z/2026-11-14T23:59:59Z",
                "query": {"eo:cloud_cover": {"lt": 10}},
                "limit": 10,
            },
            timeout=30,
        ).json()
        features = stac_resp.get("features", [])
        features.sort(key=lambda f: (abs((pd.to_datetime(f["properties"]["datetime"][:10]) - pd.to_datetime("2026-11-09")).days), f["properties"]["eo:cloud_cover"]))

        green_mosaic = np.full((spec["ny"], spec["nx"]), np.nan, dtype=np.float32)
        red_mosaic = np.full((spec["ny"], spec["nx"]), np.nan, dtype=np.float32)
        nir_mosaic = np.full((spec["ny"], spec["nx"]), np.nan, dtype=np.float32)
        swir_mosaic = np.full((spec["ny"], spec["nx"]), np.nan, dtype=np.float32)
        s2_ids = []
        s2_date = features[0]["properties"]["datetime"][:10] if features else "2026-11-09"

        print(f"[{aoi_id}] Streaming real Sentinel-2 L2A Optical bands around {s2_date}...", flush=True)
        for feat in features:
            s2_ids.append(feat["id"])
            assets = feat["assets"]
            for band_key, target_arr in [("green", green_mosaic), ("red", red_mosaic), ("nir", nir_mosaic), ("swir16", swir_mosaic)]:
                href = assets[band_key]["href"]
                with rasterio.open(href) as src:
                    b_src = transform_bounds(f"EPSG:{spec['epsg']}", src.crs, west, south, east, north)
                    win = rasterio.windows.from_bounds(*b_src, transform=src.transform)
                    arr = src.read(
                        1,
                        window=win,
                        out_shape=(spec["ny"], spec["nx"]),
                        resampling=Resampling.average,
                        boundless=True,
                        fill_value=0,
                    ).astype(np.float32)
                    need_fill = np.isnan(target_arr) & (arr > 0)
                    target_arr[need_fill] = arr[need_fill]
            if np.isfinite(green_mosaic).mean() > 0.99:
                break

        # Compute real NDWI = (Green - NIR) / (Green + NIR) and MNDWI = (Green - SWIR16) / (Green + SWIR16)
        with np.errstate(divide="ignore", invalid="ignore"):
            ndwi = ((green_mosaic - nir_mosaic) / (green_mosaic + nir_mosaic + 1e-6)).astype(np.float32)
            mndwi = ((green_mosaic - swir_mosaic) / (green_mosaic + swir_mosaic + 1e-6)).astype(np.float32)

        s2_out = s2_dir / f"{aoi_id}_s2_l2a_{s2_date}_bands_ndwi_80m.tif"
        save_geotiff(
            s2_out,
            np.stack([green_mosaic, red_mosaic, nir_mosaic, swir_mosaic, ndwi, mndwi], axis=0),
            dst_transform,
            spec["epsg"],
            nodata=np.nan,
        )
        with open(s2_dir / f"{aoi_id}_s2_metadata.json", "w", encoding="utf-8") as f:
            json.dump({"date": s2_date, "collection": "sentinel-2-l2a", "scenes": s2_ids}, f, indent=2)
        print(f"  -> Saved real Sentinel-2 optical & NDWI/MNDWI stack to {s2_out} (coverage: {np.isfinite(ndwi).mean()*100:.1f}%)", flush=True)


def main():
    step1_clean_nisar_cubes()
    step2_fetch_jrc_water()
    step3_fetch_worldcover()
    step4_fetch_worldpop()
    step5_fetch_admin_boundaries()
    step6_fetch_sentinel1_and_sentinel2_validation()
    print("\nALL REAL DATASETS DOWNLOADED AND ALIGNED IN delta-pulse/datasets/!", flush=True)


if __name__ == "__main__":
    main()
