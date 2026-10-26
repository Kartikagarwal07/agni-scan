"use client";

import dynamic from "next/dynamic";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  getGridCell,
  getGrid,
  getPriorities,
  getServiceHealth,
  type GridFeature,
  type PriorityItem,
  type RiskGrid,
  type RiskLevel,
} from "./lib/api";

const RiskMap = dynamic(() => import("./components/risk-map"), {
  ssr: false,
  loading: () => <div className="map-placeholder">Loading map renderer…</div>,
});

type AsyncState<T> =
  | { status: "loading" }
  | { status: "ready"; data: T }
  | { status: "error"; message: string };

type Filters = {
  district: string;
  riskLevel: string;
  date: string;
};

const riskLevels: RiskLevel[] = ["high", "medium", "low", "unknown"];
const emptyFeatures: GridFeature[] = [];
const loadingGrid: AsyncState<RiskGrid> = { status: "loading" };
const loadingPriorities: AsyncState<{ items: PriorityItem[]; total: number; limit: number; offset: number }> = {
  status: "loading",
};
const loadingCellDetail: AsyncState<GridFeature> = { status: "loading" };

function formatRiskLevel(level: string | null | undefined) {
  return level ? level[0].toUpperCase() + level.slice(1) : "Unavailable";
}

function formatVerificationStatus(status: string | null | undefined) {
  if (!status) return "Unavailable";
  return status.replaceAll("_", " ");
}

function apiErrorMessage(error: unknown) {
  return error instanceof Error ? error.message : "An unexpected API error occurred.";
}

function StatusPill({ status }: { status: "loading" | "connected" | "offline" }) {
  const label = status === "connected" ? "API connected" : status === "loading" ? "Checking API" : "API unavailable";
  return (
    <span className={`connection-pill ${status}`} role="status">
      <span className="connection-dot" />
      {label}
    </span>
  );
}

function MetricCard({
  label,
  value,
  note,
  icon,
  tone,
}: {
  label: string;
  value: string;
  note: string;
  icon: string;
  tone: string;
}) {
  return (
    <article className="metric-card">
      <div className="metric-top">
        <span className="metric-label">{label}</span>
        <span className={`metric-icon ${tone}`} aria-hidden="true">{icon}</span>
      </div>
      <div className="metric-value">{value}</div>
      <div className="metric-note"><span className="note-dash" />{note}</div>
    </article>
  );
}

function CellDetails({
  cellId,
  feature,
  priority,
  detailStatus,
}: {
  cellId: string | null;
  feature: GridFeature | null;
  priority: PriorityItem | null;
  detailStatus: AsyncState<GridFeature> | null;
}) {
  if (!cellId) {
    return (
      <div className="detail-empty" role="status">
        <span className="detail-empty-icon" aria-hidden="true">⌖</span>
        <strong>Select a grid cell</strong>
        <span>Choose a map polygon or priority row to inspect its contract fields.</span>
      </div>
    );
  }

  const properties = feature?.properties;
  const riskScore = properties?.risk_score ?? priority?.risk_score;
  const riskLevel = properties?.risk_level ?? priority?.risk_level;
  const evidence = properties?.evidence_completeness ?? priority?.evidence_completeness;
  const verificationStatus = properties?.verification_status ?? priority?.verification_status;
  const fieldValue = (value: string | number | null | undefined) =>
    value === null || value === undefined ? "Not supplied" : value;

  return (
    <div className="cell-details">
      <div className="selected-cell-label">SELECTED GRID CELL</div>
      <div className="selected-cell-id">{cellId}</div>
      {detailStatus?.status === "loading" && <p className="detail-fetch-note">Loading cell details…</p>}
      {detailStatus?.status === "error" && (
        <p className="detail-fetch-note error-text" role="status">
          Detail endpoint unavailable: {detailStatus.message}
        </p>
      )}
      <dl className="detail-list">
        <div><dt>District</dt><dd>{fieldValue(properties?.district ?? priority?.district)}</dd></div>
        <div>
          <dt>Risk score</dt>
          <dd>
            {riskScore === null || riskScore === undefined ? "Not supplied" : `${riskScore} / 100`}
            {riskLevel && <span className={`risk-chip ${riskLevel}`}>{formatRiskLevel(riskLevel)}</span>}
          </dd>
        </div>
        <div><dt>Observed fire detections</dt><dd>{fieldValue(properties?.observed_fire_count)}</dd></div>
        <div>
          <dt>Evidence completeness</dt>
          <dd>{evidence === undefined ? "Not supplied" : `${Math.round(evidence * 100)}%`}</dd>
        </div>
        <div><dt>Verification status</dt><dd className="status-value">{formatVerificationStatus(verificationStatus)}</dd></div>
        <div><dt>Analysis date</dt><dd>{fieldValue(properties?.analysis_date)}</dd></div>
      </dl>
      <p className="integrity-note">
        Risk scores prioritize verification; they are not probabilities of burning. A zero detection
        count does not establish that no burning occurred.
      </p>
    </div>
  );
}

function PriorityList({
  state,
  items,
  selectedCellId,
  onSelect,
}: {
  state: AsyncState<{ items: PriorityItem[]; total: number; limit: number; offset: number }>;
  items: PriorityItem[];
  selectedCellId: string | null;
  onSelect: (cellId: string) => void;
}) {
  if (state.status === "loading") {
    return <div className="list-state" role="status">Loading verification priorities…</div>;
  }
  if (state.status === "error") {
    return (
      <div className="list-state error-state" role="alert">
        <strong>Priorities could not be loaded</strong>
        <span>{state.message}</span>
      </div>
    );
  }
  if (state.data.total === 0) {
    return <div className="list-state">No priority candidates were returned by the API.</div>;
  }
  if (items.length === 0) {
    return <div className="list-state">No candidates match the selected risk level.</div>;
  }

  return (
    <>
      <div className="priority-list" role="list" aria-label="Verification priorities sorted by risk score">
        {items.map((item, index) => (
          <div role="listitem" key={item.cell_id}>
            <button
              className={`priority-row${selectedCellId === item.cell_id ? " selected" : ""}`}
              type="button"
              onClick={() => onSelect(item.cell_id)}
              aria-pressed={selectedCellId === item.cell_id}
            >
              <span className="priority-rank">{String(index + 1).padStart(2, "0")}</span>
              <span className="priority-main">
                <strong>{item.cell_id}</strong>
                <span>{item.district}</span>
              </span>
              <span className="priority-score">
                <strong>{item.risk_score ?? "—"}</strong>
                <span className={`risk-chip ${item.risk_level}`}>{formatRiskLevel(item.risk_level)}</span>
              </span>
              <span className={`priority-status ${item.verification_status}`}>
                {formatVerificationStatus(item.verification_status)}
              </span>
              <span className="priority-arrow" aria-hidden="true">↗</span>
            </button>
          </div>
        ))}
      </div>
      {state.data.total > state.data.limit && (
        <p className="pagination-note">
          Showing {items.length} of {state.data.total} API candidates. The contract allows up to 100 per request.
        </p>
      )}
    </>
  );
}

export default function Home() {
  const [filters, setFilters] = useState<Filters>({ district: "", riskLevel: "", date: "" });
  const [gridResult, setGridResult] = useState<{ key: string; value: AsyncState<RiskGrid> }>({
    key: "",
    value: loadingGrid,
  });
  const [priorityResult, setPriorityResult] = useState<{
    key: string;
    value: AsyncState<{ items: PriorityItem[]; total: number; limit: number; offset: number }>;
  }>({ key: "", value: loadingPriorities });
  const [healthResult, setHealthResult] = useState<{
    key: number;
    value: { status: "connected" | "offline"; message?: string };
  }>({
    key: -1,
    value: { status: "offline" },
  });
  const [selectedCellId, setSelectedCellId] = useState<string | null>(null);
  const [cellDetailResult, setCellDetailResult] = useState<{
    key: string;
    value: AsyncState<GridFeature>;
  } | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const requestKey = JSON.stringify([filters.district, filters.riskLevel, filters.date, reloadKey]);
  const detailRequestKey = JSON.stringify([selectedCellId, reloadKey]);
  const grid = gridResult.key === requestKey ? gridResult.value : loadingGrid;
  const priorities = priorityResult.key === requestKey ? priorityResult.value : loadingPriorities;
  const health =
    healthResult.key === reloadKey
      ? healthResult.value
      : { status: "loading" as const };
  const cellDetail =
    selectedCellId && cellDetailResult?.key === detailRequestKey
      ? cellDetailResult.value
      : selectedCellId
        ? loadingCellDetail
        : null;

  useEffect(() => {
    const controller = new AbortController();

    getGrid(filters, controller.signal).then(
      (data) => setGridResult({ key: requestKey, value: { status: "ready", data } }),
      (error: unknown) => {
        if (!controller.signal.aborted) {
          setGridResult({ key: requestKey, value: { status: "error", message: apiErrorMessage(error) } });
        }
      },
    );
    getPriorities({ district: filters.district }, controller.signal).then(
      (data) => setPriorityResult({ key: requestKey, value: { status: "ready", data } }),
      (error: unknown) => {
        if (!controller.signal.aborted) {
          setPriorityResult({ key: requestKey, value: { status: "error", message: apiErrorMessage(error) } });
        }
      },
    );

    return () => controller.abort();
  }, [filters, reloadKey, requestKey]);

  useEffect(() => {
    const controller = new AbortController();
    getServiceHealth(controller.signal).then(
      () => setHealthResult({ key: reloadKey, value: { status: "connected" } }),
      (error: unknown) => {
        if (!controller.signal.aborted) {
          setHealthResult({
            key: reloadKey,
            value: { status: "offline", message: apiErrorMessage(error) },
          });
        }
      },
    );
    return () => controller.abort();
  }, [reloadKey]);

  useEffect(() => {
    if (!selectedCellId) return;
    const controller = new AbortController();
    getGridCell(selectedCellId, controller.signal).then(
      (data) => setCellDetailResult({ key: detailRequestKey, value: { status: "ready", data } }),
      (error: unknown) => {
        if (!controller.signal.aborted) {
          setCellDetailResult({
            key: detailRequestKey,
            value: { status: "error", message: apiErrorMessage(error) },
          });
        }
      },
    );
    return () => controller.abort();
  }, [selectedCellId, reloadKey, detailRequestKey]);

  const gridFeatures = grid.status === "ready" ? grid.data.features : emptyFeatures;
  const priorityData = priorities.status === "ready" ? priorities.data : null;
  const priorityItems = useMemo(() => {
    if (!priorityData) return [];
    return priorityData.items
      .filter((item) => !filters.riskLevel || item.risk_level === filters.riskLevel)
      .toSorted((left, right) => {
        const scoreDifference = (right.risk_score ?? -1) - (left.risk_score ?? -1);
        return scoreDifference || left.cell_id.localeCompare(right.cell_id);
      });
  }, [filters.riskLevel, priorityData]);

  const districts = useMemo(
    () =>
      [...new Set([
        ...gridFeatures.map((feature) => feature.properties.district),
        ...(priorityData?.items.map((item) => item.district) ?? []),
      ])].sort((left, right) => left.localeCompare(right)),
    [gridFeatures, priorityData],
  );
  const dates = useMemo(
    () => [...new Set(gridFeatures.map((feature) => feature.properties.analysis_date))].sort().reverse(),
    [gridFeatures],
  );
  const latestDate = dates[0];
  const selectedFeature =
    (cellDetail?.status === "ready" ? cellDetail.data : null) ??
    gridFeatures.find((feature) => feature.properties.cell_id === selectedCellId) ??
    null;
  const selectedPriority = priorityData?.items.find((item) => item.cell_id === selectedCellId) ?? null;

  const handleSelectCell = useCallback((cellId: string) => setSelectedCellId(cellId), []);
  const handleDistrictChange = (value: string) => {
    setSelectedCellId(null);
    setFilters((current) => ({ ...current, district: value, date: "" }));
  };
  const handleRiskChange = (value: string) => {
    setSelectedCellId(null);
    setFilters((current) => ({ ...current, riskLevel: value }));
  };
  const handleDateChange = (value: string) => {
    setSelectedCellId(null);
    setFilters((current) => ({ ...current, date: value }));
  };

  const isLoading = grid.status === "loading" || priorities.status === "loading";
  const gridError = grid.status === "error";
  const cellCount = grid.status === "ready" ? grid.data.features.length : null;
  const highPriorityCount =
    grid.status === "ready" ? grid.data.features.filter((feature) => feature.properties.risk_level === "high").length : null;
  const detectionCount =
    grid.status === "ready"
      ? grid.data.features.reduce((total, feature) => total + feature.properties.observed_fire_count, 0)
      : null;
  const awaitingCount =
    grid.status === "ready"
      ? grid.data.features.filter((feature) =>
          ["unverified", "scheduled"].includes(feature.properties.verification_status),
        ).length
      : null;
  const metricValue = (value: number | null) =>
    value === null ? (isLoading ? "…" : "—") : value.toLocaleString();
  const dateLabel = filters.date || latestDate || "Awaiting data";

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <a className="brand" href="#overview" aria-label="AGNI-SCAN dashboard home">
          <span className="brand-mark"><span /></span>
          <span>
            <strong>AGNI<span className="brand-dash">·</span>SCAN</strong>
            <small>GEOSPATIAL INTELLIGENCE</small>
          </span>
        </a>
        <div className="workspace-label">WORKSPACE</div>
        <nav className="primary-nav" aria-label="Main navigation">
          <a className="nav-item active" href="#overview" aria-current="page"><span className="nav-icon">◫</span>Overview<span className="nav-active-dot" /></a>
          <a className="nav-item" href="#detection-gaps"><span className="nav-icon">◎</span>Detection gaps</a>
          <a className="nav-item" href="#risk-analysis"><span className="nav-icon">⌁</span>Risk analysis</a>
          <a className="nav-item" href="#verification-planning"><span className="nav-icon">↗</span>Verification planning</a>
        </nav>
        <div className="sidebar-bottom">
          <div className="region-card">
            <span className="region-kicker">ACTIVE REGION</span>
            <strong><span className="status-dot" />Punjab, India</strong>
            <small>Crop-residue monitoring</small>
          </div>
          <div className="sidebar-foot"><span className="status-ring" /> Contract v1.0.0 <span className="version">DEMO</span></div>
        </div>
      </aside>

      <section className="main-area" id="overview">
        <header className="topbar">
          <div className="breadcrumb"><span>AGNI-SCAN</span><span className="crumb-sep">/</span><strong>Overview</strong></div>
          <div className="topbar-right">
            <div className="header-date"><span>ANALYSIS DATE</span><strong>{dateLabel}</strong></div>
            <StatusPill status={health.status} />
          </div>
        </header>

        <div className="dashboard-content">
          <div className="page-heading">
            <div>
              <div className="eyebrow"><span className="eyebrow-line" /> PUNJAB · CROP RESIDUE MONITORING</div>
              <h1>Detection gap overview</h1>
              <p className="page-subtitle">Satellite-assisted mapping and field verification prioritization across Punjab.</p>
            </div>
            <div className={`demo-badge${health.status === "connected" ? " live" : ""}`}>
              <span className="demo-dot" />
              {health.status === "connected" ? "LIVE API DATA" : "DEMO MODE · NO SYNTHETIC DATA"}
            </div>
          </div>

          {health.status === "offline" && (
            <div className="demo-notice" role="status">
              <span className="notice-icon">i</span>
              <span><strong>Backend not connected.</strong> {health.message} Values remain blank until the documented API is available. No synthetic measurements are loaded.</span>
              <button className="retry-button" type="button" onClick={() => setReloadKey((key) => key + 1)}>Retry</button>
            </div>
          )}

          <section className="metrics-grid" aria-label="Live API summary metrics">
            <MetricCard label="Total grid cells" value={metricValue(cellCount)} note="Cells returned by the grid API" icon="▦" tone="blue" />
            <MetricCard label="High-priority cells" value={metricValue(highPriorityCount)} note="Risk category: high (70–100)" icon="△" tone="amber" />
            <MetricCard label="Observed fire detections" value={metricValue(detectionCount)} note="Observed count; not proof of absence" icon="◉" tone="orange" />
            <MetricCard label="Awaiting verification" value={metricValue(awaitingCount)} note="Unverified or scheduled cells" icon="↗" tone="green" />
          </section>

          <section className="panel map-panel" id="detection-gaps" aria-labelledby="map-title">
            <div className="panel-heading map-heading">
              <div>
                <div className="section-kicker">SPATIAL OVERVIEW</div>
                <h2 id="map-title">Punjab detection landscape</h2>
                <p className="panel-description">WGS84 GeoJSON cells from the documented grid endpoint.</p>
              </div>
              <div className="map-controls">
                <label className="select-wrap">
                  <span className="sr-only">Filter by district</span>
                  <select value={filters.district} onChange={(event) => handleDistrictChange(event.target.value)}>
                    <option value="">All districts</option>
                    {districts.map((district) => <option value={district} key={district}>{district}</option>)}
                  </select>
                  <span className="select-chevron" aria-hidden="true">⌄</span>
                </label>
                <label className="select-wrap">
                  <span className="sr-only">Filter by risk level</span>
                  <select value={filters.riskLevel} onChange={(event) => handleRiskChange(event.target.value)}>
                    <option value="">All risk levels</option>
                    {riskLevels.map((level) => <option value={level} key={level}>{formatRiskLevel(level)}</option>)}
                  </select>
                  <span className="select-chevron" aria-hidden="true">⌄</span>
                </label>
                <label className="select-wrap">
                  <span className="sr-only">Filter by analysis date</span>
                  <select value={filters.date} onChange={(event) => handleDateChange(event.target.value)}>
                    <option value="">All analysis dates</option>
                    {dates.map((date) => <option value={date} key={date}>{date}</option>)}
                  </select>
                  <span className="select-chevron" aria-hidden="true">⌄</span>
                </label>
              </div>
            </div>

            <div className="map-stage">
              {grid.status === "ready" && grid.data.features.length > 0 ? (
                <RiskMap data={grid.data} selectedCellId={selectedCellId} onSelectCell={handleSelectCell} />
              ) : (
                <div className="map-placeholder" role={gridError ? "alert" : "status"}>
                  <span className="map-empty-icon" aria-hidden="true">⌖</span>
                  <strong>
                    {grid.status === "loading" ? "Loading risk grid" :
                      grid.status === "error" ? "Grid data unavailable" :
                        "No grid polygons returned"}
                  </strong>
                  <p>
                    {grid.status === "loading" ? "Requesting GeoJSON from GET /api/grid…" :
                      grid.status === "error" ? grid.message :
                        "The API returned an empty FeatureCollection. No boundary or cell locations are invented for this preview."}
                  </p>
                  <span className="map-empty-tag">NO GEOGRAPHIC LAYER WITHOUT API DATA</span>
                </div>
              )}
              <div className="map-legend" aria-label="Risk level legend">
                <span className="legend-title">RISK LEVEL</span>
                {riskLevels.map((level) => <span key={level}><i className={`legend-swatch ${level}`} />{formatRiskLevel(level)}</span>)}
              </div>
              <span className="map-attribution">Cell coordinates from API · WGS84 [longitude, latitude]</span>
            </div>
            <div className="filter-caption">
              <span className="filter-info" aria-hidden="true">ⓘ</span>
              {grid.status === "ready" ? `${grid.data.features.length} cells in the current grid response.` : "Filters use the documented API query parameters."}
              <span className="selected-filters">
                {filters.district || "All districts"} <b>·</b> {filters.riskLevel ? formatRiskLevel(filters.riskLevel) : "All risk levels"} <b>·</b> {filters.date || "All dates"}
              </span>
            </div>
          </section>

          <div className="insight-grid">
            <section className="panel detail-panel" aria-labelledby="detail-title">
              <div className="panel-heading compact-heading">
                <div><div className="section-kicker">CELL INSPECTOR</div><h2 id="detail-title">Selected cell details</h2></div>
                {selectedCellId && <span className="outline-badge">API DETAIL</span>}
              </div>
              <CellDetails
                cellId={selectedCellId}
                feature={selectedFeature}
                priority={selectedPriority}
                detailStatus={cellDetail}
              />
            </section>

            <section className="panel planning-panel" id="verification-planning" aria-labelledby="planning-title">
              <div className="panel-heading compact-heading">
                <div><div className="section-kicker">FIELD OPERATIONS</div><h2 id="planning-title">Verification priorities</h2></div>
                <span className="count-badge">
                  {priorities.status === "ready" ? `${priorityItems.length} shown` : priorities.status === "loading" ? "Loading" : "Unavailable"}
                </span>
              </div>
              <p className="panel-description">Ranked by risk score, highest first. A priority score is a verification heuristic, not a fire probability.</p>
              <PriorityList
                state={priorities}
                items={priorityItems}
                selectedCellId={selectedCellId}
                onSelect={handleSelectCell}
              />
              <div className="planning-foot" id="risk-analysis">
                <span>Contract thresholds: High 70–100 · Medium 40–69 · Low 0–39 · Unknown: no score</span>
                <span>Zero detections do not prove zero burning.</span>
              </div>
            </section>
          </div>

          {(grid.status === "error" || priorities.status === "error") && (
            <div className="api-error-summary" role="alert">
              <strong>Some live data could not be loaded.</strong>
              {grid.status === "error" && <span>Grid API: {grid.message}</span>}
              {priorities.status === "error" && <span>Priorities API: {priorities.message}</span>}
              <button className="retry-button" type="button" onClick={() => setReloadKey((key) => key + 1)}>Retry requests</button>
            </div>
          )}

          <footer className="page-footer">
            <span>AGNI-SCAN <b>·</b> {health.status === "connected" ? "Connected data" : "Demo preview · no synthetic records"}</span>
            <span>Risk scores prioritize verification; they do not establish burning.</span>
          </footer>
        </div>
      </section>
    </main>
  );
}
