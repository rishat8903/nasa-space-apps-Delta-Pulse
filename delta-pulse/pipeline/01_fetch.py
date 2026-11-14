"""
Stage 1 (Part A): Stream and subset NISAR L2 GCOV layers from ASF DAAC Earthdata Cloud.
Authenticates via earthaccess (.env), resolves pre-signed S3/CloudFront URLs for all 13
calibrated PROVISIONAL scenes on Track 069 Frame 014 Ascending (2026-06-18 to 2026-11-09),
and streams the exact UTM Zone 46N (EPSG:32646) subsets for both Hero AOIs:
  1. jamuna: Brahmaputra-Jamuna Floodplain & Char Lands (Sirajganj / Bogura / Jamalpur)
     UTM Easting [141720 .. 182600], Northing [2703320 .. 2744200] (512x512 @ 80m = 40.96 km x 40.96 km)
  2. haor: Sunamganj & Sylhet Haor Basin Wetlands (Tanguar, Shanir, Matian, Dekhar Haors)
     UTM Easting [305560 .. 346440], Northing [2744280 .. 2785160] (512x512 @ 80m = 40.96 km x 40.96 km)

Saves raw linear gamma-0 power cubes (time, y, x) for HHHH, HVHV, mask, and numberOfLooks
to NetCDF (.nc) plus scene metadata JSON/CSV.
"""

import concurrent.futures
import json
import os
import time
from pathlib import Path
import dotenv
import earthaccess
import fsspec
import h5py
import numpy as np
import pandas as pd
import pyproj
import xarray as xr

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_RAW_DIR = REPO_ROOT / "data_raw"
WEB_DATA_DIR = REPO_ROOT / "web" / "data"
DOCS_DIR = REPO_ROOT / "docs"

# Target UTM Zone 46N (EPSG:32646) 80m grid definitions (aligned to 512x512 HDF5 chunks of Scene 0)
# Scene 0 origin: x0 = 59800.0 (step +80.0), y0 = 2908040.0 (step -80.0)
HERO_SPECS = {
    "jamuna": {
        "id": "jamuna",
        "name": "Brahmaputra-Jamuna Floodplain & Char Lands",
        "subtitle": "Sirajganj, Bogura, Jamalpur & Tangail (North-Central Bangladesh)",
        "track_key": "T069_F014_A",
        "epsg": 32646,
        "x_min": 59800.0 + 1024 * 80.0,   # 141720.0
        "x_max": 59800.0 + 1535 * 80.0,   # 182600.0
        "y_max": 2908040.0 - 2048 * 80.0, # 2744200.0
        "y_min": 2908040.0 - 2559 * 80.0, # 2703320.0
        "ny": 512,
        "nx": 512,
        "res_m": 80.0,
    },
    "haor": {
        "id": "haor",
        "name": "Sunamganj & Sylhet Haor Basin Wetlands",
        "subtitle": "Tanguar, Shanir, Matian & Dekhar Haors (North-East Bangladesh)",
        "track_key": "T069_F014_A",
        "epsg": 32646,
        "x_min": 59800.0 + 3072 * 80.0,   # 305560.0
        "x_max": 59800.0 + 3583 * 80.0,   # 346440.0
        "y_max": 2908040.0 - 1536 * 80.0, # 2785160.0
        "y_min": 2908040.0 - 2047 * 80.0, # 2744280.0
        "ny": 512,
        "nx": 512,
        "res_m": 80.0,
    },
}


def extract_subset_on_common_grid(
    arr_ds, x_coords: np.ndarray, y_coords: np.ndarray, spec: dict, fill_val=np.nan
) -> np.ndarray:
    """
    Extract (512, 512) window matching target UTM grid [y_max..y_min, x_min..x_max]
    even if a scene's origin shifts by a few 80m pixels.
    """
    target_x = np.linspace(spec["x_min"], spec["x_max"], spec["nx"])
    target_y = np.linspace(spec["y_max"], spec["y_min"], spec["ny"])

    # Find indices in scene x_coords and y_coords
    ix0 = int(np.argmin(np.abs(x_coords - spec["x_min"])))
    ix1 = ix0 + spec["nx"]
    iy0 = int(np.argmin(np.abs(y_coords - spec["y_max"])))
    iy1 = iy0 + spec["ny"]

    ix0_clip = max(0, ix0)
    ix1_clip = min(len(x_coords), ix1)
    iy0_clip = max(0, iy0)
    iy1_clip = min(len(y_coords), iy1)

    sub = arr_ds[iy0_clip:iy1_clip, ix0_clip:ix1_clip]
    if sub.shape == (spec["ny"], spec["nx"]):
        return sub

    out = np.full((spec["ny"], spec["nx"]), fill_val, dtype=sub.dtype)
    dy0 = iy0_clip - iy0
    dx0 = ix0_clip - ix0
    out[dy0 : dy0 + sub.shape[0], dx0 : dx0 + sub.shape[1]] = sub
    return out


def fetch_single_scene(idx: int, scene: dict, signed_url: str) -> dict:
    """Stream both Hero AOI subsets + metadata from a single pre-signed NISAR GCOV HDF5 URL."""
    t0 = time.time()
    granule = scene["granule"]
    date_str = scene["date"]
    print(f"[{idx+1:02d}/13] Streaming {date_str} ({granule})...", flush=True)

    for attempt in range(3):
        try:
            f = fsspec.open(signed_url, "rb", block_size=262144, cache_type="bytes").open()
            with h5py.File(f, "r") as h5:
                fb = h5["science/LSAR/GCOV/grids/frequencyB"]
                rg = h5["science/LSAR/GCOV/metadata/radarGrid"]
                ident = h5["science/LSAR/identification"]

                x_coords = fb["xCoordinates"][:]
                y_coords = fb["yCoordinates"][:]
                epsg = int(fb["projection"][()])

                # Incidence angle summary at mid-height slice
                inc_cube = rg["incidenceAngle"]
                mid_z = inc_cube.shape[0] // 2
                inc_2d = inc_cube[mid_z, :, :]
                inc_rx = rg["xCoordinates"][:]
                inc_ry = rg["yCoordinates"][:]

                aoi_data = {}
                for aoi_id, spec in HERO_SPECS.items():
                    hh = extract_subset_on_common_grid(fb["HHHH"], x_coords, y_coords, spec, np.nan)
                    hv = extract_subset_on_common_grid(fb["HVHV"], x_coords, y_coords, spec, np.nan)
                    mask = extract_subset_on_common_grid(fb["mask"], x_coords, y_coords, spec, 0)
                    looks = extract_subset_on_common_grid(fb["numberOfLooks"], x_coords, y_coords, spec, np.nan)

                    # Incidence angle over AOI bounding box
                    ix_inc = (inc_rx >= spec["x_min"]) & (inc_rx <= spec["x_max"])
                    iy_inc = (inc_ry >= spec["y_min"]) & (inc_ry <= spec["y_max"])
                    inc_sub = inc_2d[np.ix_(iy_inc, ix_inc)]

                    aoi_data[aoi_id] = {
                        "HHHH": hh.astype(np.float32),
                        "HVHV": hv.astype(np.float32),
                        "mask": mask.astype(np.uint8),
                        "numberOfLooks": looks.astype(np.float32),
                        "inc_mean": float(np.nanmean(inc_sub)),
                        "inc_min": float(np.nanmin(inc_sub)),
                        "inc_max": float(np.nanmax(inc_sub)),
                    }

                pge_ver = ident["productVersion"][()].decode("utf-8") if isinstance(ident["productVersion"][()], bytes) else str(ident["productVersion"][()])

            f.close()
            dt = time.time() - t0
            print(
                f"  -> Done [{idx+1:02d}/13] {date_str} in {dt:.1f}s | Jamuna HH mean={np.nanmean(aoi_data['jamuna']['HHHH']):.4f} | Haor HH mean={np.nanmean(aoi_data['haor']['HHHH']):.4f}",
                flush=True,
            )
            return {
                "idx": idx,
                "date": date_str,
                "granule": granule,
                "cycle": scene["cycle"],
                "track": scene["track"],
                "frame": scene["frame"],
                "direction": scene["direction"],
                "mode": scene["mode"],
                "pol_code": scene["pol_code"],
                "crid": scene["crid"],
                "maturity": scene["maturity"],
                "epsg": epsg,
                "product_version": pge_ver,
                "aoi_data": aoi_data,
            }
        except Exception as e:
            print(f"  [WARN] Attempt {attempt+1} failed for {date_str}: {e}")
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"Failed to stream {granule} after 3 attempts")


def resolve_url(session, url, idx):
    for attempt in range(3):
        try:
            r = session.get(url, stream=True, allow_redirects=True, timeout=30)
            r.raise_for_status()
            signed = r.url
            r.close()
            return idx, signed
        except Exception as e:
            time.sleep(2)
    raise RuntimeError(f"Failed to resolve signed URL for {url}")


def main():
    dotenv.load_dotenv(REPO_ROOT / ".env")
    dotenv.load_dotenv(REPO_ROOT.parent / ".env")
    DATA_RAW_DIR.mkdir(parents=True, exist_ok=True)
    WEB_DATA_DIR.mkdir(parents=True, exist_ok=True)

    auth = earthaccess.login(strategy="environment")
    if not auth.authenticated:
        raise RuntimeError("Earthdata authentication failed. Check .env credentials.")

    cov_path = WEB_DATA_DIR / "aoi_coverage_raw.json"
    with open(cov_path, "r", encoding="utf-8") as f:
        cov = json.load(f)

    scenes = cov["jamuna"]["tracks"]["T069_F014_A"]["scenes"]
    print(f"Found {len(scenes)} calibrated PROVISIONAL scenes on T069_F014_A.", flush=True)

    # Step 1: Resolve pre-signed CloudFront URLs in parallel
    print("Resolving pre-signed CloudFront URLs in parallel...", flush=True)
    req_session = earthaccess.get_requests_https_session()
    signed_urls = [None] * len(scenes)
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        futures = [
            pool.submit(resolve_url, req_session, sc["downloadUrl"], i)
            for i, sc in enumerate(scenes)
        ]
        for fut in concurrent.futures.as_completed(futures):
            i, signed = fut.result()
            signed_urls[i] = signed
    print(f"Resolved all {len(signed_urls)} pre-signed CloudFront URLs successfully.", flush=True)

    # Step 2: Stream scenes in parallel (4 workers to avoid network saturation while maximizing throughput)
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futures = [
            pool.submit(fetch_single_scene, i, scenes[i], signed_urls[i])
            for i in range(len(scenes))
        ]
        for fut in concurrent.futures.as_completed(futures):
            results.append(fut.result())

    results.sort(key=lambda x: x["idx"])

    # Step 3: Save stacked cubes per AOI to NetCDF (.nc) and metadata CSV/JSON
    for aoi_id, spec in HERO_SPECS.items():
        dates = [r["date"] for r in results]
        x_arr = np.linspace(spec["x_min"], spec["x_max"], spec["nx"], dtype=np.float64)
        y_arr = np.linspace(spec["y_max"], spec["y_min"], spec["ny"], dtype=np.float64)

        # Also compute 1D/2D lon/lat coordinates for convenience
        transformer = pyproj.Transformer.from_crs(f"EPSG:{spec['epsg']}", "EPSG:4326", always_xy=True)
        xx, yy = np.meshgrid(x_arr, y_arr)
        lon_2d, lat_2d = transformer.transform(xx, yy)

        hh_stack = np.stack([r["aoi_data"][aoi_id]["HHHH"] for r in results], axis=0)
        hv_stack = np.stack([r["aoi_data"][aoi_id]["HVHV"] for r in results], axis=0)
        mask_stack = np.stack([r["aoi_data"][aoi_id]["mask"] for r in results], axis=0)
        looks_stack = np.stack([r["aoi_data"][aoi_id]["numberOfLooks"] for r in results], axis=0)

        ds = xr.Dataset(
            data_vars={
                "HHHH": (("time", "y", "x"), hh_stack, {"units": "1 (linear gamma0 power)", "long_name": "RTC Backscatter HHHH"}),
                "HVHV": (("time", "y", "x"), hv_stack, {"units": "1 (linear gamma0 power)", "long_name": "RTC Backscatter HVHV"}),
                "mask": (("time", "y", "x"), mask_stack, {"long_name": "Valid sample / subswath mask"}),
                "numberOfLooks": (("time", "y", "x"), looks_stack, {"long_name": "Adaptive multi-look count"}),
                "lon": (("y", "x"), lon_2d.astype(np.float32), {"units": "degrees_east"}),
                "lat": (("y", "x"), lat_2d.astype(np.float32), {"units": "degrees_north"}),
            },
            coords={
                "time": dates,
                "y": ("y", y_arr, {"units": "m", "standard_name": "projection_y_coordinate"}),
                "x": ("x", x_arr, {"units": "m", "standard_name": "projection_x_coordinate"}),
            },
            attrs={
                "aoi_id": aoi_id,
                "aoi_name": spec["name"],
                "track_key": spec["track_key"],
                "epsg": spec["epsg"],
                "resolution_m": spec["res_m"],
                "collection": "NISAR_L2_GCOV_PROVISIONAL_V1",
                "data_maturity": "PROVISIONAL",
            },
        )
        out_nc = DATA_RAW_DIR / f"{aoi_id}_gcov_raw_cube.nc"
        ds.to_netcdf(out_nc, engine="h5netcdf")
        print(f"Saved stacked raw GCOV cube for {aoi_id} to {out_nc} (shape={hh_stack.shape})", flush=True)

        meta_rows = []
        for r in results:
            ad = r["aoi_data"][aoi_id]
            meta_rows.append({
                "date": r["date"],
                "granule": r["granule"],
                "cycle": r["cycle"],
                "track": r["track"],
                "frame": r["frame"],
                "direction": r["direction"],
                "mode": r["mode"],
                "pol_code": r["pol_code"],
                "crid": r["crid"],
                "maturity": r["maturity"],
                "product_version": r["product_version"],
                "epsg": r["epsg"],
                "inc_angle_mean_deg": round(ad["inc_mean"], 3),
                "inc_angle_min_deg": round(ad["inc_min"], 3),
                "inc_angle_max_deg": round(ad["inc_max"], 3),
                "valid_pixel_fraction": round(float(np.isfinite(ad["HHHH"]).mean()), 5),
                "mean_hh_linear": round(float(np.nanmean(ad["HHHH"])), 5),
                "mean_hv_linear": round(float(np.nanmean(ad["HVHV"])), 5),
            })
        meta_df = pd.DataFrame(meta_rows)
        meta_csv = DATA_RAW_DIR / f"{aoi_id}_metadata.csv"
        meta_df.to_csv(meta_csv, index=False)
        print(f"Saved metadata table to {meta_csv}", flush=True)


if __name__ == "__main__":
    main()
