#!/usr/bin/env python3
"""
Generate publication-grade QA figures for README.md and documentation:
1. jamuna_water_validation.png & haor_water_validation.png
2. jamuna_paddy_diagnostics.png & haor_paddy_diagnostics.png
"""

import json
from pathlib import Path
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from PIL import Image
import numpy as np

BASE_DIR = Path(__file__).resolve().parent.parent
DOCS_QA = BASE_DIR / "docs" / "qa"
WEB_DATA = BASE_DIR / "web" / "data"
WEB_IMAGES = BASE_DIR / "web" / "images"

DOCS_QA.mkdir(parents=True, exist_ok=True)

# Also create root docs/qa directory so GitHub renders cleanly whether relative to root or delta-pulse
ROOT_DOCS_QA = BASE_DIR.parent / "docs" / "qa"
ROOT_DOCS_QA.mkdir(parents=True, exist_ok=True)

def generate_water_validation_figure(aoi_id, aoi_title):
    with open(WEB_DATA / f"{aoi_id}_water_summary.json", "r") as f:
        water_data = json.load(f)
    with open(WEB_DATA / "validation_metrics.json", "r") as f:
        val_data = json.load(f)[aoi_id]["sentinel1_comparison"]

    fig = plt.figure(figsize=(15, 5.2), dpi=150, facecolor="#0a1128")
    
    # Grid layout: 3 subplots
    gs = fig.add_gridspec(1, 3, width_ratios=[1.1, 1.1, 1.3], wspace=0.22)
    
    # 1. NISAR Peak Flood Overlay
    ax1 = fig.add_subplot(gs[0])
    flood_img_path = WEB_IMAGES / "overlays" / aoi_id / "flood_2026-07-24.png"
    if flood_img_path.exists():
        im1 = Image.open(flood_img_path)
        ax1.imshow(im1)
    ax1.set_title(f"NISAR L-Band Flood Dynamics\nPeak Monsoon ({water_data['peak_flood_date']})", color="#e2e8f0", fontsize=10, fontweight="bold", pad=8)
    ax1.axis("off")
    # Sub-caption
    ax1.text(0.5, -0.05, f"Peak Water: {water_data['peak_water_km2']} km² (80m UTM 46N)", transform=ax1.transAxes, color="#38bdf8", ha="center", fontsize=8.5)

    # 2. Sentinel-1 C-Band RTC
    ax2 = fig.add_subplot(gs[1])
    s1_img_path = WEB_IMAGES / "overlays" / aoi_id / "sentinel1_rtc_2026-07-25.png"
    if s1_img_path.exists():
        im2 = Image.open(s1_img_path)
        ax2.imshow(im2)
    ax2.set_title(f"Copernicus Sentinel-1 C-Band RTC\nCross-Validation ({val_data['sentinel1_date']})", color="#e2e8f0", fontsize=10, fontweight="bold", pad=8)
    ax2.axis("off")
    ax2.text(0.5, -0.05, f"S1 Extent: {val_data['s1_open_water_km2']} km² (Time gap: {val_data['time_gap_days']}d)", transform=ax2.transAxes, color="#94a3b8", ha="center", fontsize=8.5)

    # 3. Time Series & Validation Scorecard
    ax3 = fig.add_subplot(gs[2])
    ax3.set_facecolor("#0f172a")
    
    dates = [ts["date"][5:] for ts in water_data["time_series"]]
    total_water = [ts["total_water_km2"] for ts in water_data["time_series"]]
    perm_water = [ts["permanent_wet_km2"] for ts in water_data["time_series"]]
    new_flood = [ts["new_flood_km2"] for ts in water_data["time_series"]]
    
    x = np.arange(len(dates))
    ax3.plot(x, total_water, color="#38bdf8", marker="o", linewidth=2.2, label="Total Water (km²)", zorder=4)
    ax3.plot(x, perm_water, color="#3b82f6", linestyle="--", linewidth=1.5, label="Permanent Baseline")
    ax3.bar(x, new_flood, color="#10b981", alpha=0.35, width=0.55, label="New Flood Wave")
    
    # Mark peak pass
    peak_idx = water_data["dates"].index(water_data["peak_flood_date"])
    ax3.axvline(x=peak_idx, color="#f59e0b", linestyle=":", linewidth=1.8, alpha=0.8, label=f"Peak ({water_data['peak_flood_date'][5:]})")
    
    ax3.set_xticks(x[::2])
    ax3.set_xticklabels(dates[::2], color="#cbd5e1", fontsize=8)
    ax3.tick_params(colors="#cbd5e1", labelsize=8)
    for spine in ax3.spines.values():
        spine.set_color("#334155")
    
    ax3.set_ylabel("Inundated Area (km²)", color="#e2e8f0", fontsize=9)
    ax3.set_title(f"{aoi_title}\n12-Pass Inundation Wave & Validation Scorecard", color="#e2e8f0", fontsize=10, fontweight="bold", pad=8)
    ax3.grid(True, linestyle="--", alpha=0.2, color="#64748b")
    ax3.legend(loc="upper left", facecolor="#1e293b", edgecolor="#334155", labelcolor="#e2e8f0", fontsize=7.5)

    # Validation Scorecard Box inside ax3
    m = val_data["open_water_metrics"]
    scorecard_text = (
        f"Multi-Sensor Validation (NISAR vs S1 RTC):\n"
        f"• Overall Accuracy: {m['overall_accuracy']*100:.1f}%\n"
        f"• Cohen's Kappa (κ): {m['cohens_kappa']:.3f}\n"
        f"• IoU (Jaccard): {m['iou']:.3f}\n"
        f"• Precision / Recall: {m['precision']*100:.1f}% / {m['recall']*100:.1f}%\n"
        f"• Valid Pixels Evaluated: {m['valid_pixels_compared']:,}"
    )
    ax3.text(0.97, 0.05, scorecard_text, transform=ax3.transAxes, color="#f8fafc",
             fontsize=7.8, family="monospace", va="bottom", ha="right",
             bbox=dict(boxstyle="round,pad=0.5", facecolor="#1e293b", edgecolor="#38bdf8", alpha=0.92, lw=1))

    out_file1 = DOCS_QA / f"{aoi_id}_water_validation.png"
    out_file2 = ROOT_DOCS_QA / f"{aoi_id}_water_validation.png"
    fig.savefig(out_file1, bbox_inches="tight", facecolor=fig.get_facecolor(), dpi=150)
    fig.savefig(out_file2, bbox_inches="tight", facecolor=fig.get_facecolor(), dpi=150)
    plt.close(fig)
    print(f"Generated: {out_file1}")


def generate_paddy_diagnostics_figure(aoi_id, aoi_title):
    with open(WEB_DATA / f"{aoi_id}_paddy_summary.json", "r") as f:
        paddy_data = json.load(f)

    fig = plt.figure(figsize=(15, 5.2), dpi=150, facecolor="#0a1128")
    gs = fig.add_gridspec(1, 3, width_ratios=[1.1, 1.25, 1.25], wspace=0.22)

    # 1. Spatial K=4 Paddy Classes Overlay
    ax1 = fig.add_subplot(gs[0])
    paddy_img_path = WEB_IMAGES / "overlays" / aoi_id / "paddy_rhythm_classes.png"
    if paddy_img_path.exists():
        im1 = Image.open(paddy_img_path)
        ax1.imshow(im1)
    ax1.set_title(f"Unsupervised K=4 Crop Clusters\nESA WorldCover Cropland ({paddy_data['total_cropland_km2']:.1f} km²)", color="#e2e8f0", fontsize=10, fontweight="bold", pad=8)
    ax1.axis("off")
    ax1.text(0.5, -0.05, f"142,852 Cropland Pixels ({paddy_data['cropland_fraction_pct']}% of AOI)", transform=ax1.transAxes, color="#10b981", ha="center", fontsize=8.5)

    dates = [d[5:] for d in paddy_data["dates"]]
    x = np.arange(len(dates))

    # 2. Cross-Pol HV Centroid Trajectories
    ax2 = fig.add_subplot(gs[1])
    ax2.set_facecolor("#0f172a")
    for c in paddy_data["clusters"]:
        ax2.plot(x, c["hv_db_series"], color=c["color"], marker="o", markersize=4, linewidth=2, label=f"C{c['class_id']}: {c['name'][:18]}...")
    
    ax2.set_xticks(x[::2])
    ax2.set_xticklabels(dates[::2], color="#cbd5e1", fontsize=8)
    ax2.tick_params(colors="#cbd5e1", labelsize=8)
    for spine in ax2.spines.values():
        spine.set_color("#334155")
    ax2.set_ylabel("Cross-Pol γ⁰ HV (dB)", color="#e2e8f0", fontsize=9)
    ax2.set_title("Cross-Pol γ⁰ HV Trajectories\nCanopy Volume Depolarization (Biomass Growth)", color="#e2e8f0", fontsize=10, fontweight="bold", pad=8)
    ax2.grid(True, linestyle="--", alpha=0.2, color="#64748b")
    ax2.legend(loc="lower right", facecolor="#1e293b", edgecolor="#334155", labelcolor="#e2e8f0", fontsize=7.2)

    # 3. Co-Pol HH Centroid Trajectories
    ax3 = fig.add_subplot(gs[2])
    ax3.set_facecolor("#0f172a")
    for c in paddy_data["clusters"]:
        ax3.plot(x, c["hh_db_series"], color=c["color"], marker="s", markersize=4, linewidth=2, label=f"C{c['class_id']} ({c['share_of_cropland_pct']}%)")
    
    ax3.set_xticks(x[::2])
    ax3.set_xticklabels(dates[::2], color="#cbd5e1", fontsize=8)
    ax3.tick_params(colors="#cbd5e1", labelsize=8)
    for spine in ax3.spines.values():
        spine.set_color("#334155")
    ax3.set_ylabel("Co-Pol γ⁰ HH (dB)", color="#e2e8f0", fontsize=9)
    ax3.set_title("Co-Pol γ⁰ HH Trajectories\nFlooding Dip & Stem-Water Double-Bounce", color="#e2e8f0", fontsize=10, fontweight="bold", pad=8)
    ax3.grid(True, linestyle="--", alpha=0.2, color="#64748b")
    ax3.legend(loc="lower left", facecolor="#1e293b", edgecolor="#334155", labelcolor="#e2e8f0", fontsize=7.2)

    # Note at bottom
    ax3.text(0.97, 0.95, "L-band double-bounce surge: HH > -7.5 dB", transform=ax3.transAxes, color="#f59e0b",
             fontsize=7.8, family="sans-serif", va="top", ha="right",
             bbox=dict(boxstyle="round,pad=0.3", facecolor="#1e293b", edgecolor="#f59e0b", alpha=0.9, lw=0.8))

    out_file1 = DOCS_QA / f"{aoi_id}_paddy_diagnostics.png"
    out_file2 = ROOT_DOCS_QA / f"{aoi_id}_paddy_diagnostics.png"
    fig.savefig(out_file1, bbox_inches="tight", facecolor=fig.get_facecolor(), dpi=150)
    fig.savefig(out_file2, bbox_inches="tight", facecolor=fig.get_facecolor(), dpi=150)
    plt.close(fig)
    print(f"Generated: {out_file1}")


def copy_existing_qa_plots():
    # Also copy existing jamuna/haor qa_histograms_and_drift to root docs/qa
    import shutil
    for fname in ["jamuna_qa_histograms_and_drift.png", "haor_qa_histograms_and_drift.png",
                  "jamuna_qa_cube_overview.png", "haor_qa_cube_overview.png"]:
        src = DOCS_QA / fname
        if src.exists():
            shutil.copy2(src, ROOT_DOCS_QA / fname)
            print(f"Copied {fname} to {ROOT_DOCS_QA}")

if __name__ == "__main__":
    copy_existing_qa_plots()
    generate_water_validation_figure("jamuna", "Brahmaputra–Jamuna Floodplain")
    generate_water_validation_figure("haor", "Sunamganj & Sylhet Haor Basin")
    generate_paddy_diagnostics_figure("jamuna", "Brahmaputra–Jamuna Floodplain")
    generate_paddy_diagnostics_figure("haor", "Sunamganj & Sylhet Haor Basin")
    print("All README QA figures successfully generated!")
