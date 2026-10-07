/**
 * Wi-Fi Performance Mapper — Interactive Floor Grid, Measurement Workflow & Heatmap Visualization (M11–M13)
 *
 * Responsibilities:
 * 1. Asynchronously fetch and inject the authoritative SVG floor plan (floor1.svg).
 * 2. Discover and validate all 60 grid cell elements from SVG DOM.
 * 3. Manage active survey session loading and creation via GET/POST /sessions.
 * 4. Load session historical measurements via GET /measurements?session_id=<id>&floor=Floor-1.
 * 5. Maintain frontend latest-measurement-per-cell cache (append-only history intact).
 * 6. Expose 4 primary metrics: RSSI (dBm), Latency (ms), Packet Loss (%), Throughput (Mbps).
 * 7. Compute dynamic session-relative min/max normalization and continuous heatmap colors.
 * 8. Render 3 visual states: Unmeasured, Measured-Null (N/A), Measured-Numeric (0.0 is valid).
 * 9. Render dynamic heatmap legend (metric, unit, dynamic min/max, no-data swatch).
 * 10. Instant client-side metric switching without redundant network calls.
 * 11. Coexist with M11/M12 cell selection and trigger live 5-sample survey measurements.
 * 12. Immediately merge live measurement results into cache and update heatmap.
 */

(function () {
  "use strict";

  // Metric Configuration Contract (M13)
  const METRIC_CONFIG = {
    rssi_dbm: {
      key: "rssi_dbm",
      label: "RSSI",
      unit: "dBm",
      isHigherBetter: true,
      decimals: 1,
      format: (val) => (val !== null && val !== undefined ? `${Number(val).toFixed(1)} dBm` : "N/A"),
    },
    latency_ms: {
      key: "latency_ms",
      label: "Latency",
      unit: "ms",
      isHigherBetter: false,
      decimals: 1,
      format: (val) => (val !== null && val !== undefined ? `${Number(val).toFixed(1)} ms` : "N/A"),
    },
    packet_loss_percent: {
      key: "packet_loss_percent",
      label: "Packet Loss",
      unit: "%",
      isHigherBetter: false,
      decimals: 1,
      format: (val) => (val !== null && val !== undefined ? `${Number(val).toFixed(1)}%` : "N/A"),
    },
    throughput_mbps: {
      key: "throughput_mbps",
      label: "Throughput",
      unit: "Mbps",
      isHigherBetter: true,
      decimals: 1,
      format: (val) => (val !== null && val !== undefined ? `${Number(val).toFixed(1)} Mbps` : "N/A"),
    },
  };

  // Helper to generate canonical cell cache key
  function getCellKey(floor, x, y) {
    return `${floor}_${Number(x).toFixed(2)}_${Number(y).toFixed(2)}`;
  }

  // Application State
  const state = {
    selectedCell: null,
    activeSessionId: null,
    sessions: [],
    sessionMeasurements: [], // Full historical measurements for active session (M14)
    isMeasuring: false,
    cells: new Map(),
    svgLoaded: false,
    selectedMetric: "rssi_dbm",
    measurementCache: new Map(), // key: getCellKey(floor, x, y) -> latest measurement object
  };

  // DOM Elements
  const elements = {
    // Floor plan & Metric Selector
    container: document.getElementById("floorplan-container"),
    status: document.getElementById("grid-status"),
    activeSessionBadge: document.getElementById("active-session-badge"),
    metricSelect: document.getElementById("metric-select"),

    // Heatmap Legend
    legendContainer: document.getElementById("heatmap-legend"),
    legendMetricLabel: document.getElementById("legend-metric-label"),
    legendScaleType: document.getElementById("legend-scale-type"),
    legendActiveBody: document.getElementById("legend-active-body"),
    legendMinVal: document.getElementById("legend-min-val"),
    legendMaxVal: document.getElementById("legend-max-val"),
    legendEmptyMsg: document.getElementById("legend-empty-msg"),

    // Session management
    sessionSelect: document.getElementById("session-select"),
    toggleCreateSessionBtn: document.getElementById("toggle-create-session-btn"),
    createSessionForm: document.getElementById("create-session-form"),
    newSessionId: document.getElementById("new-session-id"),
    newSessionName: document.getElementById("new-session-name"),
    newSessionFloor: document.getElementById("new-session-floor"),
    cancelCreateSessionBtn: document.getElementById("cancel-create-session-btn"),
    sessionMsg: document.getElementById("session-msg"),

    // Survey progress & coverage widget (M14)
    surveyProgressCard: document.getElementById("survey-progress-card"),
    surveyCoverageText: document.getElementById("survey-coverage-text"),
    surveyTotalReadingsText: document.getElementById("survey-total-readings-text"),
    surveyProgressBarTrack: document.getElementById("survey-progress-bar-track"),
    surveyProgressBarFill: document.getElementById("survey-progress-bar-fill"),

    // Selected cell details
    noSelectionMsg: document.getElementById("no-selection-msg"),
    cellDetailsContainer: document.getElementById("cell-details-container"),
    fieldCellId: document.getElementById("selected-cell-id"),
    fieldFloor: document.getElementById("selected-floor"),
    fieldX: document.getElementById("selected-x"),
    fieldY: document.getElementById("selected-y"),
    fieldRow: document.getElementById("selected-row"),
    fieldCol: document.getElementById("selected-col"),

    // Cell survey summary (M13 cached latest measurement details)
    cellSurveySummary: document.getElementById("cell-survey-summary"),
    cellMeasuredStatusBadge: document.getElementById("cell-measured-status-badge"),
    cellMetricsList: document.getElementById("cell-metrics-list"),
    cellCachedRssi: document.getElementById("cell-cached-rssi"),
    cellCachedSignal: document.getElementById("cell-cached-signal"),
    cellCachedLatency: document.getElementById("cell-cached-latency"),
    cellCachedPacketLoss: document.getElementById("cell-cached-packet-loss"),
    cellCachedThroughput: document.getElementById("cell-cached-throughput"),
    cellCachedAp: document.getElementById("cell-cached-ap"),
    cellCachedTimestamp: document.getElementById("cell-cached-timestamp"),
    cellCachedSamples: document.getElementById("cell-cached-samples"),

    // Selected-cell measurement history (M14)
    cellHistorySection: document.getElementById("cell-history-section"),
    cellHistoryCountBadge: document.getElementById("cell-history-count-badge"),
    cellHistoryEmpty: document.getElementById("cell-history-empty"),
    cellHistoryList: document.getElementById("cell-history-list"),

    // Measurement controls (M12)
    measureBtn: document.getElementById("measure-btn"),
    measureLoadingIndicator: document.getElementById("measure-loading-indicator"),
    measureErrorBanner: document.getElementById("measure-error-banner"),
    measureErrorTitle: document.getElementById("measure-error-title"),
    measureErrorDetail: document.getElementById("measure-error-detail"),

    // Measurement results (M12)
    resultPanel: document.getElementById("measurement-result-panel"),
    resultStatusBadge: document.getElementById("result-status-badge"),
    resultPersistedBadge: document.getElementById("result-persisted-badge"),
    resultRssi: document.getElementById("result-rssi"),
    resultSignal: document.getElementById("result-signal"),
    resultLatency: document.getElementById("result-latency"),
    resultPacketLoss: document.getElementById("result-packet-loss"),
    resultThroughput: document.getElementById("result-throughput"),
    resultId: document.getElementById("result-id"),
    resultSession: document.getElementById("result-session"),
    resultCoords: document.getElementById("result-coords"),
    resultSsid: document.getElementById("result-ssid"),
    resultBssid: document.getElementById("result-bssid"),
    resultRoaming: document.getElementById("result-roaming"),
    resultTimestamp: document.getElementById("result-timestamp"),
    resultErrorContainer: document.getElementById("result-error-container"),
    resultErrorMsg: document.getElementById("result-error-msg"),
  };

  /**
   * Display an error message in the floor plan container.
   */
  function displayGridError(title, message) {
    if (elements.status) {
      elements.status.textContent = "Error";
      elements.status.className = "status-indicator error";
    }
    if (elements.container) {
      elements.container.innerHTML = `
        <div class="error-banner">
          <h3>${title}</h3>
          <p>${message}</p>
        </div>
      `;
    }
  }

  /**
   * Update the Measure button enabled/disabled state.
   */
  function updateMeasureButtonState() {
    if (!elements.measureBtn) return;
    const canMeasure = Boolean(
      state.activeSessionId &&
      state.selectedCell &&
      !state.isMeasuring
    );
    elements.measureBtn.disabled = !canMeasure;
  }

  /**
   * Display a session feedback message (success or error).
   */
  function showSessionMsg(text, type) {
    if (!elements.sessionMsg) return;
    elements.sessionMsg.textContent = text;
    elements.sessionMsg.className = `form-feedback ${type}`;
    elements.sessionMsg.style.display = "block";
  }

  /**
   * Clear session feedback message.
   */
  function clearSessionMsg() {
    if (!elements.sessionMsg) return;
    elements.sessionMsg.style.display = "none";
    elements.sessionMsg.textContent = "";
  }

  /**
   * Update active session badge, dropdown selection, and trigger measurements load.
   */
  async function setActiveSession(sessionId) {
    state.activeSessionId = sessionId || null;
    if (elements.activeSessionBadge) {
      elements.activeSessionBadge.textContent = state.activeSessionId
        ? state.activeSessionId
        : "No active session";
    }
    // Toggle the chip-dot live indicator
    const sdot = document.getElementById("sdot");
    if (sdot) {
      if (state.activeSessionId) {
        sdot.classList.add("on");
      } else {
        sdot.classList.remove("on");
      }
    }

    if (elements.sessionSelect && sessionId) {
      elements.sessionSelect.value = sessionId;
    }
    updateMeasureButtonState();

    // Fetch and render heatmap for newly active session
    await fetchSessionMeasurements(state.activeSessionId, "Floor-1");
  }

  /**
   * Populate session dropdown from sessions array.
   */
  function populateSessionDropdown(sessions) {
    if (!elements.sessionSelect) return;
    elements.sessionSelect.innerHTML = "";

    if (!sessions || sessions.length === 0) {
      const opt = document.createElement("option");
      opt.value = "";
      opt.textContent = "-- No Sessions Found (Create One Below) --";
      elements.sessionSelect.appendChild(opt);
      setActiveSession(null);
      if (elements.createSessionForm) {
        elements.createSessionForm.style.display = "block";
      }
      return;
    }

    sessions.forEach((s) => {
      const opt = document.createElement("option");
      opt.value = s.session_id;
      opt.textContent = `${s.name} (${s.session_id}) [${s.floor}]`;
      elements.sessionSelect.appendChild(opt);
    });

    // Select the first (most recent) session by default
    setActiveSession(sessions[0].session_id);
    if (elements.createSessionForm) {
      elements.createSessionForm.style.display = "none";
    }
  }

  /**
   * Fetch survey sessions from backend GET /sessions.
   */
  async function loadSessions() {
    try {
      const response = await fetch("/sessions");
      if (!response.ok) {
        throw new Error(`HTTP ${response.status} ${response.statusText}`);
      }
      const data = await response.json();
      state.sessions = Array.isArray(data) ? data : [];
      populateSessionDropdown(state.sessions);
    } catch (err) {
      console.error("Failed to load sessions:", err);
      showSessionMsg(`Failed to load sessions: ${err.message}`, "error");
      setActiveSession(null);
    }
  }

  /**
   * Build the latest-per-cell measurement cache from historical measurements list.
   * Measurements are returned sorted by (timestamp ASC, id ASC); later record replaces earlier.
   */
  function buildMeasurementCache(measurements) {
    state.measurementCache.clear();
    if (!Array.isArray(measurements)) return;

    measurements.forEach((m) => {
      if (m && m.floor !== undefined && m.x !== undefined && m.y !== undefined) {
        const key = getCellKey(m.floor, m.x, m.y);
        state.measurementCache.set(key, m);
      }
    });
  }

  /**
   * Compute deterministic survey coverage stats from active session measurements (M14).
   * Total grid cell count for Floor-1 is authoritatively 60.
   */
  function calculateSurveyCoverage(measurements) {
    if (!Array.isArray(measurements) || measurements.length === 0) {
      return {
        distinctCount: 0,
        totalCells: 60,
        percentage: 0.0,
        totalReadings: 0,
      };
    }

    const distinctKeys = new Set();
    measurements.forEach((m) => {
      if (m && m.floor !== undefined && m.x !== undefined && m.y !== undefined) {
        distinctKeys.add(getCellKey(m.floor, m.x, m.y));
      }
    });

    const distinctCount = distinctKeys.size;
    const percentage = (distinctCount / 60) * 100;
    return {
      distinctCount,
      totalCells: 60,
      percentage,
      totalReadings: measurements.length,
    };
  }

  /**
   * Render the survey progress card (coverage & total readings) (M14).
   */
  function renderSurveyProgress() {
    const coverage = calculateSurveyCoverage(state.sessionMeasurements);

    // Sidebar progress card (original IDs used by app.js)
    if (elements.surveyCoverageText) {
      elements.surveyCoverageText.textContent = `Coverage: ${coverage.distinctCount} / 60 cells (${coverage.percentage.toFixed(1)}%)`;
    }
    if (elements.surveyTotalReadingsText) {
      elements.surveyTotalReadingsText.textContent = `Total Readings: ${coverage.totalReadings}`;
    }
    if (elements.surveyProgressBarFill) {
      elements.surveyProgressBarFill.style.width = `${coverage.percentage.toFixed(1)}%`;
    }
    if (elements.surveyProgressBarTrack) {
      elements.surveyProgressBarTrack.setAttribute("aria-valuenow", coverage.percentage.toFixed(1));
    }

    // Coverage strip (new header-level bar)
    const pctEl = document.getElementById("survey-coverage-pct");
    if (pctEl) pctEl.textContent = `${Math.round(coverage.percentage)}%`;

    const coverageCellsEl = document.getElementById("survey-coverage-text");
    if (coverageCellsEl) coverageCellsEl.textContent = `${coverage.distinctCount} of 60 cells`;

    const readingsEl = document.getElementById("survey-total-readings-text");
    if (readingsEl) readingsEl.textContent = `${coverage.totalReadings} readings`;

    const stripBarFill = document.getElementById("survey-progress-bar-fill");
    if (stripBarFill) stripBarFill.style.width = `${coverage.percentage.toFixed(1)}%`;

    const stripBarTrack = document.getElementById("survey-progress-bar-track");
    if (stripBarTrack) stripBarTrack.setAttribute("aria-valuenow", coverage.percentage.toFixed(1));

    // Sidebar duplicates (new _sidebar IDs)
    const sidebarCovEl = document.getElementById("survey-coverage-text-sidebar");
    if (sidebarCovEl) sidebarCovEl.textContent = `Coverage: ${coverage.distinctCount} / 60 cells (${coverage.percentage.toFixed(1)}%)`;

    const sidebarReadEl = document.getElementById("survey-total-readings-text-sidebar");
    if (sidebarReadEl) sidebarReadEl.textContent = `Total Readings: ${coverage.totalReadings}`;

    const sidebarBarFill = document.getElementById("survey-progress-bar-fill-sidebar");
    if (sidebarBarFill) sidebarBarFill.style.width = `${coverage.percentage.toFixed(1)}%`;

    const sidebarBarTrack = document.getElementById("survey-progress-bar-track-sidebar");
    if (sidebarBarTrack) sidebarBarTrack.setAttribute("aria-valuenow", coverage.percentage.toFixed(1));
  }


  /**
   * Render measurement history for the selected cell (M14).
   * Strict fidelity: preserve backend ordering, use N/A for null metrics, do not fabricate status.
   */
  function renderCellHistory(cellInfo) {
    if (!cellInfo || !elements.cellHistorySection) return;

    if (!Array.isArray(state.sessionMeasurements) || state.sessionMeasurements.length === 0) {
      if (elements.cellHistoryCountBadge) elements.cellHistoryCountBadge.textContent = "Readings: 0";
      if (elements.cellHistoryEmpty) elements.cellHistoryEmpty.style.display = "block";
      if (elements.cellHistoryList) {
        elements.cellHistoryList.style.display = "none";
        elements.cellHistoryList.innerHTML = "";
      }
      return;
    }

    const targetKey = getCellKey(cellInfo.floor, cellInfo.x, cellInfo.y);
    const cellReadings = state.sessionMeasurements.filter((m) => {
      if (!m || m.floor === undefined || m.x === undefined || m.y === undefined) return false;
      if (state.activeSessionId && m.session_id !== state.activeSessionId) return false;
      return getCellKey(m.floor, m.x, m.y) === targetKey;
    });

    if (elements.cellHistoryCountBadge) {
      elements.cellHistoryCountBadge.textContent = `Readings: ${cellReadings.length}`;
    }

    if (cellReadings.length === 0) {
      if (elements.cellHistoryEmpty) elements.cellHistoryEmpty.style.display = "block";
      if (elements.cellHistoryList) {
        elements.cellHistoryList.style.display = "none";
        elements.cellHistoryList.innerHTML = "";
      }
      return;
    }

    if (elements.cellHistoryEmpty) elements.cellHistoryEmpty.style.display = "none";
    if (elements.cellHistoryList) {
      elements.cellHistoryList.style.display = "flex";
      elements.cellHistoryList.innerHTML = "";

      cellReadings.forEach((m) => {
        const row = document.createElement("div");
        row.className = "history-row";

        const rssiStr = m.rssi_dbm !== null && m.rssi_dbm !== undefined ? `${Number(m.rssi_dbm).toFixed(1)} dBm` : "N/A";
        const latStr = m.latency_ms !== null && m.latency_ms !== undefined ? `${Number(m.latency_ms).toFixed(1)} ms` : "N/A";
        const lossStr = m.packet_loss_percent !== null && m.packet_loss_percent !== undefined ? `${Number(m.packet_loss_percent).toFixed(1)}%` : "N/A";
        const tpStr = m.throughput_mbps !== null && m.throughput_mbps !== undefined ? `${Number(m.throughput_mbps).toFixed(1)} Mbps` : "N/A";
        const samplesStr = m.sample_count !== null && m.sample_count !== undefined ? `${m.sample_count} samples` : "N/A";
        const timeStr = m.timestamp ? (m.timestamp.includes("T") ? m.timestamp.split("T")[1].split(".")[0] : m.timestamp) : "N/A";

        row.innerHTML = `
          <div class="history-row-header">
            <span class="history-id">#${m.id || "--"}</span>
            <span class="history-time" title="${m.timestamp || ''}">${timeStr}</span>
            <span class="history-samples">${samplesStr}</span>
          </div>
          <div class="history-row-metrics">
            <div class="history-metric-item"><span class="history-metric-label">RSSI:</span><span class="history-metric-val">${rssiStr}</span></div>
            <div class="history-metric-item"><span class="history-metric-label">Latency:</span><span class="history-metric-val">${latStr}</span></div>
            <div class="history-metric-item"><span class="history-metric-label">Loss:</span><span class="history-metric-val">${lossStr}</span></div>
            <div class="history-metric-item"><span class="history-metric-label">Throughput:</span><span class="history-metric-val">${tpStr}</span></div>
          </div>
        `;
        elements.cellHistoryList.appendChild(row);
      });
    }
  }

  /**
   * Fetch historical measurements for active session via GET /measurements?session_id=...&floor=Floor-1.
   */
  async function fetchSessionMeasurements(sessionId, floor = "Floor-1") {
    if (!sessionId) {
      state.sessionMeasurements = [];
      state.measurementCache.clear();
      renderSurveyProgress();
      renderHeatmap();
      if (state.selectedCell) {
        updateSelectionPanel(state.selectedCell);
      }
      return;
    }

    try {
      const url = `/measurements?session_id=${encodeURIComponent(sessionId)}&floor=${encodeURIComponent(floor)}`;
      const response = await fetch(url);
      if (!response.ok) {
        throw new Error(`HTTP ${response.status} ${response.statusText}`);
      }
      const measurements = await response.json();
      state.sessionMeasurements = Array.isArray(measurements) ? measurements : [];
      buildMeasurementCache(state.sessionMeasurements);
      renderSurveyProgress();
      renderHeatmap();
      if (state.selectedCell) {
        updateSelectionPanel(state.selectedCell);
      }
    } catch (err) {
      console.error("Failed to fetch session measurements:", err);
      state.sessionMeasurements = [];
      state.measurementCache.clear();
      renderSurveyProgress();
      renderHeatmap();
      if (state.selectedCell) {
        updateSelectionPanel(state.selectedCell);
      }
    }
  }

  /**
   * Compute dynamic min/max scale across latest numeric values for selected metric.
   */
  function calculateScale(numericValues) {
    if (!numericValues || numericValues.length === 0) {
      return { hasData: false, min: null, max: null, isSingleValue: false };
    }

    let min = numericValues[0];
    let max = numericValues[0];
    for (let i = 1; i < numericValues.length; i++) {
      if (numericValues[i] < min) min = numericValues[i];
      if (numericValues[i] > max) max = numericValues[i];
    }

    const isSingleValue = min === max;
    return { hasData: true, min, max, isSingleValue };
  }

  /**
   * Normalize numeric value to t in [0, 1] based on session-relative scale and metric polarity.
   */
  function normalizeValue(value, min, max, isHigherBetter) {
    if (min === null || max === null || min === max) {
      return 0.5; // Single-value midpoint
    }

    const range = max - min;
    if (range <= 0) {
      return 0.5;
    }

    let t = isHigherBetter ? (value - min) / range : (max - value) / range;
    if (t < 0) t = 0;
    if (t > 1) t = 1;
    return t;
  }

  /**
   * Continuous purple-to-bright-green heatmap ramp, passing through teal.
   */
  function getHeatmapColor(t) {
    const colorStops = [
      { position: 0, color: [124, 85, 165] },
      { position: 0.5, color: [77, 182, 154] },
      { position: 1, color: [111, 220, 91] },
    ];
    const safeT = Math.max(0, Math.min(1, t));
    const upperIndex = colorStops.findIndex((stop) => stop.position >= safeT);
    const lower = colorStops[Math.max(0, upperIndex - 1)];
    const upper = colorStops[upperIndex < 0 ? colorStops.length - 1 : upperIndex];
    const localT = upper.position === lower.position
      ? 0
      : (safeT - lower.position) / (upper.position - lower.position);
    const [r, g, b] = lower.color.map((channel, index) =>
      Math.round(channel + (upper.color[index] - channel) * localT)
    );
    return `rgba(${r}, ${g}, ${b}, 0.85)`;
  }

  /**
   * Render the dynamic heatmap legend based on scale and metric configuration.
   */
  function renderLegend(metricCfg, scaleInfo) {
    if (elements.legendMetricLabel) {
      elements.legendMetricLabel.textContent = `${metricCfg.label} (${metricCfg.unit})`;
    }

    if (!scaleInfo.hasData) {
      if (elements.legendActiveBody) elements.legendActiveBody.style.display = "none";
      if (elements.legendEmptyMsg) elements.legendEmptyMsg.style.display = "block";
      return;
    }

    if (elements.legendActiveBody) elements.legendActiveBody.style.display = "flex";
    if (elements.legendEmptyMsg) elements.legendEmptyMsg.style.display = "none";

    if (scaleInfo.isSingleValue) {
      const formatted = metricCfg.format(scaleInfo.min);
      if (elements.legendMinVal) elements.legendMinVal.textContent = formatted;
      if (elements.legendMaxVal) elements.legendMaxVal.textContent = formatted;
    } else {
      if (metricCfg.isHigherBetter) {
        if (elements.legendMinVal) elements.legendMinVal.textContent = metricCfg.format(scaleInfo.min);
        if (elements.legendMaxVal) elements.legendMaxVal.textContent = metricCfg.format(scaleInfo.max);
      } else {
        if (elements.legendMinVal) elements.legendMinVal.textContent = metricCfg.format(scaleInfo.max);
        if (elements.legendMaxVal) elements.legendMaxVal.textContent = metricCfg.format(scaleInfo.min);
      }
    }
  }

  /**
   * Render the heatmap across all SVG cells using cached measurements and selected metric.
   */
  function renderHeatmap() {
    const metricCfg = METRIC_CONFIG[state.selectedMetric] || METRIC_CONFIG.rssi_dbm;

    // 1. Collect numeric values for current metric from latest measurement of each cell
    const numericValues = [];
    state.measurementCache.forEach((m) => {
      const rawVal = m[metricCfg.key];
      if (rawVal !== null && rawVal !== undefined && typeof rawVal === "number" && !Number.isNaN(rawVal)) {
        numericValues.push(rawVal);
      }
    });

    const scaleInfo = calculateScale(numericValues);

    // 2. Apply visualization state to all 60 grid cells
    state.cells.forEach((cellInfo) => {
      const key = getCellKey(cellInfo.floor, cellInfo.x, cellInfo.y);
      const m = state.measurementCache.get(key);
      const element = cellInfo.element;
      if (!element) return;

      if (!m) {
        // State 1: Unmeasured
        element.style.fill = "";
        element.classList.remove("cell-null");
        element.classList.add("cell-unmeasured");
      } else {
        const rawVal = m[metricCfg.key];
        if (rawVal === null || rawVal === undefined || typeof rawVal !== "number" || Number.isNaN(rawVal)) {
          // State 2: Measured Null (N/A)
          element.style.fill = "rgba(100, 116, 139, 0.35)";
          element.classList.remove("cell-unmeasured");
          element.classList.add("cell-null");
        } else {
          // State 3: Measured Numeric (including 0.0)
          element.classList.remove("cell-unmeasured");
          element.classList.remove("cell-null");
          const t = normalizeValue(rawVal, scaleInfo.min, scaleInfo.max, metricCfg.isHigherBetter);
          element.style.fill = getHeatmapColor(t);
        }
      }
    });

    // 3. Render dynamic legend
    renderLegend(metricCfg, scaleInfo);
  }

  /**
   * Handle session creation via POST /sessions.
   */
  async function handleCreateSession(evt) {
    evt.preventDefault();
    clearSessionMsg();

    const sessionId = elements.newSessionId ? elements.newSessionId.value.trim() : "";
    const name = elements.newSessionName ? elements.newSessionName.value.trim() : "";
    const floor = elements.newSessionFloor ? elements.newSessionFloor.value.trim() : "Floor-1";

    if (!sessionId || !name || !floor) {
      showSessionMsg("Please provide non-empty Session ID and Name.", "error");
      return;
    }

    try {
      const payload = { session_id: sessionId, name, floor, notes: null };
      const response = await fetch("/sessions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      if (!response.ok) {
        const errJson = await response.json().catch(() => ({}));
        const detail = errJson.detail || `HTTP ${response.status} ${response.statusText}`;
        throw new Error(detail);
      }

      const created = await response.json();
      showSessionMsg(`Session '${created.session_id}' created successfully!`, "success");

      // Add to session list and activate
      state.sessions.unshift(created);
      populateSessionDropdown(state.sessions);
      await setActiveSession(created.session_id);

      // Reset form
      if (elements.newSessionId) elements.newSessionId.value = "";
      if (elements.newSessionName) elements.newSessionName.value = "";
    } catch (err) {
      console.error("Failed to create session:", err);
      showSessionMsg(`Creation failed: ${err.message}`, "error");
    }
  }

  /**
   * Validate individual grid cell metadata from SVG data attributes.
   */
  function parseAndValidateCell(cell) {
    const cellId = cell.dataset.cellId || cell.id;
    const floor = cell.dataset.floor;
    const x = Number.parseFloat(cell.dataset.x);
    const y = Number.parseFloat(cell.dataset.y);
    const row = Number.parseInt(cell.dataset.row, 10);
    const col = Number.parseInt(cell.dataset.col, 10);

    if (!cellId) {
      return { isValid: false, error: "Cell missing ID attribute" };
    }
    if (!floor) {
      return { isValid: false, error: `Cell ${cellId} missing data-floor` };
    }
    if (Number.isNaN(x) || !Number.isFinite(x)) {
      return { isValid: false, error: `Cell ${cellId} has invalid data-x: ${cell.dataset.x}` };
    }
    if (Number.isNaN(y) || !Number.isFinite(y)) {
      return { isValid: false, error: `Cell ${cellId} has invalid data-y: ${cell.dataset.y}` };
    }
    if (Number.isNaN(row) || row < 1) {
      return { isValid: false, error: `Cell ${cellId} has invalid data-row: ${cell.dataset.row}` };
    }
    if (Number.isNaN(col) || col < 1) {
      return { isValid: false, error: `Cell ${cellId} has invalid data-col: ${cell.dataset.col}` };
    }

    return {
      isValid: true,
      metadata: { cellId, floor, x, y, row, col, element: cell },
    };
  }

  /**
   * Update the selection details panel with the selected cell's metadata and latest cached survey metrics.
   */
  function updateSelectionPanel(cellInfo) {
    if (!cellInfo) {
      if (elements.noSelectionMsg) elements.noSelectionMsg.style.display = "flex";
      if (elements.cellDetailsContainer) elements.cellDetailsContainer.style.display = "none";
      if (elements.cellHistorySection) elements.cellHistorySection.style.display = "none";
      updateMeasureButtonState();
      return;
    }

    if (elements.noSelectionMsg) elements.noSelectionMsg.style.display = "none";
    if (elements.cellDetailsContainer) elements.cellDetailsContainer.style.display = "flex";
    if (elements.cellHistorySection) elements.cellHistorySection.style.display = "flex";

    if (elements.fieldCellId) elements.fieldCellId.textContent = cellInfo.cellId;
    if (elements.fieldFloor) elements.fieldFloor.textContent = cellInfo.floor;
    if (elements.fieldX) elements.fieldX.textContent = cellInfo.x.toFixed(1);
    if (elements.fieldY) elements.fieldY.textContent = cellInfo.y.toFixed(1);
    if (elements.fieldRow) elements.fieldRow.textContent = String(cellInfo.row);
    if (elements.fieldCol) elements.fieldCol.textContent = String(cellInfo.col);

    // Latest session measurement details for this cell (M13)
    const key = getCellKey(cellInfo.floor, cellInfo.x, cellInfo.y);
    const m = state.measurementCache.get(key);

    if (!m) {
      if (elements.cellMeasuredStatusBadge) {
        elements.cellMeasuredStatusBadge.textContent = "Unmeasured";
        elements.cellMeasuredStatusBadge.className = "badge";
      }
      if (elements.cellMetricsList) elements.cellMetricsList.style.display = "none";
    } else {
      if (elements.cellMeasuredStatusBadge) {
        elements.cellMeasuredStatusBadge.textContent = "Measured";
        elements.cellMeasuredStatusBadge.className = "badge badge-persisted";
      }
      if (elements.cellMetricsList) elements.cellMetricsList.style.display = "flex";

      if (elements.cellCachedRssi) {
        elements.cellCachedRssi.textContent = m.rssi_dbm !== null ? `${Number(m.rssi_dbm).toFixed(1)} dBm` : "N/A";
      }
      if (elements.cellCachedSignal) {
        elements.cellCachedSignal.textContent = m.signal_percent !== null ? `${m.signal_percent}%` : "N/A";
      }
      if (elements.cellCachedLatency) {
        elements.cellCachedLatency.textContent = m.latency_ms !== null ? `${Number(m.latency_ms).toFixed(1)} ms` : "N/A";
      }
      if (elements.cellCachedPacketLoss) {
        elements.cellCachedPacketLoss.textContent = m.packet_loss_percent !== null ? `${Number(m.packet_loss_percent).toFixed(1)}%` : "N/A";
      }
      if (elements.cellCachedThroughput) {
        elements.cellCachedThroughput.textContent = m.throughput_mbps !== null ? `${Number(m.throughput_mbps).toFixed(1)} Mbps` : "N/A";
      }
      if (elements.cellCachedAp) {
        const ssidStr = m.ssid || "N/A";
        const bssidStr = m.bssid || "N/A";
        elements.cellCachedAp.textContent = `${ssidStr} (${bssidStr})`;
      }
      if (elements.cellCachedTimestamp) {
        elements.cellCachedTimestamp.textContent = m.timestamp || "N/A";
      }
      if (elements.cellCachedSamples) {
        elements.cellCachedSamples.textContent = `Samples: ${m.sample_count !== undefined && m.sample_count !== null ? m.sample_count : "N/A"}`;
      }
    }

    // Refresh selected-cell history (M14)
    renderCellHistory(cellInfo);

    updateMeasureButtonState();
  }

  /**
   * Select a grid cell element.
   */
  function handleCellSelection(cellId) {
    const cellInfo = state.cells.get(cellId);
    if (!cellInfo) {
      console.warn(`Attempted to select unknown cell: ${cellId}`);
      return;
    }

    if (state.selectedCell && state.selectedCell.cellId === cellId) {
      return;
    }

    // Deselect previous cell outline
    if (state.selectedCell && state.selectedCell.element) {
      state.selectedCell.element.classList.remove("selected");
    }

    // Select new cell outline
    cellInfo.element.classList.add("selected");
    state.selectedCell = cellInfo;

    updateSelectionPanel(cellInfo);
  }

  /**
   * Display a measurement error in the action area.
   */
  function showMeasureError(title, detail) {
    if (elements.measureErrorBanner) {
      if (elements.measureErrorTitle) elements.measureErrorTitle.textContent = title;
      if (elements.measureErrorDetail) elements.measureErrorDetail.textContent = detail;
      elements.measureErrorBanner.style.display = "block";
    }
  }

  /**
   * Hide measurement error banner.
   */
  function hideMeasureError() {
    if (elements.measureErrorBanner) {
      elements.measureErrorBanner.style.display = "none";
    }
  }

  /**
   * Render measurement result in the results panel.
   */
  function renderMeasurementResult(resultData) {
    if (!elements.resultPanel) return;

    hideMeasureError();
    elements.resultPanel.style.display = "block";

    const status = resultData.status || "UNKNOWN";
    const isSuccess = Boolean(resultData.is_successful);
    const isPersisted = Boolean(resultData.persisted);
    const m = resultData.measurement;

    // Status Badge
    if (elements.resultStatusBadge) {
      elements.resultStatusBadge.className = "badge";
      if (status === "COMPLETE") {
        elements.resultStatusBadge.textContent = "COMPLETE (5/5)";
        elements.resultStatusBadge.classList.add("badge-status-complete");
      } else if (status === "PARTIAL") {
        const validCount = resultData.valid_samples_count || 0;
        elements.resultStatusBadge.textContent = `PARTIAL (${validCount}/5)`;
        elements.resultStatusBadge.classList.add("badge-status-partial");
      } else {
        elements.resultStatusBadge.textContent = "FAILED (0/5)";
        elements.resultStatusBadge.classList.add("badge-status-failed");
      }
    }

    // Persisted Badge
    if (elements.resultPersistedBadge) {
      if (isPersisted) {
        elements.resultPersistedBadge.textContent = "Persisted";
        elements.resultPersistedBadge.className = "badge badge-persisted";
        elements.resultPersistedBadge.style.display = "inline-block";
      } else {
        elements.resultPersistedBadge.textContent = "Not Persisted";
        elements.resultPersistedBadge.className = "badge";
        elements.resultPersistedBadge.style.display = "inline-block";
      }
    }

    // Metrics (Strict null fidelity: never convert null to 0)
    if (elements.resultRssi) {
      elements.resultRssi.textContent = m && m.rssi_dbm !== null ? `${m.rssi_dbm} dBm` : "N/A";
    }
    if (elements.resultSignal) {
      elements.resultSignal.textContent = m && m.signal_percent !== null ? `${m.signal_percent}% quality` : "N/A";
    }
    if (elements.resultLatency) {
      elements.resultLatency.textContent = m && m.latency_ms !== null ? m.latency_ms.toFixed(1) : "N/A";
    }
    if (elements.resultPacketLoss) {
      elements.resultPacketLoss.textContent = m && m.packet_loss_percent !== null ? `${m.packet_loss_percent.toFixed(1)}%` : "N/A";
    }
    if (elements.resultThroughput) {
      elements.resultThroughput.textContent = m && m.throughput_mbps !== null ? m.throughput_mbps.toFixed(1) : "N/A";
    }

    // Details List
    if (elements.resultId) {
      elements.resultId.textContent = m && m.id ? `#${m.id}` : "--";
    }
    if (elements.resultSession) {
      elements.resultSession.textContent = resultData.session_id || "--";
    }
    if (elements.resultCoords) {
      elements.resultCoords.textContent = `${resultData.floor} (x=${resultData.x}, y=${resultData.y})`;
    }
    if (elements.resultSsid) {
      elements.resultSsid.textContent = m && m.ssid ? m.ssid : "N/A";
    }
    if (elements.resultBssid) {
      elements.resultBssid.textContent = m && m.bssid ? m.bssid : "N/A";
    }
    if (elements.resultRoaming) {
      if (resultData.bssid_changed) {
        elements.resultRoaming.textContent = `Yes (${(resultData.bssids_observed || []).length} APs)`;
      } else {
        elements.resultRoaming.textContent = "No (Stable)";
      }
    }
    if (elements.resultTimestamp) {
      const tsStr = m && m.timestamp ? m.timestamp : new Date().toISOString();
      elements.resultTimestamp.textContent = tsStr;
    }

    // Diagnostic error message
    if (resultData.error_message) {
      if (elements.resultErrorContainer) elements.resultErrorContainer.style.display = "flex";
      if (elements.resultErrorMsg) elements.resultErrorMsg.textContent = resultData.error_message;
    } else {
      if (elements.resultErrorContainer) elements.resultErrorContainer.style.display = "none";
    }
  }

  /**
   * Trigger active 5-sample measurement via POST /measurements/measure.
   */
  async function triggerMeasurement() {
    if (!state.activeSessionId) {
      showMeasureError("No Active Session", "Please select or create an active survey session before measuring.");
      return;
    }
    if (!state.selectedCell) {
      showMeasureError("No Cell Selected", "Please click a grid cell on the floor plan to measure.");
      return;
    }
    if (state.isMeasuring) {
      return;
    }

    state.isMeasuring = true;
    updateMeasureButtonState();
    hideMeasureError();

    if (elements.measureLoadingIndicator) {
      elements.measureLoadingIndicator.style.display = "flex";
    }

    const payload = {
      session_id: state.activeSessionId,
      floor: state.selectedCell.floor,
      x: state.selectedCell.x,
      y: state.selectedCell.y,
    };

    try {
      const response = await fetch("/measurements/measure", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      if (response.status === 200 || response.status === 502) {
        const resultData = await response.json();
        renderMeasurementResult(resultData);

        // M14 Live Measurement Integration: merge persisted measurement into state.sessionMeasurements, cache, coverage, and heatmap
        if (resultData.measurement && resultData.persisted) {
          const m = resultData.measurement;
          // Duplicate append protection by measurement id
          const alreadyExists = state.sessionMeasurements.some((existing) => existing.id === m.id);
          if (!alreadyExists) {
            state.sessionMeasurements.push(m);
          }
          const key = getCellKey(m.floor, m.x, m.y);
          state.measurementCache.set(key, m);
          renderSurveyProgress();
          renderHeatmap();
          if (state.selectedCell) {
            updateSelectionPanel(state.selectedCell);
          }
        }
      } else {
        const errJson = await response.json().catch(() => ({}));
        const detail = errJson.detail || `HTTP ${response.status} ${response.statusText}`;
        showMeasureError(`Measurement Request Failed (HTTP ${response.status})`, detail);
      }
    } catch (err) {
      console.error("Measurement error:", err);
      showMeasureError("Network / Communication Error", `Failed to communicate with API server: ${err.message}`);
    } finally {
      state.isMeasuring = false;
      if (elements.measureLoadingIndicator) {
        elements.measureLoadingIndicator.style.display = "none";
      }
      updateMeasureButtonState();
    }
  }

  /**
   * Initialize grid interaction on the injected SVG DOM.
   */
  function initializeGridSelection(svgElement) {
    const cellElements = svgElement.querySelectorAll(".grid-cell");

    if (!cellElements || cellElements.length === 0) {
      displayGridError("Grid Initialization Failed", "No elements with class '.grid-cell' were found in the SVG floor plan.");
      return;
    }

    if (cellElements.length !== 60) {
      displayGridError(
        "Invalid Grid Geometry",
        `Expected 60 grid cells (10x6), but discovered ${cellElements.length} cells in the SVG.`
      );
      return;
    }

    state.cells.clear();
    const validationErrors = [];

    cellElements.forEach((cell) => {
      const result = parseAndValidateCell(cell);
      if (!result.isValid) {
        validationErrors.push(result.error);
        return;
      }

      const info = result.metadata;
      if (state.cells.has(info.cellId)) {
        validationErrors.push(`Duplicate cell ID detected: ${info.cellId}`);
        return;
      }

      state.cells.set(info.cellId, info);

      // Attach click event handler to the individual cell
      cell.addEventListener("click", function (evt) {
        evt.stopPropagation();
        handleCellSelection(info.cellId);
      });
    });

    if (validationErrors.length > 0) {
      displayGridError("Grid Metadata Validation Failed", validationErrors.join("<br>"));
      return;
    }

    state.svgLoaded = true;
    if (elements.status) {
      elements.status.textContent = "Active (60 cells ready)";
      elements.status.className = "status-indicator ready";
    }

    updateSelectionPanel(null);
    renderHeatmap();
  }

  /**
   * Load the static floor1.svg asset, parse it, and inject it into the container.
   */
  async function loadFloorPlan() {
    const svgUrl = "./floor1.svg";

    if (elements.status) {
      elements.status.textContent = "Loading SVG floor plan...";
    }

    try {
      const response = await fetch(svgUrl);
      if (!response.ok) {
        throw new Error(`HTTP ${response.status} ${response.statusText} loading ${svgUrl}`);
      }

      const svgText = await response.text();
      const parser = new DOMParser();
      const doc = parser.parseFromString(svgText, "image/svg+xml");

      const parserError = doc.querySelector("parsererror");
      if (parserError) {
        throw new Error(`XML Parser Error: ${parserError.textContent}`);
      }

      const svgElement = doc.querySelector("svg");
      if (!svgElement) {
        throw new Error("Parsed document does not contain an <svg> root element.");
      }

      if (elements.container) {
        elements.container.innerHTML = "";
        elements.container.appendChild(svgElement);
      }

      initializeGridSelection(svgElement);
    } catch (err) {
      console.error("Failed to load floor plan SVG:", err);
      displayGridError("Failed to Load Floor Plan", `Unable to load '${svgUrl}': ${err.message}`);
    }
  }

  /**
   * Initialize DOM event listeners.
   */
  function initializeEventListeners() {
    // Session selection change
    if (elements.sessionSelect) {
      elements.sessionSelect.addEventListener("change", function () {
        setActiveSession(elements.sessionSelect.value);
      });
    }

    // Metric selector: segmented button click delegation (Instant client-side re-render, zero API calls)
    const metricSelectorContainer = document.getElementById("metric-selector-container");
    if (metricSelectorContainer) {
      metricSelectorContainer.addEventListener("click", function (evt) {
        const btn = evt.target.closest("button[data-metric]");
        if (!btn) return;
        // Update aria-pressed on all sibling buttons
        metricSelectorContainer.querySelectorAll("button[data-metric]").forEach((b) => {
          b.setAttribute("aria-pressed", "false");
          b.classList.remove("seg-active");
        });
        btn.setAttribute("aria-pressed", "true");
        btn.classList.add("seg-active");
        state.selectedMetric = btn.dataset.metric;
        renderHeatmap();
      });
    } else if (elements.metricSelect) {
      // Fallback: legacy <select> if present
      elements.metricSelect.addEventListener("change", function () {
        state.selectedMetric = elements.metricSelect.value;
        renderHeatmap();
      });
    }

    // Toggle create session form (header button + sidebar alias button)
    function toggleCreateSessionForm() {
      if (!elements.createSessionForm) return;
      const isHidden = elements.createSessionForm.style.display === "none";
      elements.createSessionForm.style.display = isHidden ? "block" : "none";
      clearSessionMsg();
    }
    if (elements.toggleCreateSessionBtn) {
      elements.toggleCreateSessionBtn.addEventListener("click", toggleCreateSessionForm);
    }
    const toggleAlias = document.getElementById("toggle-create-session-btn-alias");
    if (toggleAlias) {
      toggleAlias.addEventListener("click", toggleCreateSessionForm);
    }

    // Cancel create session form
    if (elements.cancelCreateSessionBtn) {
      elements.cancelCreateSessionBtn.addEventListener("click", function () {
        if (elements.createSessionForm) {
          elements.createSessionForm.style.display = "none";
        }
        clearSessionMsg();
      });
    }

    // Create session form submission
    if (elements.createSessionForm) {
      elements.createSessionForm.addEventListener("submit", handleCreateSession);
    }

    // Measure button click
    if (elements.measureBtn) {
      elements.measureBtn.addEventListener("click", triggerMeasurement);
    }
  }

  /**
   * Initialize on DOM Ready
   */
  function init() {
    initializeEventListeners();
    loadFloorPlan();
    loadSessions();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  // Expose state and core helpers for inspection & testing
  window.__appState = state;
  window.__appHelpers = {
    calculateScale,
    normalizeValue,
    getHeatmapColor,
    getCellKey,
    buildMeasurementCache,
    renderHeatmap,
    calculateSurveyCoverage,
    renderSurveyProgress,
    renderCellHistory,
    METRIC_CONFIG,
  };
})();
