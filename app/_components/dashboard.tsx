"use client";

import { useState, type ReactNode } from "react";
import type { RiskLevel } from "@/lib/api-core";
import {
  cellUrl,
  distinctValues,
  EMPTY_FILTERS,
  gridUrl,
  hasFilters,
  inspectionsUrl,
  parseCell,
  parseGrid,
  parseHealth,
  parseInspections,
  parsePriorities,
  prioritiesUrl,
  PRIORITY_PAGE_SIZE,
  RISK_LEVELS,
  type GridFilters,
  type Health,
} from "@/lib/dashboard/api";
import { RISK_LABEL } from "@/lib/dashboard/format";
import { boundsOf } from "@/lib/dashboard/projection";
import { readProvenance } from "@/lib/dashboard/provenance";
import { CellDetails } from "./cell-details";
import "./dashboard.css";
import { GridMap } from "./grid-map";
import { InspectionForm, InspectionList } from "./inspections-panel";
import { PriorityList } from "./priority-list";
import { ProvenanceBanner } from "./provenance-banner";
import { EmptyState, ErrorState, Loading } from "./status";
import { useApi, type ApiState } from "./use-api";

export function Dashboard() {
  const [filters, setFilters] = useState<GridFilters>(EMPTY_FILTERS);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [priorityOffset, setPriorityOffset] = useState(0);
  const [priorityLimit, setPriorityLimit] = useState(PRIORITY_PAGE_SIZE);
  const [inspectionOffset, setInspectionOffset] = useState(0);
  const [inspectionLimit, setInspectionLimit] = useState(PRIORITY_PAGE_SIZE);

  const health = useApi("/api/health", parseHealth);
  // The unfiltered grid supplies provenance metadata, filter options and a stable map extent.
  const fullGrid = useApi("/api/grid", parseGrid);
  const filtered = hasFilters(filters);
  const filteredGrid = useApi(filtered ? gridUrl(filters) : null, parseGrid);
  const priorities = useApi(prioritiesUrl(filters.district, priorityOffset, priorityLimit), parsePriorities);
  const cell = useApi(selectedId ? cellUrl(selectedId) : null, parseCell);
  // With no cell selected, GET /api/inspections lists inspections for all cells.
  const inspections = useApi(inspectionsUrl(selectedId, inspectionOffset, inspectionLimit), parseInspections);

  const shownGrid = filtered ? filteredGrid : fullGrid;
  const full = fullGrid.state.status === "success" ? fullGrid.state.data : null;
  const bounds = full ? boundsOf(full.features) : null;

  const updateFilter = (patch: Partial<GridFilters>) => {
    setFilters((current) => ({ ...current, ...patch }));
    if ("district" in patch) setPriorityOffset(0);
  };
  const selectCell = (cellId: string) => {
    setSelectedId(cellId);
    setInspectionOffset(0);
  };
  const clearFilters = () => {
    setFilters(EMPTY_FILTERS);
    setPriorityOffset(0);
  };

  return (
    <div className="ag-page">
      <header className="ag-header">
        <div>
          <h1 className="ag-title">AGNI-SCAN</h1>
          <p className="ag-muted">
            Crop-residue burning verification-priority dashboard
          </p>
        </div>
        <HealthBadge state={health.state} />
      </header>

      {fullGrid.state.status === "loading" && <Loading label="Loading data provenance…" />}
      {fullGrid.state.status === "error" && (
        <ErrorState title="Could not load the risk grid" error={fullGrid.state.error} onRetry={fullGrid.retry} />
      )}
      {full && <ProvenanceBanner provenance={readProvenance(full.metadata)} />}

      <section aria-label="Filters" className="ag-filters">
        <Select
          label="District"
          value={filters.district}
          options={full ? distinctValues(full.features, "district") : []}
          onChange={(district) => updateFilter({ district })}
          disabled={!full}
        />
        <Select
          label="Analysis date"
          value={filters.date}
          options={full ? distinctValues(full.features, "analysis_date") : []}
          onChange={(date) => updateFilter({ date })}
          disabled={!full}
        />
        <Select
          label="Risk level"
          value={filters.riskLevel}
          options={[...RISK_LEVELS]}
          optionLabel={(level) => RISK_LABEL[level as RiskLevel]}
          onChange={(riskLevel) => updateFilter({ riskLevel: riskLevel as RiskLevel | "" })}
          disabled={!full}
        />
        <button type="button" onClick={clearFilters} disabled={!filtered} className="ag-button">
          Clear filters
        </button>
      </section>

      <div className="ag-columns">
        <Panel title="Grid map">
          {shownGrid.state.status === "loading" && <Loading label="Loading grid cells…" />}
          {shownGrid.state.status === "error" && (
            <ErrorState title="Could not load grid cells" error={shownGrid.state.error} onRetry={shownGrid.retry} />
          )}
          {shownGrid.state.status === "success" &&
            (shownGrid.state.data.features.length === 0 || !bounds ? (
              <EmptyState title="No grid cells to show">
                {filtered ? "No cells match the selected filters." : "The API returned an empty grid."}
              </EmptyState>
            ) : (
              <GridMap
                cells={shownGrid.state.data.features}
                bounds={bounds}
                selectedId={selectedId}
                onSelect={selectCell}
              />
            ))}
        </Panel>

        <div className="ag-stack">
          <Panel title="Selected cell">
            <CellDetails state={cell.state} onRetry={cell.retry} />
          </Panel>

          <Panel
            title="Field inspections"
            note={selectedId ? "Recorded for the selected cell (GET /api/inspections?cell_id=…)." : "All recorded inspections. Select a cell to record one."}
          >
            {selectedId && (
              <InspectionForm
                key={selectedId}
                cellId={selectedId}
                onCreated={() => {
                  setInspectionOffset(0);
                  inspections.retry();
                }}
              />
            )}
            <InspectionList
              cellId={selectedId}
              state={inspections.state}
              onPage={setInspectionOffset}
              onLimit={(limit) => {
                setInspectionLimit(limit);
                setInspectionOffset(0);
              }}
              onRetry={inspections.retry}
            />
          </Panel>
        </div>
      </div>

      <Panel
        title="Verification priorities"
        note="Ranked by risk score from GET /api/priorities; cells without a score come last. Only the district filter applies here, because the API does not filter priorities by date or risk level."
      >
        <PriorityList
          state={priorities.state}
          selectedId={selectedId}
          onSelect={selectCell}
          onPage={setPriorityOffset}
          onLimit={(limit) => {
            setPriorityLimit(limit);
            setPriorityOffset(0);
          }}
          onRetry={priorities.retry}
        />
      </Panel>
    </div>
  );
}

function Panel({ title, note, children }: { title: string; note?: string; children: ReactNode }) {
  return (
    <section aria-label={title} className="ag-panel">
      <header className="ag-panelHeader">
        <h2 className="ag-panelTitle">{title}</h2>
        {note && <p className="ag-panelNote">{note}</p>}
      </header>
      {children}
    </section>
  );
}

type SelectProps = {
  label: string;
  value: string;
  options: string[];
  onChange: (value: string) => void;
  optionLabel?: (value: string) => string;
  disabled?: boolean;
};

function Select({ label, value, options, onChange, optionLabel = (v) => v, disabled }: SelectProps) {
  return (
    <label className="ag-field">
      {label}
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        disabled={disabled}
        className="ag-select"
      >
        <option value="">All</option>
        {options.map((option) => (
          <option key={option} value={option}>
            {optionLabel(option)}
          </option>
        ))}
      </select>
    </label>
  );
}

function HealthBadge({ state }: { state: ApiState<Health> }) {
  const online = state.status === "success" && state.data.status === "ok";
  const settled = state.status === "success" || state.status === "error";
  const [dot, text] = online
    ? ["ag-dotOk", "API online"]
    : settled
      ? ["ag-dotBad", "API unavailable"]
      : ["ag-pulse", "Checking API…"];
  return (
    <p role="status" className="ag-health">
      <span className={`ag-dot ${dot}`} aria-hidden />
      {text}
    </p>
  );
}
