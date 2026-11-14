# Stage 5: Cross-Sensor Validation Report (`docs/validation_report.md`)

**Generated:** 2026-11-14 (100% Real Satellite Cross-Comparison)

## 1. Peak Monsoon SAR Validation: NISAR L-Band (`2026-07-24`) vs. Sentinel-1 C-Band (`OPERA_L2_RTC-S1_V1`, `2026-07-25`)

| Hero Study Area | NISAR Date | Sentinel-1 Date | S1 Bursts Mosaicked | Open Water IoU | Cohen's Kappa | Precision | Recall | Overall Accuracy |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Brahmaputra-Jamuna Floodplain & Char Lands** | `2026-07-24` | `2026-07-25` | 1 bursts | **0.697** | **0.771** | 76.6% | 88.4% | 92.2% |
| **Sunamganj & Sylhet Haor Basin Wetlands** | `2026-07-24` | `2026-07-25` | 2 bursts | **0.851** | **0.758** | 87.5% | 96.9% | 89.2% |

## 2. Post-Monsoon Optical Validation: NISAR L-Band (`2026-11-09`) vs. Sentinel-2 L2A Optical NDWI/MNDWI

| Hero Study Area | NISAR Date | Sentinel-2 Date | Sentinel-2 L2A Tile(s) | Optical Water IoU | Cohen's Kappa | Precision | Recall | Overall Accuracy |
| :--- | :---: | :---: | :--- | :---: | :---: | :---: | :---: | :---: |
| **Brahmaputra-Jamuna Floodplain & Char Lands** | `2026-11-09` | `2026-11-09` | `S2B_MSIL2A_20261109T044009_R033_T45RYH_20261109T082003` | **0.322** | **0.433** | 40.4% | 61.1% | 89.8% |
| **Sunamganj & Sylhet Haor Basin Wetlands** | `2026-11-09` | `2026-11-13` | `S2C_46RBN_20261111_0_L2A, S2B_46RBN_20261106_0_L2A, S2A_46RBN_20261113_0_L2A, S2A_46RCN_20261113_1_L2A` | **0.689** | **0.659** | 73.0% | 92.5% | 82.8% |

## 3. Physical Explanation of Disagreements & Known Limits

- **Wavelength & Wind-Roughened Water (24 cm L-Band vs. 5.6 cm C-Band):** During the July 24–25 monsoon peak, strong southwesterly winds across the 10-km-wide Jamuna channel and open Sunamganj haors create centimeter-scale Bragg capillary waves that elevate C-band (`VV`/`VH`) backscatter, causing C-band thresholding to miss wind-roughened water pockets that remain dark at L-band (24 cm).
- **Flooded Vegetation & Submerged Paddy:** NISAR L-band penetrates emergent Aman rice and wetland reeds, flagging submerged vegetation via strong `HH` double-bounce enhancement, whereas C-band scatters in the upper leaf layer and optical NDWI is obstructed where emergent green canopy covers standing water.
- **Dry Bare Sandbars (Chars) at L-Band:** Fine, smooth, dry quartz sandbars in the braided Jamuna can exhibit low L-band surface roughness (-16 to -18 dB), creating minor commission along sandbar margins relative to Sentinel-2 optical MNDWI.
- **Speckle Filter & PROVISIONAL Maturity:** Both sensors were evaluated on the common 80 m UTM Zone 46N grid after 3x3 spatial filtering. All NISAR scenes are calibrated `PROVISIONAL` products (`CRID` `P05023` / `P05036`).
