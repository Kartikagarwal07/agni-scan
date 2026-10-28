// Reads the provenance metadata that GET /api/grid forwards from the data pipeline.
// Anything that is not explicitly labelled is shown as "unknown", never as real data.

export type ProvenanceKind = "synthetic" | "observed" | "unknown";

export type Provenance = {
  kind: ProvenanceKind;
  headline: string;
  disclaimer: string | null;
  interpretation: string | null;
  source: string | null;
  analysisWindow: string | null;
  notices: string[];
  /** Credits for the real data sources used (metadata.attribution); empty for synthetic data. */
  credits: string[];
};

const SYNTHETIC = "SYNTHETIC_DEMONSTRATION_NOT_REAL_SATELLITE_DATA";
const OBSERVED = "PROCESSED_USER_SUPPLIED_FIRMS_OBSERVATIONS";

function text(value: unknown) {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function strings(value: unknown) {
  return Array.isArray(value) ? value.filter((v): v is string => typeof v === "string" && v.trim() !== "") : [];
}

export function readProvenance(metadata: Record<string, unknown> | null | undefined): Provenance {
  const meta = metadata ?? {};
  const source = text(meta.data_provenance);
  const window = typeof meta.analysis_window === "object" && meta.analysis_window !== null
    ? (meta.analysis_window as Record<string, unknown>)
    : null;
  const start = text(window?.start_date);
  const end = text(window?.end_date);

  let kind: ProvenanceKind = "unknown";
  if (meta.synthetic === true || source === SYNTHETIC) kind = "synthetic";
  else if (meta.synthetic === false && source === OBSERVED) kind = "observed";

  const headline = {
    synthetic: "Synthetic demo data — not real satellite observations",
    observed: "Processed FIRMS observations (user-supplied files)",
    unknown: "Data provenance not provided — treat all values as unverified demo data",
  }[kind];

  return {
    kind,
    headline,
    disclaimer: text(meta.disclaimer),
    interpretation: text(meta.interpretation),
    source,
    analysisWindow: start && end ? `${start} to ${end}` : null,
    notices: [...strings(meta.contract_deviations), ...strings(meta.warnings)],
    credits: strings(meta.attribution),
  };
}
