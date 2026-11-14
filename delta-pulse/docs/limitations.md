# Project Limitations & Future Scope (`docs/limitations.md`)

**Project:** Delta Pulse — NASA Space Apps Challenge 2026  
**Challenge:** Dancing with the SARs  

---

## 1. Honest Scientific & Observational Limitations (Hard Rule #4)

### Data Maturity & Calibration
- **Provisional Calibrated Data Span:** The quantitative time-series analysis utilizes 13 scenes from **June 18, 2026 to November 09, 2026** from collection `NISAR_L2_GCOV_PROVISIONAL_V1` on Track 069 Frame 014 Ascending. While these scenes feature calibrated radiometric terrain correction ($\gamma^0$), they represent Provisional science data (CRID `P05023` / `P05036`) subject to ongoing post-launch calibration refinements by NASA and ISRO.
- **BETA Collection (Winter 2025 – Early 2026):** Pre-calibration BETA scenes (CRID `X05009` / `X05010`) covering the winter Boro rice planting season exist along the western Bangladesh border, but are strictly excluded from quantitative comparisons with Provisional data to prevent false drift artifacts.

### Radar Physics & Resolution Limits
- **Wind-Induced Surface Roughness:** While L-band (24 cm wavelength) is significantly more resilient to capillary ripples than C-band (5.6 cm), violent monsoon gale gusts (>25 knots) over wide Jamuna channels (4–10 km across) can induce decimeter-scale gravity-capillary waves that slightly elevate water backscatter by +2 to +4 dB, momentarily blurring the open water threshold.
- **Double-Bounce Classification without In-Situ Validation:** The flooded vegetation classification algorithm relies on the dihedral corner reflector model (+2.5 to +7.0 dB HH surge). While physically grounded, no ground-truth drone or field survey was conducted during active flood crests; therefore, this layer is explicitly designated as **experimental hypothesis**.
- **Spatial Resolution Trade-off:** Analysis is performed at 80 m pixel spacing (Frequency B, 5 MHz bandwidth) to enable rapid streaming and responsive web performance across 41 km $\times$ 41 km study areas. Sub-pixel features such as narrow village irrigation ditches, household homestead ponds, and raised mud paths (*ails*) are integrated into mixed-pixel responses.

### Ancillary Dataset Uncertainty
- **WorldPop Spatial Disaggregation:** WorldPop population grids are dasymetric statistical models constrained by settlement footprints. Delta Pulse reports all flood-exposed population numbers with **$\pm 15\%$ uncertainty bounds** rather than unjustified single-digit precision.

---

## 2. Future Scope & Next Milestones

1. **Full-Year InSAR Coherence & Dry-Season Boro Tracking:** Once NASA and ISRO complete the full reprocessing campaign, expand time series to a 365-day cycle to map the complete dry-season Boro rice harvest and pre-monsoon flash floods.
2. **InSAR Subsidence Mapping for Megacities (Dhaka & Chattogram):** Utilize NISAR Level 2 GSLC (Geocoded Single Look Complex) products and GUNW interferograms to measure millimeter-scale land subsidence from groundwater extraction in Dhaka and coastal sediment compaction in Chattogram.
3. **Slope Stability & Landslide Early Warning in Chittagong Hill Tracts:** Leverage L-band SAR backscatter decorrelation and moisture shifts to detect rain-triggered hill-slope failures along the Chattogram-Cox's Bazar transport corridor.
4. **Bangla Language Localization:** Add full bilingual interface support (English / বাংলা) so local agricultural extension officers (*Upazila Krishi Officers*) and disaster management committees can use Delta Pulse directly during monsoon emergencies.
5. **Real-Time Automated Ingestion Hook:** Deploy an AWS Lambda / Cloud Function triggered by CMR granule release events to automatically stream and render new NISAR acquisitions within hours of downlink.
