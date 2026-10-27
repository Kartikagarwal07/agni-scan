// Browser-side client for the AGNI-SCAN API (docs/API_CONTRACT.md).
// Pure helpers live here so they can be unit tested with `node --test`.
import type { Inspection, InspectionResult, RiskCell, RiskCellProperties, RiskGrid, RiskLevel } from "@/lib/api-core";

export const RISK_LEVELS: readonly RiskLevel[] = ["high", "medium", "low", "unknown"];
export const INSPECTION_RESULTS: readonly InspectionResult[] = ["fire_evidence_found", "no_fire_evidence_found", "inconclusive"];
// The API accepts limit 1-100; these are the page sizes offered in the UI.
export const PAGE_SIZES = [10, 20, 50, 100] as const;
export const PRIORITY_PAGE_SIZE = 10;
export const NOTES_MAX_LENGTH = 1000;

export type GridFilters = { district: string; date: string; riskLevel: RiskLevel | "" };
export const EMPTY_FILTERS: GridFilters = { district: "", date: "", riskLevel: "" };

export type Health = { status: string; service: string };

export type PriorityItem = Pick<
  RiskCellProperties,
  "cell_id" | "district" | "risk_score" | "risk_level" | "evidence_completeness" | "verification_status" | "priority_rank"
>;
export type PriorityPage = { items: PriorityItem[]; total: number; limit: number; offset: number };
export type InspectionPage = { items: Inspection[]; total: number; limit: number; offset: number };
export type InspectionDraft = { cell_id: string; result: InspectionResult | ""; notes: string };

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

export function hasFilters(filters: GridFilters) {
  return filters.district !== "" || filters.date !== "" || filters.riskLevel !== "";
}

export function gridUrl(filters: GridFilters) {
  const params = new URLSearchParams();
  if (filters.district) params.set("district", filters.district);
  if (filters.date) params.set("date", filters.date);
  if (filters.riskLevel) params.set("risk_level", filters.riskLevel);
  const query = params.toString();
  return query ? `/api/grid?${query}` : "/api/grid";
}

export function cellUrl(cellId: string) {
  return `/api/grid/${encodeURIComponent(cellId)}`;
}

export function prioritiesUrl(district: string, offset: number, limit = PRIORITY_PAGE_SIZE) {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  if (district) params.set("district", district);
  return `/api/priorities?${params}`;
}

export function inspectionsUrl(cellId: string | null, offset: number, limit = PRIORITY_PAGE_SIZE) {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  if (cellId) params.set("cell_id", cellId);
  return `/api/inspections?${params}`;
}

/** Same rules as the backend's parseInspection; returns a message, or null when valid. */
export function inspectionDraftError(draft: InspectionDraft): string | null {
  if (!draft.cell_id) return "Select a cell first.";
  if (!INSPECTION_RESULTS.includes(draft.result as InspectionResult)) return "Choose an inspection result.";
  if (draft.notes.trim().length === 0) return "Notes are required.";
  if (draft.notes.length > NOTES_MAX_LENGTH) return `Notes must be at most ${NOTES_MAX_LENGTH} characters.`;
  return null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** Message from the contract's standard error object, or a generic one. */
export function errorFromResponse(status: number, body: unknown): ApiError {
  const error = isRecord(body) && isRecord(body.error) ? body.error : null;
  const code = typeof error?.code === "string" ? error.code : `HTTP_${status}`;
  const message = typeof error?.message === "string" ? error.message : `The API responded with HTTP ${status}.`;
  return new ApiError(status, code, message);
}

function invalid(what: string): never {
  throw new ApiError(200, "INVALID_RESPONSE", `The API returned ${what} that does not match the data contract.`);
}

function isPosition(value: unknown) {
  return Array.isArray(value) && value.length >= 2 && value.every((n) => typeof n === "number" && Number.isFinite(n));
}

export function parseCell(value: unknown): RiskCell {
  if (!isRecord(value) || value.type !== "Feature" || !isRecord(value.geometry) || !isRecord(value.properties)) {
    return invalid("a grid cell");
  }
  const { geometry, properties } = value;
  const rings = geometry.coordinates;
  if (
    geometry.type !== "Polygon" ||
    !Array.isArray(rings) ||
    rings.length === 0 ||
    !rings.every((ring) => Array.isArray(ring) && ring.length >= 4 && ring.every(isPosition)) ||
    typeof properties.cell_id !== "string" ||
    value.id !== properties.cell_id ||
    !RISK_LEVELS.includes(properties.risk_level as RiskLevel)
  ) {
    return invalid("a grid cell");
  }
  return value as RiskCell;
}

export function parseGrid(value: unknown): RiskGrid {
  if (!isRecord(value) || value.type !== "FeatureCollection" || !Array.isArray(value.features)) {
    return invalid("a grid");
  }
  return {
    type: "FeatureCollection",
    metadata: isRecord(value.metadata) ? value.metadata : {},
    features: value.features.map(parseCell),
  };
}

export function parsePriorities(value: unknown): PriorityPage {
  if (!isRecord(value) || !Array.isArray(value.items) || typeof value.total !== "number") {
    return invalid("a priority list");
  }
  return value as PriorityPage;
}

export function parseHealth(value: unknown): Health {
  if (!isRecord(value) || typeof value.status !== "string") return invalid("a health response");
  return { status: value.status, service: typeof value.service === "string" ? value.service : "" };
}

export function parseInspection(value: unknown): Inspection {
  if (
    !isRecord(value) ||
    typeof value.id !== "string" ||
    typeof value.cell_id !== "string" ||
    !INSPECTION_RESULTS.includes(value.result as InspectionResult) ||
    typeof value.notes !== "string" ||
    typeof value.created_at !== "string"
  ) {
    return invalid("an inspection");
  }
  return value as Inspection;
}

export function parseInspections(value: unknown): InspectionPage {
  if (!isRecord(value) || !Array.isArray(value.items) || typeof value.total !== "number") {
    return invalid("an inspection list");
  }
  return { ...(value as InspectionPage), items: value.items.map(parseInspection) };
}

export async function fetchJson<T>(
  url: string,
  parse: (body: unknown) => T,
  signal?: AbortSignal,
  init: RequestInit = {},
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(url, {
      ...init,
      signal,
      headers: { accept: "application/json", ...init.headers },
      cache: "no-store",
    });
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new ApiError(0, "NETWORK_ERROR", "Could not reach the AGNI-SCAN API. Check that the server is running.");
  }
  let body: unknown = null;
  try {
    body = await response.json();
  } catch {
    if (response.ok) throw new ApiError(response.status, "INVALID_RESPONSE", "The API returned a response that is not JSON.");
  }
  if (!response.ok) throw errorFromResponse(response.status, body);
  return parse(body);
}

/**
 * POST /api/inspections. The write token is only sent when given: the backend
 * requires it in production and accepts writes without it in local development.
 */
export function createInspection(draft: InspectionDraft, writeToken: string) {
  const headers: Record<string, string> = { "content-type": "application/json" };
  if (writeToken) headers["x-agni-scan-write-token"] = writeToken;
  return fetchJson("/api/inspections", parseInspection, undefined, {
    method: "POST",
    headers,
    body: JSON.stringify({ cell_id: draft.cell_id, result: draft.result, notes: draft.notes.trim() }),
  });
}

/** Distinct, sorted values of one property, for filter options. */
export function distinctValues(cells: readonly RiskCell[], key: "district" | "analysis_date") {
  return [...new Set(cells.map((cell) => cell.properties[key]))].sort();
}
