"use client";

import { parseGrid } from "@/lib/dashboard/api";
import { readProvenance } from "@/lib/dashboard/provenance";
import { useApi } from "./use-api";

/**
 * Site-wide data notice, built from GET /api/grid metadata. While it loads, or if
 * the API is unreachable, it never implies the data is real.
 */
export function DataNotice() {
  const { state } = useApi("/api/grid", parseGrid);

  let tone = "pending";
  let text = "Checking data provenance…";
  let detail = "";
  if (state.status === "error") {
    tone = "unknown";
    text = "Data provenance unavailable — treat everything shown as unverified demo data";
  } else if (state.status === "success") {
    const provenance = readProvenance(state.data.metadata);
    tone = provenance.kind;
    text = provenance.kind === "synthetic" ? "Demo · synthetic data — not real satellite observations" : provenance.headline;
    detail = ` · ${state.data.features.length} cells${provenance.analysisWindow ? ` · window ${provenance.analysisWindow}` : ""}`;
  }

  return (
    <p role="status" className={`site-notice site-notice_${tone}`}>
      {text}
      {detail && <span className="site-noticeDetail">{detail}</span>}
    </p>
  );
}
