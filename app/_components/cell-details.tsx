import type { ReactNode } from "react";
import type { RiskCell } from "@/lib/api-core";
import { formatCount, formatPercent, formatScore, RISK_LABEL, VERIFICATION_LABEL } from "@/lib/dashboard/format";
import { RiskBadge } from "./risk-badge";
import { EmptyState, ErrorState, Loading } from "./status";
import type { ApiState } from "./use-api";

export function CellDetails({ state, onRetry }: { state: ApiState<RiskCell>; onRetry: () => void }) {
  if (state.status === "idle") {
    return <EmptyState title="No cell selected">Select a cell on the map or in the priority list.</EmptyState>;
  }
  if (state.status === "loading") return <Loading label="Loading cell details…" />;
  if (state.status === "error") {
    const notFound = state.error.status === 404;
    return (
      <ErrorState
        title={notFound ? "Cell not found" : "Could not load cell details"}
        error={state.error}
        onRetry={notFound ? undefined : onRetry}
      />
    );
  }

  const p = state.data.properties;
  const rows: [string, ReactNode][] = [
    ["District", p.district],
    ["Risk level", <RiskBadge key="level" level={p.risk_level} />],
    ["Risk score", formatScore(p.risk_score)],
    ["Observed detections", formatCount(p.observed_fire_count, "detection")],
    ["Evidence completeness", formatPercent(p.evidence_completeness)],
    ["Verification status", VERIFICATION_LABEL[p.verification_status]],
    ["Analysis date", p.analysis_date],
  ];

  return (
    <div className="ag-details">
      <p className="ag-mono ag-small">{p.cell_id}</p>
      <dl className="ag-detailsList">
        {rows.map(([term, value]) => (
          <div key={term} style={{ display: "contents" }}>
            <dt>{term}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
      <ul className="ag-notes">
        <li>The risk score is a heuristic verification-priority score, not a probability of burning.</li>
        {p.risk_score === null && (
          <li>
            No score: the evidence is insufficient, so the level is {RISK_LABEL[p.risk_level]}. This is not the same
            as low risk.
          </li>
        )}
        {p.observed_fire_count === 0 && <li>Zero observed detections do not prove that no burning happened.</li>}
      </ul>
    </div>
  );
}
