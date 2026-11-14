# Delta Pulse: Scientific Methods & Processing Architecture (`docs/methods.md`)

**NASA Space Apps Challenge 2026**  
**Challenge:** Dancing with the SARs  
**Project:** Delta Pulse — The Breathing Delta  
**Author Region:** Chattogram, Bangladesh  

---

## 1. Physical Principles of Radar Remote Sensing at L-Band

Synthetic Aperture Radar (SAR) is an active microwave instrument that emits pulses and records the backscattered echo in amplitude and phase. Unlike optical instruments that measure passive solar reflectance and are obstructed by monsoon cloud decks, radar penetrates cloud cover, atmospheric water vapor, and precipitation.

### Core Physical Drivers in the Bangladesh Delta:
1. **Specular Scattering (Calm Water):** Open water bodies (the Jamuna River and Haor depression lakes) act as specular reflectors for microwave pulses. The emitted radar pulse reflects away from the antenna into space, yielding low backscatter (typically **$\le -18 \text{ dB}$ to $-24 \text{ dB}$** in HV and **$\le -13 \text{ dB}$** in HH).
2. **Double-Bounce Reflection (Flooded Vegetation):** When floodwaters submerge rice paddies, reeds (*Phragmites karka*), or swamp trees (*Barringtonia acutangula* / *Pongamia pinnata*), the horizontal water surface and vertical crop stems form a dihedral (90°) corner reflector. Radar pulses bounce from water to stem and directly back to the satellite, creating a strong surge in co-polarized backscatter (**$+3 \text{ dB}$ to $+7 \text{ dB}$ surge in HH**). Naive dark-pixel thresholding misses this flooded vegetation; Delta Pulse explicitly separates and tracks both.
3. **Volume Scattering (Paddy Rice Canopy):** As Aman rice transitions from transplanting to vegetative tillering and panicle heading, the random orientation of leaves and stalks causes multiple depolarizing volume bounces, producing a steady **$+4 \text{ dB}$ to $+8 \text{ dB}$ rise in cross-polarization (HV)**.
4. **Fluvial Sediment Transport & Char Emergence:** High monsoon discharge through the Brahmaputra system moves millions of tons of Himalayan sediment. As floodwaters recede in October/November, newly deposited sandbars (*chars*) emerge from the river bed, causing rapid $+5 \text{ dB}$ to $+9 \text{ dB}$ backscatter increases.

---

## 2. Ingestion & Preprocessing Pipeline (`pipeline/01_fetch.py`, `02_preprocess.py`)

1. **Viewing Geometry Normalization:** Scenes are constrained strictly to **Track 069, Frame 014, ASCENDING** (`T069_F014_A`), guaranteeing identical orbital look angle, incidence angle ($\sim 41.0^\circ$), and ground illumination geometry across all 13 passes.
2. **Streaming & Spatial Subsetting:** Byte-range HTTP requests stream chunk-aligned subsets (512x512 pixels at 80 m pixel spacing) directly from NASA Earthdata Cloud via `earthaccess`, `fsspec`, and `h5py`, eliminating multi-gigabyte downloads.
3. **Speckle Suppression in Linear Power:** Multi-look SAR imagery exhibits coherent speckle noise. Delta Pulse applies a NaN-aware $3 \times 3$ Lee adaptive filter in **linear power** ($\gamma^0$) before log conversion, preserving sharp riverbank cut edges while reducing variance over homogeneous water:
   $$W = 1 - \frac{\sigma_u^2}{\sigma_i^2 / \mu^2}$$
4. **Logarithmic Decibel Conversion:**
   $$\gamma^0_{\text{dB}} = 10 \cdot \log_{10}(\gamma^0_{\text{linear}})$$
5. **Radiometric Stability Check:** Verified against persistent high-backscatter urban/built-up target pixels across all 13 dates; standard deviation was $< 0.4 \text{ dB}$, confirming zero sensor calibration drift.

---

## 3. Water Pulse & Flood Classification (`pipeline/03_water.py`)

- **Open Water Thresholding:** Performed via scene-adaptive Otsu thresholding bounded within $[-23.5, -16.0] \text{ dB}$ on HV, cross-verified with HH ($< -12.5 \text{ dB}$).
- **Morphological Cleaning:** $3 \times 3$ binary opening eliminates isolated false-positive pixels; $3 \times 3$ closing fills internal voids within main channels.
- **Dynamic Classification:**
  - *Permanent Water:* Pixels with water recurrence $\ge 75\%$ across all passes.
  - *Newly Flooded Water:* Water on date $T$ that was not water in the baseline/recurrent mask.
  - *Receding Water:* Water present in earlier peak dates that has dried down.
  - *Flooded Vegetation:* Vegetated pixels exhibiting an HH backscatter increase of $\ge +2.5 \text{ dB}$ above baseline with $\Delta\text{HH} > \Delta\text{HV} + 1.0 \text{ dB}$.

---

## 4. Paddy Rhythm Phenology (`pipeline/04_paddy.py`)

1. Agricultural pixels are isolated by excluding permanent water and persistent urban targets.
2. For each pixel, a 26-dimensional multi-temporal feature vector is constructed:
   $$\mathbf{f} = \left[ \mathbf{z}(\text{HV}_{\text{dB}}), \mathbf{z}(\text{HV} - \text{HH}_{\text{dB}}) \right]$$
   where $\mathbf{z}(\cdot)$ is temporal z-score normalization (mean 0, variance 1) to isolate curve shape from static soil variations.
3. Unsupervised Mini-Batch K-Means ($k=4$) identifies distinct cropping signatures:
   - *Cluster 1:* Transplanted Aman Rice (standard monsoon curve, transplanting dip in July, vegetative peak in Sept/Oct).
   - *Cluster 2:* Deepwater / Floating Aman (early inundation, emergent canopy in late monsoon).
   - *Cluster 3:* Intensive Double/Triple Cropping on elevated natural levees.
   - *Cluster 4:* Seasonal Char Silt cultivation and sandbank fallow.

---

## 5. Human Impact Quantification (`pipeline/05_impact.py`)

- Newly flooded binary masks are intersected with WorldPop 100 m UN-adjusted gridded population data and ESA WorldCover cropland masks.
- Recognizing that gridded population datasets are spatial models, Delta Pulse explicitly reports population exposure with **$\pm 15\%$ uncertainty intervals** rather than misleading false precision.
- Impact metrics are aggregated by Upazila and District across Sirajganj, Bogura, Jamalpur, Tangail, Sunamganj, and Netrokona.

---

## 6. Change Radio Sonification Engine (`web/src/app.js`)

Change Radio converts 5 months of active microwave history into music using the browser's native **Web Audio API**:
- **Pitch Frequency:** HV cross-polar backscatter (indicative of biomass volume scattering) maps to a 13-note **pentatonic scale** ($C_3$ to $E_5$, 130 Hz to 659 Hz).
- **Timbre & Filtering:** The cross-polarization ratio ($\text{HH} - \text{HV}$) modulates a low-pass biquad filter ($300 \text{ Hz}$ to $3,000 \text{ Hz}$), adding brightness to rough vegetated terrain and warm softness to silt.
- **Sudden Inundation Cue:** When a pixel's backscatter drops sharply ($\le -5.0 \text{ dB}$) between passes, an auxiliary sub-bass oscillator ($65.4 \text{ Hz}$ / $C_2$ sine wave) triggers a deep pulse, giving acoustic prominence to flood arrivals.
