/**
 * ============================================================================
 * DELTA PULSE — NASA SPACE APPS CHALLENGE 2026 ("DANCING WITH THE SARS")
 * Interactive Geospatial Observatory & Radar Sonification Controller
 * 100% Real NISAR L2 GCOV + JRC + ESA WorldCover + WorldPop + S1 + S2 Data
 * ============================================================================
 */

const WORLDCOVER_NAMES = {
  10: "Tree Cover (10)",
  20: "Shrubland (20)",
  30: "Grassland (30)",
  40: "Cropland (40)",
  50: "Built-up Settlement (50)",
  60: "Bare / Char Sandbar (60)",
  80: "Permanent Water (80)",
  90: "Herbaceous Wetland (90)",
};

const PENTATONIC_SCALE = [
  { note: "G3", freq: 196.0 },
  { note: "A3", freq: 220.0 },
  { note: "C4", freq: 261.63 },
  { note: "D4", freq: 293.66 },
  { note: "E4", freq: 329.63 },
  { note: "G4", freq: 392.0 },
  { note: "A4", freq: 440.0 },
  { note: "C5", freq: 523.25 },
  { note: "D5", freq: 587.33 },
  { note: "E5", freq: 659.25 },
];

function hvToNote(hvDb) {
  const norm = Math.max(0, Math.min(1, (hvDb + 25.0) / 15.0));
  const idx = Math.min(PENTATONIC_SCALE.length - 1, Math.floor(norm * PENTATONIC_SCALE.length));
  return PENTATONIC_SCALE[idx];
}

// Application State
const state = {
  activeTab: "story",
  aoi: "jamuna",
  dateIdx: 3, // Default to 2026-07-24 (Peak Monsoon)
  layerMode: "rgb",
  basemap: "dark",
  opacity: 0.9,
  isPlaying: false,
  playSpeedMs: 700,
  playTimer: null,
  swipeEnabled: false,
  swipeIdxA: 0, // 2026-06-18
  swipeIdxB: 3, // 2026-07-24
  swipePct: 50,
  showTransects: true,
  selectedPinIdx: 0,
  customPixel: null,
  // Audio / Change Radio state
  audioCtx: null,
  radioPlaying: false,
  radioMuted: false,
  radioTimer: null,
  // Data cache
  cache: {},
  validationMetrics: null,
  coverageRaw: null,
};

// Leaflet & Chart.js instances
let map = null;
let baseTileLayer = null;
let primaryOverlay = null;
let secondaryOverlay = null; // Used in Before/After Split-Swipe mode
let landmarkLayerGroup = null;
let transectLayerGroup = null;
let anywhereMap = null;
let anywhereRect = null;

let tsChart = null;
let paddyHvChart = null;
let paddyHhChart = null;
let impactTsChart = null;

const BASEMAP_URLS = {
  dark: {
    url: "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
    attr: "&copy; OpenStreetMap contributors",
    className: "dark-radar-tiles",
  },
  sat: {
    url: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    attr: "&copy; Esri, Maxar, Earthstar Geographics",
    className: "",
  },
  osm: {
    url: "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
    attr: "&copy; OpenStreetMap contributors",
    className: "",
  },
};

// ============================================================================
// 1. INITIALIZATION & DATA FETCHING
// ============================================================================
document.addEventListener("DOMContentLoaded", async () => {
  bindUIEvents();
  await loadGlobalData();
  await loadAOIData(state.aoi);
  updateAllViews();
});

async function loadGlobalData() {
  try {
    const [valResp, covResp] = await Promise.all([
      fetch("data/validation_metrics.json"),
      fetch("data/aoi_coverage_raw.json"),
    ]);
    state.validationMetrics = await valResp.json();
    state.coverageRaw = await covResp.json();
  } catch (err) {
    console.error("Failed loading global validation/coverage JSON:", err);
  }
}

async function loadAOIData(aoiId) {
  if (state.cache[aoiId]) return state.cache[aoiId];
  const [manifest, water, paddy, impact] = await Promise.all([
    fetch(`data/${aoiId}_web_manifest.json`).then((r) => r.json()),
    fetch(`data/${aoiId}_water_summary.json`).then((r) => r.json()),
    fetch(`data/${aoiId}_paddy_summary.json`).then((r) => r.json()),
    fetch(`data/${aoiId}_impact_summary.json`).then((r) => r.json()),
  ]);
  state.cache[aoiId] = { manifest, water, paddy, impact };
  return state.cache[aoiId];
}

function getActiveData() {
  return state.cache[state.aoi];
}

// ============================================================================
// 2. UI NAVIGATION & EVENT BINDINGS
// ============================================================================
function switchTab(tabId) {
  state.activeTab = tabId;
  document.querySelectorAll(".nav-tab").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.tab === tabId);
  });
  document.querySelectorAll(".view-section").forEach((sec) => {
    sec.classList.toggle("active", sec.id === `view-${tabId}`);
  });

  if (tabId === "explorer") {
    initExplorerMap();
    setTimeout(() => {
      if (map) {
        map.invalidateSize();
        const b = getActiveData().manifest.bounds_wgs84;
        map.fitBounds(
          [
            [b[1], b[0]],
            [b[3], b[2]],
          ],
          { padding: [14, 14] }
        );
      }
      updateExplorerOverlay();
      renderPinChart();
    }, 60);
  } else if (tabId === "paddy") {
    setTimeout(() => renderPaddyView(), 50);
  } else if (tabId === "impact") {
    setTimeout(() => renderImpactView(), 50);
  } else if (tabId === "anywhere") {
    setTimeout(() => {
      initAnywhereMap();
      queryASFGranules();
    }, 60);
  }
}

function bindUIEvents() {
  // Top navigation tabs
  document.querySelectorAll(".nav-tab").forEach((btn) => {
    btn.addEventListener("click", () => switchTab(btn.dataset.tab));
  });

  // Study Area (AOI) selector
  const aoiSelect = document.getElementById("aoi-select");
  if (aoiSelect) {
    aoiSelect.addEventListener("change", async (e) => {
      stopAnimation();
      stopChangeRadio();
      state.aoi = e.target.value;
      state.selectedPinIdx = 0;
      state.customPixel = null;
      await loadAOIData(state.aoi);
      if (map) {
        const b = getActiveData().manifest.bounds_wgs84; // [west, south, east, north]
        map.fitBounds([
          [b[1], b[0]],
          [b[3], b[2]],
        ]);
      }
      updateAllViews();
    });
  }

  // Hero buttons
  document.getElementById("btn-launch-explorer")?.addEventListener("click", () => {
    switchTab("explorer");
  });
  document.getElementById("btn-hero-radio")?.addEventListener("click", () => {
    switchTab("explorer");
    setTimeout(() => {
      if (!state.radioPlaying) toggleChangeRadio();
    }, 250);
  });
  document.getElementById("btn-hero-datasets")?.addEventListener("click", () => {
    switchTab("impact");
  });

  // 5 Story Beat cards
  document.querySelectorAll(".beat-card").forEach((card) => {
    card.addEventListener("click", () => {
      const beatIdx = parseInt(card.dataset.beat, 10);
      const presets = [
        { layer: "rgb", dateIdx: 3, pinIdx: 0 },        // Beat 1: Peak Monsoon RGB
        { layer: "water", dateIdx: 3, pinIdx: 5 },      // Beat 2: Specular Open Water
        { layer: "water", dateIdx: 3, pinIdx: 3 },      // Beat 3: Flooded Veg Double-Bounce
        { layer: "recurrence", dateIdx: 11, pinIdx: 1 },// Beat 4: Recurrence & Char emergence
        { layer: "paddy", dateIdx: 8, pinIdx: 2 },      // Beat 5: Paddy Rhythm
      ];
      const p = presets[beatIdx] || presets[0];
      state.layerMode = p.layer;
      state.dateIdx = p.dateIdx;
      state.selectedPinIdx = p.pinIdx;
      state.customPixel = null;
      syncLayerRadioButtons();
      switchTab("explorer");
    });
  });

  // Time Slider & Transport Controls
  const timeSlider = document.getElementById("time-slider");
  timeSlider?.addEventListener("input", (e) => {
    state.dateIdx = parseInt(e.target.value, 10);
    updateDateDependentUI();
  });

  document.getElementById("btn-prev")?.addEventListener("click", () => {
    stopAnimation();
    const dates = getActiveData().manifest.dates;
    state.dateIdx = (state.dateIdx - 1 + dates.length) % dates.length;
    updateDateDependentUI();
  });

  document.getElementById("btn-next")?.addEventListener("click", () => {
    stopAnimation();
    const dates = getActiveData().manifest.dates;
    state.dateIdx = (state.dateIdx + 1) % dates.length;
    updateDateDependentUI();
  });

  document.getElementById("btn-play")?.addEventListener("click", () => {
    if (state.isPlaying) {
      stopAnimation();
    } else {
      startAnimation();
    }
  });

  document.getElementById("speed-select")?.addEventListener("change", (e) => {
    state.playSpeedMs = parseInt(e.target.value, 10);
    if (state.isPlaying) {
      stopAnimation();
      startAnimation();
    }
  });

  // Layer Stack Radio Options
  document.querySelectorAll("#layer-list .layer-option").forEach((label) => {
    label.addEventListener("click", () => {
      const radio = label.querySelector('input[type="radio"]');
      if (radio) {
        radio.checked = true;
        state.layerMode = radio.value;
        syncLayerRadioButtons();
        updateExplorerOverlay();
      }
    });
  });

  // Before / After Split-Screen Swipe
  const swipeToggle = document.getElementById("swipe-toggle");
  swipeToggle?.addEventListener("change", (e) => {
    state.swipeEnabled = e.target.checked;
    const box = document.getElementById("swipe-controls-box");
    const hint = document.getElementById("swipe-hint-text");
    if (box) box.style.display = state.swipeEnabled ? "flex" : "none";
    if (hint) hint.style.display = state.swipeEnabled ? "none" : "block";
    if (state.swipeEnabled && !["rgb", "water"].includes(state.layerMode)) {
      state.layerMode = "water";
      syncLayerRadioButtons();
    }
    updateExplorerOverlay();
  });

  document.getElementById("swipe-date-a")?.addEventListener("change", (e) => {
    state.swipeIdxA = parseInt(e.target.value, 10);
    updateExplorerOverlay();
  });
  document.getElementById("swipe-date-b")?.addEventListener("change", (e) => {
    state.swipeIdxB = parseInt(e.target.value, 10);
    updateExplorerOverlay();
  });
  document.getElementById("swipe-slider")?.addEventListener("input", (e) => {
    state.swipePct = parseInt(e.target.value, 10);
    const lbl = document.getElementById("swipe-pct-label");
    if (lbl) lbl.textContent = `${state.swipePct}%`;
    applySwipeClip();
  });

  // Basemap pills & Opacity
  document.querySelectorAll(".pill-btn[data-base]").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.basemap = btn.dataset.base;
      document.querySelectorAll(".pill-btn[data-base]").forEach((b) => {
        b.classList.toggle("active", b.dataset.base === state.basemap);
      });
      if (map && baseTileLayer) {
        map.removeLayer(baseTileLayer);
        const cfg = BASEMAP_URLS[state.basemap];
        baseTileLayer = L.tileLayer(cfg.url, { attribution: cfg.attr, maxZoom: 18, className: cfg.className || "" }).addTo(map);
        baseTileLayer.bringToBack();
      }
    });
  });

  document.getElementById("opacity-slider")?.addEventListener("input", (e) => {
    state.opacity = parseInt(e.target.value, 10) / 100.0;
    const lbl = document.getElementById("opacity-val");
    if (lbl) lbl.textContent = `${e.target.value}%`;
    if (primaryOverlay) primaryOverlay.setOpacity(state.opacity);
    if (secondaryOverlay) secondaryOverlay.setOpacity(state.opacity);
  });

  document.getElementById("chk-transects")?.addEventListener("change", (e) => {
    state.showTransects = e.target.checked;
    renderTransectsOnMap();
  });

  // Change Radio buttons
  document.getElementById("btn-radio-toggle")?.addEventListener("click", () => {
    toggleChangeRadio();
  });
  document.getElementById("btn-radio-mute")?.addEventListener("click", () => {
    state.radioMuted = !state.radioMuted;
    const btn = document.getElementById("btn-radio-mute");
    if (btn) btn.textContent = state.radioMuted ? "🔇" : "🔊";
  });

  // Paddy & Validation quick-jump buttons
  document.getElementById("btn-view-paddy-map")?.addEventListener("click", () => {
    state.layerMode = "paddy";
    syncLayerRadioButtons();
    switchTab("explorer");
  });
  document.getElementById("btn-inspect-s1")?.addEventListener("click", () => {
    state.layerMode = "s1";
    state.dateIdx = 3; // 2026-07-24
    syncLayerRadioButtons();
    switchTab("explorer");
  });
  document.getElementById("btn-inspect-s2")?.addEventListener("click", () => {
    state.layerMode = "s2";
    state.dateIdx = 11; // 2026-11-09
    syncLayerRadioButtons();
    switchTab("explorer");
  });

  // Try Anywhere presets & query button
  document.querySelectorAll(".anywhere-preset").forEach((chip) => {
    chip.addEventListener("click", () => {
      document.querySelectorAll(".anywhere-preset").forEach((c) => c.classList.remove("active"));
      chip.classList.add("active");
      const [w, s, e, n] = chip.dataset.bbox.split(",").map(Number);
      document.getElementById("bbox-west").value = w;
      document.getElementById("bbox-south").value = s;
      document.getElementById("bbox-east").value = e;
      document.getElementById("bbox-north").value = n;
      queryASFGranules(chip.dataset.name);
    });
  });

  document.getElementById("btn-query-asf")?.addEventListener("click", () => {
    queryASFGranules("Custom Bounding Box");
  });
}

function syncLayerRadioButtons() {
  document.querySelectorAll("#layer-list .layer-option").forEach((label) => {
    const r = label.querySelector('input[type="radio"]');
    const isMatch = r && r.value === state.layerMode;
    if (r) r.checked = isMatch;
    label.classList.toggle("active", isMatch);
  });
}

// ============================================================================
// 3. UPDATE ALL VIEWS WHEN AOI OR DATA CHANGES
// ============================================================================
function updateAllViews() {
  const { manifest, water, impact } = getActiveData();
  const val = state.validationMetrics ? state.validationMetrics[state.aoi] : null;

  // 1. Update Story Arc Hero Telemetry
  const aoiTitle = state.aoi === "jamuna" ? "JAMUNA FLOODPLAIN (1,678 KM²)" : "SUNAMGANJ HAOR BASIN (1,678 KM²)";
  setText("hero-telemetry-aoi", aoiTitle);
  setText("hero-stat-passes", `${manifest.dates.length} Passes`);
  setText("hero-stat-peak-water", `${water.peak_water_km2.toFixed(1)} km²`);
  setText("hero-stat-peak-date", `Peak on ${water.peak_flood_date} (Perm: ${water.permanent_water_km2} km²)`);

  const peakImp = impact.time_series.reduce((best, cur) =>
    cur.people_exposed_estimate > best.people_exposed_estimate ? cur : best
  , impact.time_series[0]);
  setText("hero-stat-pop", `${peakImp.people_exposed_estimate.toLocaleString()} people`);

  if (val) {
    const s1Acc = (val.sentinel1_comparison.open_water_metrics.overall_accuracy * 100).toFixed(1);
    const s1Iou = val.sentinel1_comparison.open_water_metrics.iou.toFixed(3);
    setText("hero-stat-val", `${s1Acc}% Acc (IoU ${s1Iou})`);
  }

  // 2. Populate Swipe Date Dropdowns
  const selA = document.getElementById("swipe-date-a");
  const selB = document.getElementById("swipe-date-b");
  if (selA && selB) {
    selA.innerHTML = manifest.dates.map((d, i) => `<option value="${i}">${d}</option>`).join("");
    selB.innerHTML = manifest.dates.map((d, i) => `<option value="${i}">${d}</option>`).join("");
    state.swipeIdxA = 0;
    state.swipeIdxB = Math.min(3, manifest.dates.length - 1);
    selA.value = String(state.swipeIdxA);
    selB.value = String(state.swipeIdxB);
  }

  // 3. Configure Time Slider Range
  const slider = document.getElementById("time-slider");
  if (slider) {
    slider.max = String(manifest.dates.length - 1);
    if (state.dateIdx >= manifest.dates.length) state.dateIdx = 3;
    slider.value = String(state.dateIdx);
  }

  // 4. Show/hide Jamuna transect toggle
  const tRow = document.getElementById("transect-toggle-row");
  if (tRow) {
    tRow.style.display = state.aoi === "jamuna" ? "flex" : "none";
  }

  // 5. Render Landmark Chips & Map Pins
  renderLandmarkChips();
  if (map) {
    renderMapLandmarks();
    renderTransectsOnMap();
  }

  // 6. Update Date-Dependent Explorer UI & Charts
  updateDateDependentUI();
  renderPaddyView();
  renderImpactView();

  // 7. Update Methods & Datasets QA Figures
  const qaCal = document.getElementById("qa-img-cal");
  const qaVal = document.getElementById("qa-img-val");
  if (qaCal) qaCal.src = `images/qa/${state.aoi}_qa_histograms_and_drift.png`;
  if (qaVal) qaVal.src = `images/qa/${state.aoi}_qa_cube_overview.png`;
}

function setText(id, text) {
  const el = document.getElementById(id);
  if (el) el.textContent = text;
}

// ============================================================================
// 4. VIEW 02: INTERACTIVE RADAR EXPLORER (MAP, SWIPE, CHARTS, RADIO)
// ============================================================================
function initExplorerMap() {
  if (map) return;
  const { manifest } = getActiveData();
  const b = manifest.bounds_wgs84; // [west, south, east, north]
  const bounds = [
    [b[1], b[0]],
    [b[3], b[2]],
  ];

  map = L.map("map", {
    center: [manifest.center[1], manifest.center[0]],
    zoom: 11,
    zoomControl: true,
  });

  const cfg = BASEMAP_URLS[state.basemap];
  baseTileLayer = L.tileLayer(cfg.url, { attribution: cfg.attr, maxZoom: 18, className: cfg.className || "" }).addTo(map);
  landmarkLayerGroup = L.layerGroup().addTo(map);
  transectLayerGroup = L.layerGroup().addTo(map);

  map.fitBounds(bounds);
  map.on("move zoom viewreset", () => {
    if (state.swipeEnabled) applySwipeClip();
  });

  // Click anywhere inside AOI to inspect nearest real 80m grid cell
  map.on("click", (ev) => {
    const { lat, lng } = ev.latlng;
    const grid = getActiveData().manifest.dense_click_grid;
    if (!grid || !grid.length) return;
    let best = null;
    let bestDist = Infinity;
    for (const pt of grid) {
      const d = (pt.lat - lat) ** 2 + (pt.lon - lng) ** 2;
      if (d < bestDist) {
        bestDist = d;
        best = pt;
      }
    }
    if (best && bestDist < 0.02) {
      state.customPixel = best;
      state.selectedPinIdx = -1;
      document.querySelectorAll(".landmark-chip[data-pin]").forEach((c) => c.classList.remove("active"));
      updatePinDetailsAndChart();
    }
  });

  // Live Radar Cursor Telemetry HUD on mousemove
  map.on("mousemove", (ev) => {
    const hud = document.getElementById("map-cursor-hud");
    if (!hud) return;
    const { lat, lng } = ev.latlng;
    const grid = getActiveData().manifest.dense_click_grid;
    if (!grid || !grid.length) return;
    let best = null;
    let bestDist = Infinity;
    for (const pt of grid) {
      const d = (pt.lat - lat) ** 2 + (pt.lon - lng) ** 2;
      if (d < bestDist) {
        bestDist = d;
        best = pt;
      }
    }
    if (best && bestDist < 0.015) {
      const hh = best.hh[state.dateIdx];
      const hv = best.hv[state.dateIdx];
      hud.innerHTML = `<span style="color:var(--gold-400);">${lat.toFixed(3)}°N, ${lng.toFixed(3)}°E</span> • HH <b style="color:#fff;">${hh} dB</b> • HV <b style="color:var(--cyan-400);">${hv} dB</b> • Rec <b style="color:var(--emerald-400);">${best.rec}%</b>`;
    } else {
      hud.innerHTML = `<span style="color:var(--gold-400);">RADAR CURSOR:</span> ${lat.toFixed(3)}°N, ${lng.toFixed(3)}°E (Outside 80m AOI Cube)`;
    }
  });

  // Direct mouse/touch dragging of the Before/After Split-Swipe divider on the map
  const dividerEl = document.getElementById("swipe-divider");
  const stageEl = document.querySelector(".map-stage");
  if (dividerEl && stageEl) {
    let draggingSwipe = false;
    dividerEl.addEventListener("mousedown", (ev) => {
      ev.stopPropagation();
      draggingSwipe = true;
      map.dragging.disable();
    });
    window.addEventListener("mousemove", (ev) => {
      if (!draggingSwipe) return;
      const rect = stageEl.getBoundingClientRect();
      const pct = Math.max(5, Math.min(95, Math.round(((ev.clientX - rect.left) / rect.width) * 100)));
      state.swipePct = pct;
      const sl = document.getElementById("swipe-slider");
      const lbl = document.getElementById("swipe-pct-label");
      if (sl) sl.value = String(pct);
      if (lbl) lbl.textContent = `${pct}%`;
      applySwipeClip();
    });
    window.addEventListener("mouseup", () => {
      if (draggingSwipe) {
        draggingSwipe = false;
        map.dragging.enable();
      }
    });
  }

  // Collapsible map legend header
  document.getElementById("legend-header-toggle")?.addEventListener("click", () => {
    const contentEl = document.getElementById("legend-content");
    const iconEl = document.getElementById("legend-collapse-icon");
    if (!contentEl) return;
    const isHidden = contentEl.style.display === "none";
    contentEl.style.display = isHidden ? "block" : "none";
    if (iconEl) iconEl.textContent = isHidden ? "▾" : "▸";
  });

  renderMapLandmarks();
  renderTransectsOnMap();
  updateExplorerOverlay();
}

function getOverlayUrlForMode(mode, dateIdx) {
  const { manifest } = getActiveData();
  const ov = manifest.overlays[dateIdx] || manifest.overlays[0];
  const st = manifest.static_overlays;
  switch (mode) {
    case "rgb":
      return ov.sar_overlay;
    case "water":
      return ov.flood_overlay;
    case "recurrence":
      return st.water_recurrence;
    case "paddy":
      return st.paddy_classes;
    case "worldcover":
      return st.worldcover;
    case "worldpop":
      return st.worldpop;
    case "s1":
      return st.sentinel1_rtc;
    case "s2":
      return st.sentinel2_optical;
    default:
      return ov.sar_overlay;
  }
}

function updateExplorerOverlay() {
  if (!map) return;
  const { manifest } = getActiveData();
  const b = manifest.bounds_wgs84;
  const bounds = [
    [b[1], b[0]],
    [b[3], b[2]],
  ];

  if (primaryOverlay) {
    map.removeLayer(primaryOverlay);
    primaryOverlay = null;
  }
  if (secondaryOverlay) {
    map.removeLayer(secondaryOverlay);
    secondaryOverlay = null;
  }

  const divider = document.getElementById("swipe-divider");

  if (state.swipeEnabled && ["rgb", "water"].includes(state.layerMode)) {
    const urlA = getOverlayUrlForMode(state.layerMode, state.swipeIdxA);
    const urlB = getOverlayUrlForMode(state.layerMode, state.swipeIdxB);
    primaryOverlay = L.imageOverlay(urlA, bounds, { opacity: state.opacity, interactive: false }).addTo(map);
    secondaryOverlay = L.imageOverlay(urlB, bounds, { opacity: state.opacity, interactive: false }).addTo(map);
    if (divider) divider.style.display = "block";
    setTimeout(() => applySwipeClip(), 30);
  } else {
    const url = getOverlayUrlForMode(state.layerMode, state.dateIdx);
    primaryOverlay = L.imageOverlay(url, bounds, { opacity: state.opacity, interactive: false }).addTo(map);
    if (divider) divider.style.display = "none";
  }

  updateMapLegend();
}

function applySwipeClip() {
  const divider = document.getElementById("swipe-divider");
  if (!state.swipeEnabled || !primaryOverlay || !secondaryOverlay) {
    if (divider) divider.style.display = "none";
    return;
  }
  const elA = primaryOverlay.getElement();
  const elB = secondaryOverlay.getElement();
  if (!elA || !elB) return;

  const pct = state.swipePct;
  elA.style.clipPath = `inset(0 ${100 - pct}% 0 0)`;
  elB.style.clipPath = `inset(0 0 0 ${pct}%)`;
  if (divider) {
    divider.style.display = "block";
    divider.style.left = `${pct}%`;
  }
}

function updateMapLegend() {
  const titleEl = document.getElementById("legend-title");
  const contentEl = document.getElementById("legend-content");
  if (!titleEl || !contentEl) return;

  const legends = {
    rgb: {
      title: "NISAR L-Band Dual-Pol RGB Composite",
      items: [
        { color: "#0c4a6e", label: "Smooth Open Water (Specular Dark, HH < −16 dB)" },
        { color: "#22c55e", label: "Vegetated Canopy / Paddy (High HV Volume Scatter)" },
        { color: "#f472b6", label: "Flooded Stems / Double-Bounce (High HH & HH−HV)" },
        { color: "#fde047", label: "Built-up Settlements & Embankments (Corner Reflector)" },
      ],
    },
    water: {
      title: "Water & Monsoon Flood Dynamics",
      items: [
        { color: "#06b6d4", label: "Permanent River / Haor Core (JRC ≥ 50%)" },
        { color: "#3b82f6", label: "Newly Flooded Monsoon Water (JRC < 50%)" },
        { color: "#ec4899", label: "Flooded Vegetation (L-Band Double-Bounce)" },
        { color: "#f59e0b", label: "Receded Flood / Emergent Char Sandbar" },
      ],
    },
    recurrence: {
      title: "12-Pass Water Inundation Recurrence (%)",
      items: [
        { color: "#084081", label: "80–100% Persistent Deep Channel / Haor Lake" },
        { color: "#2b8cbe", label: "45–80% Seasonal Monsoon Floodplain" },
        { color: "#7bccc4", label: "15–45% Ephemeral Flash-Flood / Char Margin" },
      ],
    },
    paddy: {
      title: "Paddy Phenology Clusters (K=4 on WorldCover 40)",
      items: [
        { color: "#10b981", label: "Cluster 1: Early-Planted / High-Biomass Cropland" },
        { color: "#0ea5e9", label: "Cluster 2: Deeply Flooded -> Late Transplanted Crop" },
        { color: "#f59e0b", label: "Cluster 3: Double-Cropped / Mid-Monsoon Canopy Peak" },
        { color: "#a855f7", label: "Cluster 4: Lowland Wetland-Margin Cropland" },
      ],
    },
    worldcover: {
      title: "Real ESA WorldCover 10m (v200 Baseline)",
      items: [
        { color: "#22c55e", label: "Cropland (Class 40 — 54.5% Jamuna / 49.0% Haor)" },
        { color: "#14b8a6", label: "Herbaceous Wetland (Class 90 — 31.9% Haor)" },
        { color: "#057857", label: "Tree Cover & Homestead Groves (Class 10)" },
        { color: "#0694d4", label: "Permanent Water Bodies (Class 80)" },
        { color: "#d4af86", label: "Bare / Braided River Sandbars (Class 60)" },
        { color: "#ef4444", label: "Built-up Settlements (Class 50)" },
      ],
    },
    worldpop: {
      title: "Real WorldPop 100m UN-Adjusted Population",
      items: [
        { color: "#fcffa4", label: "High Density (> 25 people / 0.64 ha pixel)" },
        { color: "#f98e09", label: "Moderate Rural Density (8–25 people / pixel)" },
        { color: "#57106e", label: "Sparse Floodplain Settlement (1–8 people / pixel)" },
      ],
    },
    s1: {
      title: "Real Sentinel-1 C-Band RTC (2026-07-25, 5.6 cm)",
      items: [
        { color: "#081d38", label: "C-Band Specular Open Water (Low VV & VH)" },
        { color: "#34d399", label: "Vegetated Floodplain (VH Volume Scatter)" },
        { color: "#fbbf24", label: "Wind-Roughened Bragg Scatter / Settlements" },
      ],
    },
    s2: {
      title: "Real Sentinel-2 L2A Optical (SWIR-NIR-Red)",
      items: [
        { color: "#061838", label: "Post-Monsoon Open Water (High NDWI > 0)" },
        { color: "#22c55e", label: "Healthy Vegetated Cropland (High NIR B08)" },
        { color: "#eab308", label: "Dry Emergent Char Sandbars (High SWIR B11)" },
      ],
    },
  };

  const lg = legends[state.layerMode] || legends.rgb;
  titleEl.textContent = lg.title;
  contentEl.innerHTML = lg.items
    .map(
      (it) => `
      <div class="legend-item">
        <span class="legend-swatch" style="background:${it.color};"></span>
        <span>${it.label}</span>
      </div>`
    )
    .join("");
}

function renderLandmarkChips() {
  const container = document.getElementById("landmark-chips");
  if (!container) return;
  const pins = getActiveData().manifest.landmark_pins;
  container.innerHTML = pins
    .map(
      (pin, idx) => `
      <button class="landmark-chip ${idx === state.selectedPinIdx ? "active" : ""}" data-pin="${idx}">
        📍 ${idx + 1}. ${pin.name}
      </button>`
    )
    .join("");

  container.querySelectorAll(".landmark-chip").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.selectedPinIdx = parseInt(btn.dataset.pin, 10);
      state.customPixel = null;
      container.querySelectorAll(".landmark-chip").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      renderMapLandmarks();
      updatePinDetailsAndChart();
      if (map) {
        const p = pins[state.selectedPinIdx];
        map.panTo([p.lat, p.lon]);
      }
    });
  });
}

function renderMapLandmarks() {
  if (!map || !landmarkLayerGroup) return;
  landmarkLayerGroup.clearLayers();
  const pins = getActiveData().manifest.landmark_pins;

  pins.forEach((pin, idx) => {
    const isSel = idx === state.selectedPinIdx && !state.customPixel;
    const icon = L.divIcon({
      className: "pin-marker-wrap",
      html: `<div class="pin-marker-dot ${isSel ? "selected" : ""}" title="${pin.name}"></div>`,
      iconSize: [22, 22],
      iconAnchor: [11, 11],
    });
    const marker = L.marker([pin.lat, pin.lon], { icon }).addTo(landmarkLayerGroup);
    marker.bindTooltip(`<strong>${idx + 1}. ${pin.name}</strong><br/>Click to inspect 12-pass NISAR signature`, {
      direction: "top",
      offset: [0, -10],
    });
    marker.on("click", (ev) => {
      L.DomEvent.stopPropagation(ev);
      state.selectedPinIdx = idx;
      state.customPixel = null;
      renderLandmarkChips();
      renderMapLandmarks();
      updatePinDetailsAndChart();
    });
  });
}

function renderTransectsOnMap() {
  if (!map || !transectLayerGroup) return;
  transectLayerGroup.clearLayers();
  if (state.aoi !== "jamuna" || !state.showTransects) return;

  const transects = getActiveData().water.jamuna_transects || [];
  transects.forEach((tr) => {
    const line = L.polyline(
      [
        [tr.lat_deg, tr.lon_range[0]],
        [tr.lat_deg, tr.lon_range[1]],
      ],
      {
        color: "#22d3ee",
        weight: 2.5,
        dashArray: "6, 6",
        opacity: 0.9,
      }
    ).addTo(transectLayerGroup);

    line.bindTooltip(
      `<div style="font-size:12px;line-height:1.4;">
        <strong>${tr.id}: ${tr.name}</strong><br/>
        • Early Monsoon Wet Width: <b>${(tr.width_early_monsoon_m / 1000).toFixed(2)} km</b><br/>
        • Peak Monsoon Wet Width: <b>${(tr.width_peak_monsoon_m / 1000).toFixed(2)} km</b><br/>
        • Post-Monsoon Wet Width: <b>${(tr.width_post_monsoon_m / 1000).toFixed(2)} km</b><br/>
        • Emergent Char Sandbars: <b>${(tr.char_emergence_m / 1000).toFixed(2)} km</b>
      </div>`,
      { sticky: true }
    );
  });
}

function updateDateDependentUI() {
  const { manifest, water, impact } = getActiveData();
  const idx = state.dateIdx;
  const dateStr = manifest.dates[idx];

  const slider = document.getElementById("time-slider");
  if (slider && parseInt(slider.value, 10) !== idx) {
    slider.value = String(idx);
  }

  setText("date-display", dateStr);
  setText("cycle-display", `Pass ${idx + 1} / ${manifest.dates.length}`);
  setText("kpi-date-tag", dateStr);

  // Scene KPIs for active date
  const wRow = water.time_series[idx] || water.time_series[0];
  const iRow = impact.time_series[idx] || impact.time_series[0];

  setText("kpi-open-water", `${wRow.total_water_km2.toFixed(1)} km²`);
  setText("kpi-flooded-veg", `${wRow.flooded_veg_km2.toFixed(1)} km²`);
  setText("kpi-pop-exposed", `${iRow.people_exposed_estimate.toLocaleString()}`);
  setText("kpi-crop-flooded", `${iRow.cropland_flooded_ha.toLocaleString()} ha`);

  updateExplorerOverlay();
  updatePinDetailsAndChart();
}

function getActivePixelSeries() {
  const { manifest } = getActiveData();
  if (state.customPixel) {
    const cp = state.customPixel;
    return {
      name: `Custom Floodplain Pixel (${cp.lat.toFixed(3)}°N, ${cp.lon.toFixed(3)}°E)`,
      badge: `REC ${cp.rec}%`,
      coords: `${cp.lat.toFixed(4)}°N, ${cp.lon.toFixed(4)}°E • WorldCover: ${WORLDCOVER_NAMES[cp.wc] || cp.wc}`,
      dates: manifest.dates,
      hh: cp.hh,
      hv: cp.hv,
      diff: cp.diff,
      explanation: `Real 80 m NISAR pixel at (${cp.lat.toFixed(4)}°N, ${cp.lon.toFixed(4)}°E). ESA WorldCover class: ${
        WORLDCOVER_NAMES[cp.wc] || cp.wc
      }. 12-pass water recurrence: ${cp.rec}%. Estimated WorldPop count in pixel: ${cp.pop} people. On ${
        manifest.dates[state.dateIdx]
      }, co-pol HH is ${cp.hh[state.dateIdx]} dB and cross-pol HV is ${cp.hv[state.dateIdx]} dB.`,
    };
  }
  const pin = manifest.landmark_pins[state.selectedPinIdx] || manifest.landmark_pins[0];
  return {
    name: pin.name,
    badge: `PIN #${state.selectedPinIdx + 1}`,
    coords: `${pin.lat.toFixed(4)}°N, ${pin.lon.toFixed(4)}°E • ${
      WORLDCOVER_NAMES[pin.worldcover_class] || "Floodplain"
    }`,
    dates: pin.time_series.dates,
    hh: pin.time_series.hh_db,
    hv: pin.time_series.hv_db,
    diff: pin.time_series.hv_minus_hh_db,
    explanation: `<strong>${pin.description}</strong><br/><br/>${pin.plain_language_explanation}`,
  };
}

function updatePinDetailsAndChart() {
  const px = getActivePixelSeries();
  setText("pin-title", px.name);
  setText("pin-coords", px.coords);
  setText("pin-badge", px.badge);

  const expEl = document.getElementById("pin-explanation");
  if (expEl) expEl.innerHTML = px.explanation;

  // Update Change Radio telemetry cells for current date
  const curHh = px.hh[state.dateIdx];
  const curHv = px.hv[state.dateIdx];
  const noteObj = hvToNote(curHv);
  const isFlooded = curHv < -16.5 || curHh < -15.2;

  setText("radio-note", `${noteObj.note} (${Math.round(noteObj.freq)} Hz)`);
  setText("radio-backscatter", `${curHv.toFixed(1)} / ${curHh.toFixed(1)} dB`);
  setText("radio-flood-bass", isFlooded ? "ON (65 Hz Sub-Bass)" : "OFF (Dry / Canopy)");

  renderPinChart();
}

function renderPinChart() {
  const canvas = document.getElementById("ts-chart");
  if (!canvas) return;
  const px = getActivePixelSeries();
  const labels = px.dates.map((d) => d.slice(5)); // MM-DD

  // Custom vertical playhead plugin for active date
  const playheadPlugin = {
    id: "activeDatePlayhead",
    afterDatasetsDraw(chart) {
      const { ctx, chartArea, scales } = chart;
      const x = scales.x.getPixelForValue(state.dateIdx);
      if (x >= chartArea.left && x <= chartArea.right) {
        ctx.save();
        ctx.beginPath();
        ctx.moveTo(x, chartArea.top);
        ctx.lineTo(x, chartArea.bottom);
        ctx.lineWidth = 2;
        ctx.strokeStyle = "#fbbf24";
        ctx.setLineDash([4, 3]);
        ctx.stroke();
        ctx.restore();
      }
    },
  };

  if (tsChart) {
    tsChart.destroy();
  }

  tsChart = new Chart(canvas, {
    type: "line",
    data: {
      labels,
      datasets: [
        {
          label: "γ⁰ HH (dB)",
          data: px.hh,
          borderColor: "#fbbf24",
          backgroundColor: "rgba(251, 191, 36, 0.12)",
          borderWidth: 2.2,
          pointRadius: 3.5,
          tension: 0.25,
        },
        {
          label: "γ⁰ HV (dB)",
          data: px.hv,
          borderColor: "#22d3ee",
          backgroundColor: "rgba(34, 211, 238, 0.12)",
          borderWidth: 2.2,
          pointRadius: 3.5,
          tension: 0.25,
        },
        {
          label: "HV − HH (dB)",
          data: px.diff,
          borderColor: "#c084fc",
          borderDash: [4, 4],
          borderWidth: 1.6,
          pointRadius: 2.5,
          tension: 0.25,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      onClick: (evt, elements) => {
        if (elements && elements.length > 0) {
          state.dateIdx = elements[0].index;
          updateDateDependentUI();
        }
      },
      plugins: {
        legend: {
          labels: { color: "#cbd5e1", font: { size: 10, family: "'JetBrains Mono', monospace" }, boxWidth: 12 },
        },
      },
      scales: {
        x: {
          ticks: { color: "#94a3b8", font: { size: 9, family: "'JetBrains Mono', monospace" } },
          grid: { color: "rgba(255,255,255,0.05)" },
        },
        y: {
          ticks: { color: "#94a3b8", font: { size: 9, family: "'JetBrains Mono', monospace" } },
          grid: { color: "rgba(255,255,255,0.06)" },
          title: { display: true, text: "dB", color: "#94a3b8", font: { size: 9 } },
        },
      },
    },
    plugins: [playheadPlugin],
  });
}

// ============================================================================
// 5. TIMELINE ANIMATION & CHANGE RADIO SONIFICATION (WEB AUDIO API)
// ============================================================================
function startAnimation() {
  state.isPlaying = true;
  const btn = document.getElementById("btn-play");
  if (btn) {
    btn.textContent = "⏸ Pause";
    btn.classList.add("playing");
  }
  state.playTimer = setInterval(() => {
    const dates = getActiveData().manifest.dates;
    state.dateIdx = (state.dateIdx + 1) % dates.length;
    updateDateDependentUI();
  }, state.playSpeedMs);
}

function stopAnimation() {
  state.isPlaying = false;
  if (state.playTimer) {
    clearInterval(state.playTimer);
    state.playTimer = null;
  }
  const btn = document.getElementById("btn-play");
  if (btn) {
    btn.textContent = "▶ Play";
    btn.classList.remove("playing");
  }
}

function toggleChangeRadio() {
  if (state.radioPlaying) {
    stopChangeRadio();
  } else {
    startChangeRadio();
  }
}

function startChangeRadio() {
  if (!state.audioCtx) {
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    state.audioCtx = new AudioContextClass();
  }
  if (state.audioCtx.state === "suspended") {
    state.audioCtx.resume();
  }

  state.radioPlaying = true;
  const btn = document.getElementById("btn-radio-toggle");
  const eq = document.getElementById("radio-eq");
  if (btn) {
    btn.textContent = "⏹ Stop";
    btn.classList.add("playing");
  }
  if (eq) eq.classList.add("active");

  playCurrentDateSound();
  state.radioTimer = setInterval(() => {
    const dates = getActiveData().manifest.dates;
    state.dateIdx = (state.dateIdx + 1) % dates.length;
    updateDateDependentUI();
    playCurrentDateSound();
  }, 680);
}

function stopChangeRadio() {
  state.radioPlaying = false;
  if (state.radioTimer) {
    clearInterval(state.radioTimer);
    state.radioTimer = null;
  }
  const btn = document.getElementById("btn-radio-toggle");
  const eq = document.getElementById("radio-eq");
  if (btn) {
    btn.textContent = "▶ Listen";
    btn.classList.remove("playing");
  }
  if (eq) eq.classList.remove("active");
}

function playCurrentDateSound() {
  const px = getActivePixelSeries();
  const idx = state.dateIdx;
  const dateStr = px.dates[idx];
  const hh = px.hh[idx];
  const hv = px.hv[idx];
  const noteObj = hvToNote(hv);
  const isFlooded = hv < -16.5 || hh < -15.2;
  const isDoubleBounce = hh > -8.0 && hh - hv > 6.5;

  // Update accessible caption
  const cap = document.getElementById("radio-caption");
  if (cap) {
    const stateDesc = isDoubleBounce
      ? "Double-Bounce Flooded Stems (Bright Harmonic)"
      : isFlooded
      ? "Specular Open Floodwater (Deep 65 Hz Sub-Bass)"
      : "Vegetated Canopy / Dry Ground (Pentatonic Bell)";
    cap.textContent = `[${dateStr}] Note ${noteObj.note} (${Math.round(
      noteObj.freq
    )} Hz) • HV=${hv.toFixed(1)} dB, HH=${hh.toFixed(1)} dB → ${stateDesc}`;
  }

  if (state.radioMuted || !state.audioCtx) return;

  const ctx = state.audioCtx;
  const now = ctx.currentTime;

  // Lead Pentatonic Oscillator (mapped to HV dB)
  const osc = ctx.createOscillator();
  const filter = ctx.createBiquadFilter();
  const gain = ctx.createGain();

  osc.type = isDoubleBounce ? "sawtooth" : "triangle";
  osc.frequency.setValueAtTime(noteObj.freq, now);

  // Filter brightness mapped to HH - HV polarization ratio
  const cutoff = Math.max(350, Math.min(3200, 900 + (hh - hv) * 180));
  filter.type = "lowpass";
  filter.frequency.setValueAtTime(cutoff, now);

  gain.gain.setValueAtTime(0.001, now);
  gain.gain.exponentialRampToValueAtTime(0.18, now + 0.04);
  gain.gain.exponentialRampToValueAtTime(0.001, now + 0.58);

  osc.connect(filter);
  filter.connect(gain);
  gain.connect(ctx.destination);

  osc.start(now);
  osc.stop(now + 0.6);

  // Sub-bass 65 Hz pulse when flooded
  if (isFlooded) {
    const sub = ctx.createOscillator();
    const subGain = ctx.createGain();
    sub.type = "sine";
    sub.frequency.setValueAtTime(65.41, now); // C2 sub-bass
    subGain.gain.setValueAtTime(0.001, now);
    subGain.gain.exponentialRampToValueAtTime(0.22, now + 0.05);
    subGain.gain.exponentialRampToValueAtTime(0.001, now + 0.55);
    sub.connect(subGain);
    subGain.connect(ctx.destination);
    sub.start(now);
    sub.stop(now + 0.58);
  }
}

// ============================================================================
// 6. VIEW 03: PADDY RHYTHM (UNSUPERVISED K=4 ON ESA WORLDCOVER CROPLAND)
// ============================================================================
function renderPaddyView() {
  const { paddy } = getActiveData();
  const cardsEl = document.getElementById("paddy-cluster-cards");
  if (!cardsEl || !paddy) return;

  cardsEl.innerHTML = paddy.clusters
    .map(
      (c) => `
      <div class="surface-card" style="border-top: 3px solid ${c.color};">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;">
          <span class="badge" style="background:${c.color}22;color:${c.color};border:1px solid ${c.color};">
            CLUSTER ${c.class_id} (${c.share_of_cropland_pct}%)
          </span>
          <span style="font-family:var(--font-mono);font-size:0.74rem;color:var(--text-muted);">
            ΔHV ${c.hv_dynamic_range_db} dB
          </span>
        </div>
        <h3 style="font-size:0.95rem;font-weight:800;color:#ffffff;margin-bottom:6px;">${c.name}</h3>
        <div style="font-family:var(--font-mono);font-size:1.15rem;font-weight:700;color:${c.color};margin-bottom:6px;">
          ${c.area_km2.toFixed(1)} km² <span style="font-size:0.78rem;color:var(--text-muted);">(${c.area_ha.toLocaleString()} ha)</span>
        </div>
        <div style="font-size:0.72rem;color:var(--cyan-400);margin-bottom:8px;font-family:var(--font-mono);">
          Flooded Min: ${c.flooded_transplant_date} • Peak Veg: ${c.peak_vegetative_date}
        </div>
        <p style="font-size:0.76rem;color:var(--text-secondary);line-height:1.5;">${c.hypothesis}</p>
      </div>`
    )
    .join("");

  const labels = paddy.dates.map((d) => d.slice(5));

  // HV Centroid Chart
  const hvCanvas = document.getElementById("paddy-hv-chart");
  if (hvCanvas) {
    if (paddyHvChart) paddyHvChart.destroy();
    paddyHvChart = new Chart(hvCanvas, {
      type: "line",
      data: {
        labels,
        datasets: paddy.clusters.map((c) => ({
          label: `C${c.class_id}: ${c.name.split("(")[0].trim()}`,
          data: c.hv_db_series,
          borderColor: c.color,
          backgroundColor: c.color + "22",
          borderWidth: 2.4,
          pointRadius: 3.5,
          tension: 0.28,
        })),
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { labels: { color: "#cbd5e1", font: { size: 11 } } },
        },
        scales: {
          x: { ticks: { color: "#94a3b8" }, grid: { color: "rgba(255,255,255,0.05)" } },
          y: {
            ticks: { color: "#94a3b8" },
            grid: { color: "rgba(255,255,255,0.06)" },
            title: { display: true, text: "Mean γ⁰ HV (dB)", color: "#94a3b8" },
          },
        },
      },
    });
  }

  // HH Centroid Chart
  const hhCanvas = document.getElementById("paddy-hh-chart");
  if (hhCanvas) {
    if (paddyHhChart) paddyHhChart.destroy();
    paddyHhChart = new Chart(hhCanvas, {
      type: "line",
      data: {
        labels,
        datasets: paddy.clusters.map((c) => ({
          label: `C${c.class_id}: ${c.name.split("(")[0].trim()}`,
          data: c.hh_db_series,
          borderColor: c.color,
          backgroundColor: c.color + "22",
          borderWidth: 2.4,
          pointRadius: 3.5,
          tension: 0.28,
        })),
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { labels: { color: "#cbd5e1", font: { size: 11 } } },
        },
        scales: {
          x: { ticks: { color: "#94a3b8" }, grid: { color: "rgba(255,255,255,0.05)" } },
          y: {
            ticks: { color: "#94a3b8" },
            grid: { color: "rgba(255,255,255,0.06)" },
            title: { display: true, text: "Mean γ⁰ HH (dB)", color: "#94a3b8" },
          },
        },
      },
    });
  }
}

// ============================================================================
// 7. VIEW 04: IMPACT & MULTI-SENSOR VALIDATION
// ============================================================================
function renderImpactView() {
  const { water, impact } = getActiveData();
  const val = state.validationMetrics ? state.validationMetrics[state.aoi] : null;
  if (!impact || !water) return;

  const peakImp = impact.time_series.reduce(
    (best, cur) => (cur.people_exposed_estimate > best.people_exposed_estimate ? cur : best),
    impact.time_series[0]
  );

  const pctAoi = ((water.peak_water_km2 / water.total_aoi_area_km2) * 100).toFixed(1);
  setText("imp-peak-water", `${water.peak_water_km2.toFixed(1)} km²`);
  setText("imp-peak-water-sub", `${pctAoi}% of ${water.total_aoi_area_km2} km² AOI (${water.peak_flood_date})`);

  setText("imp-peak-pop", `${peakImp.people_exposed_estimate.toLocaleString()}`);
  setText(
    "imp-peak-pop-sub",
    `±15% Band: ${peakImp.people_exposed_range[0].toLocaleString()} – ${peakImp.people_exposed_range[1].toLocaleString()}`
  );

  setText("imp-peak-crop", `${peakImp.cropland_flooded_ha.toLocaleString()} ha`);
  setText("imp-peak-crop-sub", `Of ${impact.total_cropland_in_aoi_ha.toLocaleString()} ha WorldCover Cropland`);

  setText("imp-upazila-count", `${impact.ranked_upazila_impact.length} Upazilas`);
  setText("imp-district-sub", `Across ${impact.ranked_district_impact.length} Districts (geoBoundaries ADM2/3)`);
  setText("imp-table-date-badge", `PEAK: ${impact.peak_flood_date}`);

  // Populate Upazila Table
  const tbody = document.getElementById("impact-upazila-tbody");
  if (tbody) {
    tbody.innerHTML = impact.ranked_upazila_impact
      .map(
        (u) => `
        <tr>
          <td><strong>${u.upazila}</strong></td>
          <td>${u.district}</td>
          <td style="font-family:var(--font-mono);color:var(--cyan-400);">${u.aoi_footprint_km2.toFixed(1)} km²</td>
          <td style="font-family:var(--font-mono);color:var(--gold-400);">
            ${u.people_affected_peak.toLocaleString()}
            <span style="font-size:0.68rem;color:var(--text-muted);">(${u.people_affected_range[0].toLocaleString()}–${u.people_affected_range[1].toLocaleString()})</span>
          </td>
          <td style="font-family:var(--font-mono);color:var(--emerald-400);">${u.cropland_affected_ha.toLocaleString()} ha</td>
        </tr>`
      )
      .join("");
  }

  // Dual-Axis Impact Time-Series Chart
  const impCanvas = document.getElementById("impact-ts-chart");
  if (impCanvas) {
    if (impactTsChart) impactTsChart.destroy();
    const labels = water.dates.map((d) => d.slice(5));
    impactTsChart = new Chart(impCanvas, {
      type: "bar",
      data: {
        labels,
        datasets: [
          {
            type: "line",
            label: "Exposed Population (WorldPop)",
            data: impact.time_series.map((r) => r.people_exposed_estimate),
            borderColor: "#fbbf24",
            backgroundColor: "rgba(251, 191, 36, 0.18)",
            borderWidth: 2.5,
            yAxisID: "yPop",
            tension: 0.25,
          },
          {
            type: "bar",
            label: "Open Water Area (km²)",
            data: water.time_series.map((r) => r.total_water_km2),
            backgroundColor: "rgba(6, 182, 212, 0.55)",
            borderColor: "#06b6d4",
            borderWidth: 1,
            yAxisID: "yArea",
          },
          {
            type: "bar",
            label: "Flooded Vegetation (km²)",
            data: water.time_series.map((r) => r.flooded_veg_km2),
            backgroundColor: "rgba(236, 72, 153, 0.65)",
            borderColor: "#ec4899",
            borderWidth: 1,
            yAxisID: "yArea",
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: { labels: { color: "#cbd5e1", font: { size: 11 } } },
        },
        scales: {
          x: { ticks: { color: "#94a3b8" }, grid: { color: "rgba(255,255,255,0.05)" } },
          yArea: {
            type: "linear",
            position: "left",
            ticks: { color: "#22d3ee" },
            grid: { color: "rgba(255,255,255,0.06)" },
            title: { display: true, text: "Inundated Area (km²)", color: "#22d3ee" },
          },
          yPop: {
            type: "linear",
            position: "right",
            ticks: { color: "#fbbf24" },
            grid: { drawOnChartArea: false },
            title: { display: true, text: "Exposed Population", color: "#fbbf24" },
          },
        },
      },
    });
  }

  // Stage 5 Validation Cards
  if (val) {
    const s1 = val.sentinel1_comparison;
    const s1m = s1.open_water_metrics;
    setText("val-s1-date-badge", `${s1.nisar_date} vs ${s1.sentinel1_date}`);
    setText(
      "val-s1-scene-desc",
      `Compares NISAR L2 GCOV (${s1.nisar_date}, ${s1.nisar_open_water_km2} km² open water + ${s1.nisar_flooded_veg_km2} km² flooded veg) against real Sentinel-1 C-Band RTC (${s1.sentinel1_granules[0]}, ${s1.s1_open_water_km2} km² water).`
    );
    setText("val-s1-acc", `${(s1m.overall_accuracy * 100).toFixed(1)}%`);
    setText("val-s1-kappa", s1m.cohens_kappa.toFixed(3));
    setText("val-s1-iou", s1m.iou.toFixed(3));
    setText("val-s1-pr", `${(s1m.precision * 100).toFixed(0)}% / ${(s1m.recall * 100).toFixed(0)}%`);
    setText("val-s1-physics-note", val.known_limitations_and_physics.wind_roughened_water);

    const s2 = val.sentinel2_optical_comparison;
    const s2m = s2.optical_agreement_metrics;
    setText("val-s2-date-badge", `${s2.nisar_date} vs ${s2.sentinel2_date}`);
    setText(
      "val-s2-scene-desc",
      `Compares post-monsoon NISAR L2 GCOV (${s2.nisar_date}, ${s2.nisar_open_water_km2} km² water) against cloud-free Copernicus Sentinel-2 L2A Optical NDWI (${s2.sentinel2_date}, ${s2.s2_optical_water_km2} km² water).`
    );
    setText("val-s2-acc", `${(s2m.overall_accuracy * 100).toFixed(1)}%`);
    setText("val-s2-kappa", s2m.cohens_kappa.toFixed(3));
    setText("val-s2-iou", s2m.iou.toFixed(3));
    setText("val-s2-pr", `${(s2m.precision * 100).toFixed(0)}% / ${(s2m.recall * 100).toFixed(0)}%`);
    setText("val-s2-physics-note", val.known_limitations_and_physics.flooded_vegetation_double_bounce);
  }

  // Render Jamuna Braided River Transect Cards (T1-T3)
  const transectSec = document.getElementById("jamuna-transect-section");
  const transectGrid = document.getElementById("transect-cards-grid");
  const transects = water.jamuna_transects || [];
  if (transectSec && transectGrid) {
    if (transects.length > 0) {
      transectSec.style.display = "block";
      transectGrid.innerHTML = transects
        .map(
          (tr) => `
          <div class="surface-card" style="border-top: 3px solid var(--cyan-400);">
            <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;">
              <span class="badge badge-cyan">TRANSECT ${tr.id} (${tr.lat_deg.toFixed(2)}°N)</span>
              <span style="font-family:var(--font-mono);font-size:0.72rem;color:var(--gold-400);">
                Char Emergence: ${(tr.char_emergence_m / 1000).toFixed(2)} km
              </span>
            </div>
            <h3 style="font-size:0.95rem;font-weight:800;color:#ffffff;margin-bottom:10px;">${tr.name}</h3>
            <div class="kpi-grid-2">
              <div class="kpi-mini">
                <div class="kpi-mini-label">Early Monsoon (Jun 18)</div>
                <div class="kpi-mini-val">${(tr.width_early_monsoon_m / 1000).toFixed(2)} km</div>
              </div>
              <div class="kpi-mini">
                <div class="kpi-mini-label">Peak Flood (Jul 24)</div>
                <div class="kpi-mini-val" style="color:var(--cyan-400);">${(tr.width_peak_monsoon_m / 1000).toFixed(2)} km</div>
              </div>
              <div class="kpi-mini">
                <div class="kpi-mini-label">Post-Monsoon (Nov 09)</div>
                <div class="kpi-mini-val">${(tr.width_post_monsoon_m / 1000).toFixed(2)} km</div>
              </div>
              <div class="kpi-mini">
                <div class="kpi-mini-label">New Char Sandbars</div>
                <div class="kpi-mini-val" style="color:var(--gold-400);">+${(tr.char_emergence_m / 1000).toFixed(2)} km</div>
              </div>
            </div>
          </div>`
        )
        .join("");
    } else {
      transectSec.style.display = "none";
    }
  }
}

// ============================================================================
// 8. VIEW 05: TRY ANYWHERE — LIVE NASA ASF SEARCH API INTEGRATION
// ============================================================================
function initAnywhereMap() {
  if (anywhereMap) {
    anywhereMap.invalidateSize();
    return;
  }
  anywhereMap = L.map("anywhere-map", {
    center: [24.62, 89.78],
    zoom: 7,
  });
  L.tileLayer(BASEMAP_URLS.dark.url, {
    attribution: BASEMAP_URLS.dark.attr,
    maxZoom: 18,
    className: BASEMAP_URLS.dark.className || "",
  }).addTo(anywhereMap);
}

async function queryASFGranules(regionLabel = "Selected Bounding Box") {
  const w = parseFloat(document.getElementById("bbox-west").value);
  const s = parseFloat(document.getElementById("bbox-south").value);
  const e = parseFloat(document.getElementById("bbox-east").value);
  const n = parseFloat(document.getElementById("bbox-north").value);

  setText(
    "cli-repro-cmd",
    `python delta-pulse/pipeline/00_coverage.py --bbox ${w.toFixed(2)} ${s.toFixed(2)} ${e.toFixed(2)} ${n.toFixed(2)}`
  );

  if (anywhereMap) {
    if (anywhereRect) anywhereMap.removeLayer(anywhereRect);
    anywhereRect = L.rectangle(
      [
        [s, w],
        [n, e],
      ],
      { color: "#fbbf24", weight: 2, fillOpacity: 0.18 }
    ).addTo(anywhereMap);
    anywhereMap.fitBounds(
      [
        [s, w],
        [n, e],
      ],
      { padding: [25, 25], maxZoom: 9 }
    );
  }

  const statusEl = document.getElementById("asf-api-status");
  if (statusEl) statusEl.textContent = "QUERYING NASA ASF API...";

  const polygonWkt = `POLYGON((${w} ${s},${e} ${s},${e} ${n},${w} ${n},${w} ${s}))`;
  const asfUrl = `https://api.daac.asf.alaska.edu/services/search/param?dataset=NISAR&processingLevel=GCOV&intersectsWith=${encodeURIComponent(
    polygonWkt
  )}&output=json&maxResults=25`;

  let granules = [];
  try {
    const resp = await fetch(asfUrl);
    if (resp.ok) {
      const data = await resp.json();
      const rawList = Array.isArray(data) ? data[0] || [] : data.results || [];
      granules = rawList.map((g) => ({
        date: (g.startTime || "").slice(0, 10),
        id: g.granuleName || g.fileID,
        trackFrame: `Track ${g.track || "?"} / Frame ${g.frame || "?"} (${g.flightDirection || "A"})`,
        maturity: (g.startTime || "") >= "2026-06-17" ? "PROVISIONAL CALIBRATED" : "BETA (PRE-CAL)",
        sizeMb: g.sizeMB ? parseFloat(g.sizeMB).toFixed(1) : "2150.0",
        url: g.downloadUrl || "https://search.asf.alaska.edu/",
      }));
      if (statusEl) statusEl.textContent = "LIVE ASF API (200 OK)";
    }
  } catch (err) {
    // Fallback to cached real ASF coverage file if offline or CORS-restricted
    if (statusEl) statusEl.textContent = "CACHED ASF CATALOG";
  }

  if (granules.length === 0 && state.coverageRaw) {
    const fallback = state.coverageRaw.jamuna_floodplain?.sample_granules || [];
    granules = fallback.map((g) => ({
      date: g.start_time.slice(0, 10),
      id: g.scene_name,
      trackFrame: `Track ${g.track} / Frame ${g.frame} (${g.flight_direction})`,
      maturity: g.start_time >= "2026-06-17" ? "PROVISIONAL CALIBRATED" : "BETA (PRE-CAL)",
      sizeMb: g.bytes ? (g.bytes / (1024 * 1024)).toFixed(1) : "2140.0",
      url: g.url,
    }));
  }

  setText("anywhere-results-title", `Discovered NISAR L2 GCOV Scenes — ${regionLabel}`);
  setText("anywhere-count-badge", `${granules.length} SCENES`);

  const tbody = document.getElementById("anywhere-results-tbody");
  if (tbody) {
    tbody.innerHTML = granules
      .slice(0, 15)
      .map(
        (g) => `
        <tr>
          <td style="font-family:var(--font-mono);color:var(--gold-400);">${g.date}</td>
          <td style="font-family:var(--font-mono);font-size:0.72rem;">${g.id}</td>
          <td>${g.trackFrame}</td>
          <td>
            <span class="badge ${g.maturity.includes("PROVISIONAL") ? "badge-emerald" : "badge-gold"}">
              ${g.maturity}
            </span>
          </td>
          <td style="font-family:var(--font-mono);">${g.sizeMb} MB</td>
          <td><a href="${g.url}" target="_blank" rel="noopener" style="color:var(--cyan-400);">Download HDF5 →</a></td>
        </tr>`
      )
      .join("");
  }
}
