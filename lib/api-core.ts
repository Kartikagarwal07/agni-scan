/**
 * AGNI-SCAN demo data only — it is deterministic fixture data, not satellite
 * observations or a scientifically validated probability of crop-residue burning.
 */
export const DEMO_DATA_NOTICE =
  "MOCK DATA — NOT REAL SATELLITE RESULTS. Risk scores are verification-priority heuristics.";

export type RiskLevel = "low" | "medium" | "high" | "unknown";
export type VerificationStatus =
  | "unverified"
  | "scheduled"
  | "verified_fire"
  | "verified_no_fire";

export type RiskCellProperties = {
  cell_id: string;
  district: string;
  risk_score: number | null;
  risk_level: RiskLevel;
  observed_fire_count: number;
  evidence_completeness: number;
  verification_status: VerificationStatus;
  analysis_date: string;
};

export type RiskCell = {
  type: "Feature";
  id: string;
  geometry: { type: "Polygon"; coordinates: number[][][] };
  properties: RiskCellProperties;
};

export type InspectionResult =
  | "fire_evidence_found"
  | "no_fire_evidence_found"
  | "inconclusive";

export type Inspection = {
  id: string;
  cell_id: string;
  result: InspectionResult;
  notes: string;
  created_at: string;
};

export const DEMO_GRID: readonly RiskCell[] = [
  {
    type: "Feature",
    id: "PB-001",
    geometry: { type: "Polygon", coordinates: [[[75.8, 30.9], [75.81, 30.9], [75.81, 30.91], [75.8, 30.91], [75.8, 30.9]]] },
    properties: { cell_id: "PB-001", district: "Ludhiana", risk_score: 82, risk_level: "high", observed_fire_count: 0, evidence_completeness: 0.75, verification_status: "unverified", analysis_date: "2026-10-26" },
  },
  {
    type: "Feature",
    id: "PB-002",
    geometry: { type: "Polygon", coordinates: [[[75.82, 30.9], [75.83, 30.9], [75.83, 30.91], [75.82, 30.91], [75.82, 30.9]]] },
    properties: { cell_id: "PB-002", district: "Ludhiana", risk_score: 61, risk_level: "medium", observed_fire_count: 0, evidence_completeness: 0.9, verification_status: "scheduled", analysis_date: "2026-10-26" },
  },
  {
    type: "Feature",
    id: "PB-003",
    geometry: { type: "Polygon", coordinates: [[[75.85, 30.92], [75.86, 30.92], [75.86, 30.93], [75.85, 30.93], [75.85, 30.92]]] },
    properties: { cell_id: "PB-003", district: "Patiala", risk_score: 34, risk_level: "low", observed_fire_count: 0, evidence_completeness: 0.65, verification_status: "verified_no_fire", analysis_date: "2026-10-26" },
  },
  {
    type: "Feature",
    id: "PB-004",
    geometry: { type: "Polygon", coordinates: [[[74.85, 31.63], [74.86, 31.63], [74.86, 31.64], [74.85, 31.64], [74.85, 31.63]]] },
    properties: { cell_id: "PB-004", district: "Amritsar", risk_score: null, risk_level: "unknown", observed_fire_count: 0, evidence_completeness: 0.2, verification_status: "unverified", analysis_date: "2026-10-25" },
  },
] as const;

export class RequestValidationError extends Error {}

export function parsePagination(searchParams: URLSearchParams) {
  const limit = parseInteger(searchParams.get("limit"), 20, 1, 100, "limit");
  const offset = parseInteger(searchParams.get("offset"), 0, 0, Number.MAX_SAFE_INTEGER, "offset");
  return { limit, offset };
}

function parseInteger(value: string | null, fallback: number, min: number, max: number, name: string) {
  if (value === null) return fallback;
  if (!/^\d+$/.test(value)) throw new RequestValidationError(`${name} must be an integer.`);
  const number = Number(value);
  if (number < min || number > max) throw new RequestValidationError(`${name} must be between ${min} and ${max}.`);
  return number;
}

export function requireDate(value: string | null) {
  if (value !== null && !/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    throw new RequestValidationError("date must use YYYY-MM-DD format.");
  }
  return value;
}

export function requireRiskLevel(value: string | null): RiskLevel | null {
  if (value === null) return null;
  if (!(["low", "medium", "high", "unknown"] as const).includes(value as RiskLevel)) {
    throw new RequestValidationError("risk_level must be low, medium, high, or unknown.");
  }
  return value as RiskLevel;
}

export function gridFor(searchParams: URLSearchParams) {
  const district = searchParams.get("district");
  const date = requireDate(searchParams.get("date"));
  const riskLevel = requireRiskLevel(searchParams.get("risk_level"));
  return DEMO_GRID.filter(({ properties }) =>
    (district === null || properties.district === district) &&
    (date === null || properties.analysis_date === date) &&
    (riskLevel === null || properties.risk_level === riskLevel),
  );
}

export function validationError(message = "Invalid request parameters") {
  return { error: { code: "VALIDATION_ERROR", message } };
}

export function notFoundError(message = "Resource not found") {
  return { error: { code: "NOT_FOUND", message } };
}

export function parseInspection(value: unknown): Pick<Inspection, "cell_id" | "result" | "notes"> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new RequestValidationError("Request body must be a JSON object.");
  }
  const body = value as Record<string, unknown>;
  const { cell_id, result, notes } = body;
  if (typeof cell_id !== "string" || !DEMO_GRID.some((cell) => cell.properties.cell_id === cell_id)) {
    throw new RequestValidationError("cell_id must identify an existing grid cell.");
  }
  if (!(["fire_evidence_found", "no_fire_evidence_found", "inconclusive"] as const).includes(result as InspectionResult)) {
    throw new RequestValidationError("result is not an allowed inspection result.");
  }
  if (typeof notes !== "string" || notes.trim().length === 0 || notes.length > 1000) {
    throw new RequestValidationError("notes must be a non-empty string of at most 1000 characters.");
  }
  return { cell_id, result: result as InspectionResult, notes: notes.trim() };
}
