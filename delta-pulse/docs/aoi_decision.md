# AOI Coverage Analysis & Hero Study Area Decision (`docs/aoi_decision.md`)

**Generated:** 2026-11-13 (Stage 0 Coverage Check via `pipeline/00_coverage.py`)  
**Data Source:** NASA ASF DAAC Search API (`dataset=NISAR`, `processingLevel=GCOV`)  
**Collection:** `NISAR_L2_GCOV_PROVISIONAL_V1` (Calibrated Provisional products from 2026-06-17 onward) and `NISAR_L2_UR_GCOV` (Urgent Response calibrated products). `QA_STATS` side files excluded.

---

## 1. Candidate Study Areas Evaluated in Bangladesh

Following the priority order in the project specification, we queried ASF DAAC for all NISAR L-band Level 2 Geocoded Polarimetric Covariance (`GCOV`) scenes intersecting four candidate areas in Bangladesh:

1. **Candidate 1 (Priority 1): Brahmaputra–Jamuna Floodplain & Char Lands (Sirajganj / Bogura / Jamalpur)**
   - **Bounding Box:** `[89.55°E, 24.15°N, 89.90°E, 24.95°N]`
   - **Physical Drivers:** Monsoon river discharge from the Himalayan/Tibetan catchment, braided river channel migration, emergent/submergent sandbars (*chars*), and deepwater/transplanted Aman paddy.
2. **Candidate 2 (Priority 2): Haor Basin (Sylhet & Sunamganj Tectonic Wetlands)**
   - **Bounding Box:** `[90.95°E, 24.55°N, 91.55°E, 25.10°N]`
   - **Physical Drivers:** Flash floods from the Meghalaya hills (Cherrapunji/Mawsynram runoff) filling bowl-shaped tectonic depressions (*haors*) into a vast inland sea from June to October, followed by drainage in November for Boro rice cultivation.
3. **Candidate 3 (Priority 3): Chattogram Coastal Belt & Karnaphuli/Halda Estuary**
   - **Bounding Box:** `[91.65°E, 22.15°N, 92.05°E, 22.65°N]`
   - **Physical Drivers:** Author's hometown region; coastal tidal flats, estuarine flooding, hill-torrent runoff, and cyclone surge exposure.
4. **Candidate 4 (Priority 4): Sundarbans Mangrove Edge & Khulna Polders**
   - **Bounding Box:** `[89.15°E, 22.00°N, 89.65°E, 22.55°N]`
   - **Physical Drivers:** Mangrove forest double-bounce signatures, tidal polder waterlogging, and aquaculture/shrimp *ghers*.

---

## 2. Real ASF NISAR GCOV Scene Counts per Track, Frame & Direction

To ensure constant viewing geometry (incidence angle and look direction) for valid quantitative change detection, all scenes were grouped by **Track (`relativeOrbit`)**, **Frame (`frameNumber`)**, and **Flight Direction (`ASCENDING` / `DESCENDING`)**.

### Summary Table Across All Candidate AOIs

| Candidate AOI | Track / Frame / Dir | Total Scenes | PROVISIONAL (>= 2026-06-17) | Dual-Pol `HH+HV` (`DHDH`/`QPDH`) | BETA (< 2026-06-17) | Bandwidth Mode | Date Range (2026) | Full Coverage of AOI? |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **1. Brahmaputra–Jamuna** | **`T069_F014_A` (Asc)** | **13** | **13** | **13 (100%)** | 0 | `4005` (10 m) | `2026-06-18` to `2026-11-09` | **Yes (100%)** |
| 1. Brahmaputra–Jamuna | `T019_F076_D` (Desc) | 20* | 20* | 20* | 0 | `2005`/`4005` | `2026-06-27` to `2026-11-06` | Yes (Mixed sub-modes) |
| 1. Brahmaputra–Jamuna | `T091_F076_D` (Desc) | 13 | 13 | 13 | 0 | `2005`/`4005` | `2026-06-20` to `2026-11-11` | Partial (Eastern edge) |
| 1. Brahmaputra–Jamuna | `T170_F014_A` (Asc) | 14 | 14 | 14 | 0 | `4005` | `2026-06-25` to `2026-11-04` | Partial (Western edge) |
| **2. Haor Basin (Sylhet)** | **`T091_F076_D` (Desc)** | **13** | **13** | **13 (100%)** | 0 | `2005`/`4005` | `2026-06-20` to `2026-11-11` | **Yes (100%)** |
| **2. Haor Basin (Sylhet)** | **`T069_F014_A` (Asc)** | **13** | **13** | **13 (100%)** | 0 | `4005` (10 m) | `2026-06-18` to `2026-11-09` | **Yes (Western/Central)** |
| 2. Haor Basin (Sylhet) | `T141_F014_A` (Asc) | 12 | 12 | 12 | 0 | `4005` (10 m) | `2026-06-23` to `2026-11-02` | Yes (Eastern Sylhet) |
| **3. Chattogram Coastal** | **`T069_F013_A` (Asc)** | **13** | **13** | **13 (100%)** | 0 | `4005` (10 m) | `2026-06-18` to `2026-11-09` | **Yes (100%)** |
| 3. Chattogram Coastal | `T163_F077_D` (Desc) | 15 | 15 | 15 | 0 | `2005`/`4005` | `2026-06-25` to `2026-11-04` | Partial (Eastern hills) |
| 3. Chattogram Coastal | `T091_F077_D` (Desc) | 26* | 26* | 19 | 0 | Mixed | `2026-06-20` to `2026-11-11` | Partial (Western coast) |
| 4. Sundarbans Edge | `T170_F013_A` (Asc) | 15 | 15 | 15 | 0 | `4005` | `2026-06-25` to `2026-11-04` | Yes |
| 4. Sundarbans Edge | `T019_F077_D` (Desc) | 13 | 13 | 13 | 0 | `2005`/`4005` | `2026-06-27` to `2026-11-06` | Yes |

*\*Note: Tracks with >13 scenes between June 17 and Nov 11 have split sub-frames or mode switches (e.g., `2005` QPDH and `4005` DHDH) on the same date.*

### Detailed Acquisition Dates for Primary Selected Tracks

#### Track `069`, Frame `014`, Ascending (`T069_F014_A`) — Covers BOTH AOI 1 (Brahmaputra–Jamuna) and Western AOI 2 (Sunamganj Haor Basin)
All **13 scenes** are calibrated `PROVISIONAL` (`CRID` `P05023` / `P05030` / `P05036`), dual-pol `DHDH` (`HHHH` + `HVHV`), mode `4005` (40 MHz Frequency A at 10 m spacing + 5 MHz Frequency B at 80 m spacing), every 12 days:
1. `2026-06-18` (Cycle 023) — `NISAR_L2_PR_GCOV_023_069_A_014_4005_DHDH_A_20260618T232135_20260618T232210_P05023_N_F_J_001`
2. `2026-06-30` (Cycle 024) — `NISAR_L2_PR_GCOV_024_069_A_014_4005_DHDH_A_20260630T232136_20260630T232210_P05023_N_F_J_001`
3. `2026-07-12` (Cycle 025) — `NISAR_L2_PR_GCOV_025_069_A_014_4005_DHDH_A_20260712T232137_20260712T232211_P05023_N_F_J_001`
4. `2026-07-24` (Cycle 026) — `NISAR_L2_PR_GCOV_026_069_A_014_4005_DHDH_A_20260724T232136_20260724T232211_P05023_N_F_J_001`
5. `2026-08-05` (Cycle 027) — `NISAR_L2_PR_GCOV_027_069_A_014_4005_DHDH_A_20260805T232137_20260805T232211_P05023_N_F_J_001`
6. `2026-08-17` (Cycle 028) — `NISAR_L2_PR_GCOV_028_069_A_014_4005_DHDH_A_20260817T232136_20260817T232210_P05030_N_F_J_001`
7. `2026-08-29` (Cycle 029) — `NISAR_L2_PR_GCOV_029_069_A_014_4005_DHDH_A_20260829T232135_20260829T232210_P05030_N_F_J_001`
8. `2026-09-10` (Cycle 030) — `NISAR_L2_PR_GCOV_030_069_A_014_4005_DHDH_A_20260910T232135_20260910T232209_P05030_N_F_J_001`
9. `2026-09-22` (Cycle 031) — `NISAR_L2_PR_GCOV_031_069_A_014_4005_DHDH_A_20260922T232133_20260922T232208_P05030_N_F_J_001`
10. `2026-10-04` (Cycle 032) — `NISAR_L2_PR_GCOV_032_069_A_014_4005_DHDH_A_20261004T232133_20261004T232208_P05030_N_F_J_001`
11. `2026-10-16` (Cycle 033) — `NISAR_L2_PR_GCOV_033_069_A_014_4005_DHDH_A_20261016T232133_20261016T232208_P05030_N_F_J_001`
12. `2026-10-28` (Cycle 034) — `NISAR_L2_PR_GCOV_034_069_A_014_4005_DHDH_A_20261028T232133_20261028T232207_P05036_N_F_J_001`
13. `2026-11-09` (Cycle 035) — `NISAR_L2_UR_GCOV_035_069_A_014_4005_DHDH_A_20261109T232132_20261109T232207_P05036_F_F_J_001`

#### Track `091`, Frame `076`, Descending (`T091_F076_D`) — Covers Full Haor Basin (Sylhet & Sunamganj)
**13 calibrated PROVISIONAL passes** every 12 days from `2026-06-20` to `2026-11-11` (`2026-06-20`, `07-02`, `07-14`, `07-26`, `08-07`, `08-19`, `08-31`, `09-12`, `09-24`, `10-06`, `10-18`, `10-30`, `11-11`), all with `HH` and `HV` polarizations.

#### Track `069`, Frame `013`, Ascending (`T069_F013_A`) — Covers Chattogram Coastal Belt & Karnaphuli/Halda Estuary
**13 calibrated PROVISIONAL passes** every 12 days on the exact same dates as `T069_F014_A` (`2026-06-18` to `2026-11-09`), all `4005` `DHDH` (`HH` + `HV`).

---

## 3. Note on BETA Collection (`NISAR_L2_GCOV_BETA_V1`) Over Bangladesh

We also queried ASF across all of Bangladesh (`88.0°E–92.7°E, 20.5°N–26.7°N`) prior to June 17, 2026:
- **33 granules** exist prior to `2026-06-17` along the western border of Bangladesh (`Track 098 Frame 012/013` and `Track 120 Frame 075/076/077`, covering western Kushtia/Rajshahi/Satkhira border) from `2025-11-28` to `2026-01-17` (`CRID` `X05009` / `X05010`, pre-calibration BETA).
- However, over the central/eastern hero areas (Jamuna, Haor, Chattogram), **100% of available acquisitions are calibrated PROVISIONAL scenes starting June 18, 2026**, with an uninterrupted 13-pass 12-day repeat series through November 11, 2026.
- Per Hard Rule #3, we do **not** mix pre-calibration BETA scenes with calibrated PROVISIONAL scenes in quantitative time series, and we clearly label every scene's data maturity (`PROVISIONAL`, CRID `P05023`/`P05030`/`P05036`) in the UI.

---

## 4. Final AOI Decision

Based on the coverage evidence above, we select **three Hero Study Areas** in Bangladesh:

1. **Hero AOI 1 (Primary): Brahmaputra–Jamuna Floodplain & Char Lands (`jamuna`)**
   - **Track / Frame / Direction:** `Track 069, Frame 014, ASCENDING` (`T069_F014_A`)
   - **Scene Count:** 13 calibrated `PROVISIONAL` dual-pol (`HH`, `HV`) scenes (`2026-06-18` to `2026-11-09`, 100% uniform `4005` mode).
   - **Focus:** Monsoon flood wave, braided channel shifts, char emergence/submergence, and floodplain Aman paddy rhythm.
2. **Hero AOI 2 (Primary): Haor Basin Wetlands — Sunamganj & Sylhet (`haor`)**
   - **Track / Frame / Direction:** `Track 069, Frame 014, ASCENDING` (`T069_F014_A` — Western/Central Sunamganj Haors: Tanguar, Shanir, Matian, Dekhar Haor) & `Track 091, Frame 076, DESCENDING` (`T091_F076_D` — Hakaluki & Eastern Sylhet Haors), 13 calibrated `PROVISIONAL` scenes each.
   - **Focus:** Dramatic seasonal inland-sea wetland inundation during monsoon peak (July–August) and post-monsoon recession (October–November) revealing haor beds and Boro rice fields.
3. **Hero AOI 3 (Local Context): Chattogram Coastal Belt & Halda–Karnaphuli Estuary (`chattogram_coastal`)**
   - **Track / Frame / Direction:** `Track 069, Frame 013, ASCENDING` (`T069_F013_A`), 13 calibrated `PROVISIONAL` scenes (`2026-06-18` to `2026-11-09`).
   - **Focus:** Author's hometown region — estuarine flood pulse, coastal polders, and tidal/monsoon drainage dynamics.
