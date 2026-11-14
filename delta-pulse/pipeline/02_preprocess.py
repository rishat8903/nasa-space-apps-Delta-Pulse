"""
Stage 1 (Part B): Preprocess raw NISAR L2 GCOV cubes, apply speckle filtering in linear power,
convert to dB, and generate QA sanity-check figures and calibration stability metrics.

Steps:
1. Load stacked raw linear gamma-0 cubes (time, y, x) for each Hero AOI (`jamuna`, `haor`).
2. Mask invalid pixels (`<= 0`, `NaN`, or `mask == 0` / `mask == 255`).
3. Apply a 3x3 Lee / normalized-box speckle filter in linear power (preserving edges while
   reducing multi-look radar speckle).
4. Convert filtered linear gamma-0 power to decibels: `10 * log10(linear_filtered)`.
5. Compute HV - HH difference (or HH - HV difference) in dB.
6. Run Stage 1 QA sanity checks:
   - Per-scene backscatter histograms (HH and HV in dB)
   - Calibration stability over top-5% brightest persistent urban/built-up targets across all 13 dates
   - Multi-temporal visual overview plots of the cube
   Save QA figures in `docs/qa/` and processed cubes in `data_raw/{aoi_id}_gcov_processed.nc`.
"""

import json
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.ndimage import uniform_filter
import xarray as xr

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_RAW_DIR = REPO_ROOT / "data_raw"
DOCS_QA_DIR = REPO_ROOT / "docs" / "qa"


def lee_filter_2d(img_linear: np.ndarray, size: int = 3, cu: float = 0.25) -> np.ndarray:
    """
    Apply a 2D Lee adaptive speckle filter on linear power data while ignoring NaNs/zeros.
    First performs a normalized NaN-aware local mean and local variance over a (size x size) window,
    then weights between the local mean and center pixel according to local coefficient of variation.
    """
    valid = np.isfinite(img_linear) & (img_linear > 0)
    data = np.where(valid, img_linear.astype(np.float64), 0.0)
    weights = valid.astype(np.float64)

    mean_w = uniform_filter(weights, size=size, mode="nearest")
    local_sum = uniform_filter(data, size=size, mode="nearest")
    local_sq_sum = uniform_filter(data ** 2, size=size, mode="nearest")

    with np.errstate(divide="ignore", invalid="ignore"):
        local_mean = np.where(mean_w > 0, local_sum / mean_w, np.nan)
        local_var = np.where(mean_w > 0, np.maximum(0.0, (local_sq_sum / mean_w) - (local_mean ** 2)), 0.0)

        # Lee weight W = 1 - (cu^2 / ci^2), bounded to [0, 1]
        ci_sq = local_var / np.maximum(local_mean ** 2, 1e-20)
        cu_sq = cu ** 2
        w = np.clip(1.0 - (cu_sq / np.maximum(ci_sq, cu_sq)), 0.0, 1.0)

        filtered = local_mean + w * (data - local_mean)
        filtered = np.where(valid & (filtered > 0), filtered, np.nan)

    return filtered.astype(np.float32)


def process_aoi(aoi_id: str):
    raw_nc = DATA_RAW_DIR / f"{aoi_id}_gcov_raw_cube.nc"
    meta_csv = DATA_RAW_DIR / f"{aoi_id}_metadata.csv"
    if not raw_nc.exists():
        raise FileNotFoundError(f"Missing {raw_nc}; run 01_fetch.py first.")

    ds = xr.open_dataset(raw_nc, engine="h5netcdf")
    meta_df = pd.read_csv(meta_csv)

    hh_raw = ds["HHHH"].values
    hv_raw = ds["HVHV"].values
    mask_arr = ds["mask"].values
    dates = [str(t) for t in ds["time"].values]
    nt, ny, nx = hh_raw.shape

    hh_db = np.full((nt, ny, nx), np.nan, dtype=np.float32)
    hv_db = np.full((nt, ny, nx), np.nan, dtype=np.float32)

    print(f"Preprocessing {aoi_id} ({nt} scenes, {ny}x{nx} grid)...")
    for t in range(nt):
        valid_mask = (mask_arr[t] > 0) & (mask_arr[t] < 255)
        hh_slice = np.where(valid_mask & (hh_raw[t] > 0) & np.isfinite(hh_raw[t]), hh_raw[t], np.nan)
        hv_slice = np.where(valid_mask & (hv_raw[t] > 0) & np.isfinite(hv_raw[t]), hv_raw[t], np.nan)

        hh_filt = lee_filter_2d(hh_slice, size=3, cu=0.25)
        hv_filt = lee_filter_2d(hv_slice, size=3, cu=0.25)

        with np.errstate(divide="ignore", invalid="ignore"):
            hh_db[t] = 10.0 * np.log10(hh_filt)
            hv_db[t] = 10.0 * np.log10(hv_filt)

    hv_minus_hh_db = hv_db - hh_db
    hh_minus_hv_db = hh_db - hv_db

    # Identify stable reference targets (persistent high-backscatter built-up/settlement pixels:
    # temporal minimum HH > -6.5 dB and temporal std < 1.2 dB across all 13 dates)
    hh_min_t = np.nanmin(hh_db, axis=0)
    hh_std_t = np.nanstd(hh_db, axis=0)
    stable_ref_mask = (hh_min_t > -6.5) & (hh_std_t < 1.5)
    if np.sum(stable_ref_mask) < 50:
        # Fallback to top 2% brightest minimum HH pixels
        thresh = np.nanpercentile(hh_min_t, 98.0)
        stable_ref_mask = hh_min_t >= thresh

    ref_hh_series = [float(np.nanmean(hh_db[t][stable_ref_mask])) for t in range(nt)]
    ref_hv_series = [float(np.nanmean(hv_db[t][stable_ref_mask])) for t in range(nt)]
    scene_hh_mean = [float(np.nanmean(hh_db[t])) for t in range(nt)]
    scene_hv_mean = [float(np.nanmean(hv_db[t])) for t in range(nt)]

    meta_df["mean_hh_db"] = np.round(scene_hh_mean, 3)
    meta_df["mean_hv_db"] = np.round(scene_hv_mean, 3)
    meta_df["stable_ref_hh_db"] = np.round(ref_hh_series, 3)
    meta_df["stable_ref_hv_db"] = np.round(ref_hv_series, 3)
    meta_df.to_csv(meta_csv, index=False)

    drift_hh_std = float(np.std(ref_hh_series))
    drift_hv_std = float(np.std(ref_hv_series))
    print(
        f"  -> {aoi_id}: Stable reference pixels={int(np.sum(stable_ref_mask))} | HH stability std={drift_hh_std:.3f} dB | HV stability std={drift_hv_std:.3f} dB"
    )

    # Save processed NetCDF cube
    ds_out = ds.copy()
    ds_out["HH_dB"] = (("time", "y", "x"), hh_db, {"units": "dB", "long_name": "Filtered Gamma0 HH Backscatter (dB)"})
    ds_out["HV_dB"] = (("time", "y", "x"), hv_db, {"units": "dB", "long_name": "Filtered Gamma0 HV Backscatter (dB)"})
    ds_out["HV_minus_HH_dB"] = (("time", "y", "x"), hv_minus_hh_db, {"units": "dB", "long_name": "HV - HH Difference (dB)"})
    ds_out["HH_minus_HV_dB"] = (("time", "y", "x"), hh_minus_hv_db, {"units": "dB", "long_name": "HH - HV Difference (dB)"})
    ds_out["stable_ref_mask"] = (("y", "x"), stable_ref_mask.astype(np.uint8), {"long_name": "Stable built-up reference target mask"})

    proc_nc = DATA_RAW_DIR / f"{aoi_id}_gcov_processed.nc"
    ds_out.to_netcdf(proc_nc, engine="h5netcdf")
    print(f"  -> Saved processed dB cube to {proc_nc}")

    # Generate QA figures in docs/qa/
    DOCS_QA_DIR.mkdir(parents=True, exist_ok=True)

    # Figure 1: Histograms per scene + Calibration stability over stable targets
    fig, axes = plt.subplots(1, 3, figsize=(16, 4.8), dpi=140)
    fig.patch.set_facecolor("#0b1622")
    for ax in axes:
        ax.set_facecolor("#112233")
        ax.tick_params(colors="#cbd5e1")
        for spine in ax.spines.values():
            spine.set_color("#334155")

    cmap = plt.cm.viridis(np.linspace(0, 1, nt))
    bins_hh = np.linspace(-26, 2, 110)
    bins_hv = np.linspace(-32, -6, 110)

    for t in range(nt):
        valid_hh = hh_db[t][np.isfinite(hh_db[t])]
        valid_hv = hv_db[t][np.isfinite(hv_db[t])]
        hist_hh, _ = np.histogram(valid_hh, bins=bins_hh, density=True)
        hist_hv, _ = np.histogram(valid_hv, bins=bins_hv, density=True)
        axes[0].plot(0.5 * (bins_hh[:-1] + bins_hh[1:]), hist_hh, color=cmap[t], alpha=0.8, lw=1.2, label=dates[t] if t in (0, nt//2, nt-1) else None)
        axes[1].plot(0.5 * (bins_hv[:-1] + bins_hv[1:]), hist_hv, color=cmap[t], alpha=0.8, lw=1.2, label=dates[t] if t in (0, nt//2, nt-1) else None)

    axes[0].set_title(f"{aoi_id.upper()}: HH Backscatter Histograms (13 Passes)", color="#f8fafc", fontsize=11)
    axes[0].set_xlabel("HH Gamma-0 (dB)", color="#cbd5e1")
    axes[0].set_ylabel("Density", color="#cbd5e1")
    axes[0].legend(facecolor="#0b1622", edgecolor="#334155", labelcolor="#f8fafc", fontsize=8)

    axes[1].set_title(f"{aoi_id.upper()}: HV Backscatter Histograms ({nt} Passes)", color="#f8fafc", fontsize=11)
    axes[1].set_xlabel("HV Gamma-0 (dB)", color="#cbd5e1")
    axes[1].legend(facecolor="#0b1622", edgecolor="#334155", labelcolor="#f8fafc", fontsize=8)

    x_idx = np.arange(nt)
    axes[2].plot(x_idx, ref_hh_series, "o-", color="#f59e0b", lw=2, label=f"Stable Built-up HH (std={drift_hh_std:.2f} dB)")
    axes[2].plot(x_idx, ref_hv_series, "s-", color="#38bdf8", lw=2, label=f"Stable Built-up HV (std={drift_hv_std:.2f} dB)")
    axes[2].plot(x_idx, scene_hh_mean, "--", color="#fbbf24", alpha=0.6, label="AOI Mean HH")
    axes[2].plot(x_idx, scene_hv_mean, "--", color="#7dd3fc", alpha=0.6, label="AOI Mean HV")
    axes[2].set_xticks(x_idx)
    axes[2].set_xticklabels([d[5:] for d in dates], rotation=45, fontsize=8)
    axes[2].set_title("Radiometric Calibration Stability Check", color="#f8fafc", fontsize=11)
    axes[2].set_ylabel("Backscatter (dB)", color="#cbd5e1")
    axes[2].legend(facecolor="#0b1622", edgecolor="#334155", labelcolor="#f8fafc", fontsize=8)
    axes[2].grid(True, color="#1e293b", ls=":")

    plt.tight_layout()
    qa_hist_path = DOCS_QA_DIR / f"{aoi_id}_qa_histograms_and_drift.png"
    plt.savefig(qa_hist_path, dpi=140, facecolor=fig.get_facecolor())
    plt.close(fig)

    # Figure 2: 4-date visual cube comparison (Early Monsoon, Peak Flood, Late Monsoon, Post-Monsoon Recession)
    sample_indices = [0, 3, 7, nt - 1]
    fig2, axes2 = plt.subplots(2, 4, figsize=(16, 8), dpi=130)
    fig2.patch.set_facecolor("#0b1622")
    for col, tidx in enumerate(sample_indices):
        im_hh = axes2[0, col].imshow(hh_db[tidx], cmap="magma", vmin=-22, vmax=-3)
        axes2[0, col].set_title(f"HH dB — {dates[tidx]}", color="#f8fafc", fontsize=10)
        axes2[0, col].axis("off")

        im_hv = axes2[1, col].imshow(hv_db[tidx], cmap="viridis", vmin=-28, vmax=-10)
        axes2[1, col].set_title(f"HV dB — {dates[tidx]}", color="#f8fafc", fontsize=10)
        axes2[1, col].axis("off")

    plt.tight_layout()
    qa_cube_path = DOCS_QA_DIR / f"{aoi_id}_qa_cube_overview.png"
    plt.savefig(qa_cube_path, dpi=130, facecolor=fig2.get_facecolor())
    plt.close(fig2)
    print(f"  -> Saved QA plots to {qa_hist_path} and {qa_cube_path}")


def main():
    for aoi_id in ["jamuna", "haor"]:
        process_aoi(aoi_id)


if __name__ == "__main__":
    main()
