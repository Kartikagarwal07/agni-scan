export type RiskLevel = "low" | "medium" | "high" | "unknown";
export type VerificationStatus = "unverified" | "scheduled" | "verified_fire" | "verified_no_fire";

export type GridProperties = {
  cell_id: string;
  district: string;
  risk_score: number | null;
  risk_level: RiskLevel;
  observed_fire_count: number;
  evidence_completeness: number;
  verification_status: VerificationStatus;
  analysis_date: string;
};

export type GridPosition = [number, number, ...number[]];

export type GridFeature = {
  type: "Feature";
  id: string;
  geometry: {
    type: "Polygon";
    coordinates: GridPosition[][];
  };
  properties: GridProperties;
};

export type RiskGrid = {
  type: "FeatureCollection";
  features: GridFeature[];
};

export type PriorityItem = {
  cell_id: string;
  district: string;
  risk_score: number | null;
  risk_level: RiskLevel;
  evidence_completeness: number;
  verification_status: VerificationStatus;
};

export type PrioritiesResponse = {
  items: PriorityItem[];
  total: number;
  limit: number;
  offset: number;
};

export type GridFilters = {
  district: string;
  riskLevel: string;
  date: string;
};

export type PriorityFilters = {
  district: string;
};

const riskLevels: RiskLevel[] = ["low", "medium", "high", "unknown"];
const verificationStatuses: VerificationStatus[] = [
  "unverified",
  "scheduled",
  "verified_fire",
  "verified_no_fire",
];

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isRiskLevel(value: unknown): value is RiskLevel {
  return typeof value === "string" && riskLevels.includes(value as RiskLevel);
}

function isVerificationStatus(value: unknown): value is VerificationStatus {
  return typeof value === "string" && verificationStatuses.includes(value as VerificationStatus);
}

function isDate(value: unknown): value is string {
  return typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value);
}

function isRiskScore(value: unknown): value is number | null {
  return value === null || (typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= 100);
}

function isValidRiskPair(score: number | null, level: RiskLevel) {
  if (score === null) return level === "unknown";
  if (score >= 70) return level === "high";
  if (score >= 40) return level === "medium";
  return level === "low";
}

function isEvidenceCompleteness(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= 1;
}

function isPosition(value: unknown): value is GridPosition {
  if (!Array.isArray(value) || value.length < 2) return false;
  const [longitude, latitude] = value;
  return (
    typeof longitude === "number" &&
    Number.isFinite(longitude) &&
    longitude >= -180 &&
    longitude <= 180 &&
    typeof latitude === "number" &&
    Number.isFinite(latitude) &&
    latitude >= -90 &&
    latitude <= 90 &&
    value.every((coordinate) => typeof coordinate === "number" && Number.isFinite(coordinate))
  );
}

function parseGridFeature(value: unknown): GridFeature {
  if (!isRecord(value) || value.type !== "Feature" || typeof value.id !== "string") {
    throw new Error("Grid response contains an invalid GeoJSON Feature.");
  }

  if (
    !isRecord(value.geometry) ||
    value.geometry.type !== "Polygon" ||
    !Array.isArray(value.geometry.coordinates) ||
    !isRecord(value.properties)
  ) {
    throw new Error(`Grid feature ${value.id} must contain Polygon geometry and properties.`);
  }

  const { properties } = value;
  if (
    typeof properties.cell_id !== "string" ||
    properties.cell_id !== value.id ||
    typeof properties.district !== "string" ||
    !isRiskScore(properties.risk_score) ||
    !isRiskLevel(properties.risk_level) ||
    !isValidRiskPair(properties.risk_score, properties.risk_level) ||
    !Number.isInteger(properties.observed_fire_count) ||
    typeof properties.observed_fire_count !== "number" ||
    properties.observed_fire_count < 0 ||
    !isEvidenceCompleteness(properties.evidence_completeness) ||
    !isVerificationStatus(properties.verification_status) ||
    !isDate(properties.analysis_date)
  ) {
    throw new Error(`Grid feature ${value.id} does not match the shared data contract.`);
  }

  const rings: GridPosition[][] = [];
  for (const ring of value.geometry.coordinates) {
    if (!Array.isArray(ring) || ring.length < 4 || !ring.every(isPosition)) {
      throw new Error(`Grid feature ${value.id} contains an invalid Polygon ring.`);
    }
    const first = ring[0];
    const last = ring[ring.length - 1];
    if (first[0] !== last[0] || first[1] !== last[1]) {
      throw new Error(`Grid feature ${value.id} contains a Polygon ring that is not closed.`);
    }
    rings.push(ring);
  }
  if (rings.length === 0) throw new Error(`Grid feature ${value.id} does not contain a Polygon ring.`);

  return {
    type: "Feature",
    id: value.id,
    geometry: { type: "Polygon", coordinates: rings },
    properties: {
      cell_id: properties.cell_id,
      district: properties.district,
      risk_score: properties.risk_score,
      risk_level: properties.risk_level,
      observed_fire_count: properties.observed_fire_count,
      evidence_completeness: properties.evidence_completeness,
      verification_status: properties.verification_status,
      analysis_date: properties.analysis_date,
    },
  };
}

function parseGrid(value: unknown): RiskGrid {
  if (!isRecord(value) || value.type !== "FeatureCollection" || !Array.isArray(value.features)) {
    throw new Error("Grid response must be a GeoJSON FeatureCollection.");
  }
  const features = value.features.map(parseGridFeature);
  if (new Set(features.map((feature) => feature.id)).size !== features.length) {
    throw new Error("Grid response contains duplicate feature IDs.");
  }
  return { type: "FeatureCollection", features };
}

function parsePriorityItem(value: unknown): PriorityItem {
  if (
    !isRecord(value) ||
    typeof value.cell_id !== "string" ||
    typeof value.district !== "string" ||
    !isRiskScore(value.risk_score) ||
    !isRiskLevel(value.risk_level) ||
    !isValidRiskPair(value.risk_score, value.risk_level) ||
    !isEvidenceCompleteness(value.evidence_completeness) ||
    !isVerificationStatus(value.verification_status)
  ) {
    throw new Error("Priorities response contains an item that does not match the API contract.");
  }
  return {
    cell_id: value.cell_id,
    district: value.district,
    risk_score: value.risk_score,
    risk_level: value.risk_level,
    evidence_completeness: value.evidence_completeness,
    verification_status: value.verification_status,
  };
}

function parsePriorities(value: unknown): PrioritiesResponse {
  if (
    !isRecord(value) ||
    !Array.isArray(value.items) ||
    !Number.isInteger(value.total) ||
    !Number.isInteger(value.limit) ||
    !Number.isInteger(value.offset) ||
    (value.total as number) < 0 ||
    (value.limit as number) < 1 ||
    (value.offset as number) < 0
  ) {
    throw new Error("Priorities response does not match the documented pagination shape.");
  }
  return {
    items: value.items.map(parsePriorityItem),
    total: value.total as number,
    limit: value.limit as number,
    offset: value.offset as number,
  };
}

async function requestJson(url: string, signal?: AbortSignal): Promise<unknown> {
  const response = await fetch(url, {
    headers: { Accept: "application/json" },
    cache: "no-store",
    signal,
  });
  const body = await response.text();
  let parsed: unknown;

  try {
    parsed = JSON.parse(body);
  } catch {
    if (!response.ok) {
      throw new Error(`${url} returned HTTP ${response.status}; the response was not JSON.`);
    }
    throw new Error(`${url} returned a successful response that was not valid JSON.`);
  }

  if (!response.ok) {
    if (
      isRecord(parsed) &&
      isRecord(parsed.error) &&
      typeof parsed.error.message === "string"
    ) {
      const code = typeof parsed.error.code === "string" ? `${parsed.error.code}: ` : "";
      throw new Error(`${code}${parsed.error.message} (HTTP ${response.status})`);
    }
    throw new Error(`${url} returned HTTP ${response.status}.`);
  }
  return parsed;
}

export async function getGrid(filters: GridFilters, signal?: AbortSignal): Promise<RiskGrid> {
  const query = new URLSearchParams();
  if (filters.district) query.set("district", filters.district);
  if (filters.date) query.set("date", filters.date);
  if (filters.riskLevel) query.set("risk_level", filters.riskLevel);
  const suffix = query.size > 0 ? `?${query.toString()}` : "";
  return parseGrid(await requestJson(`/api/grid${suffix}`, signal));
}

export async function getPriorities(
  filters: PriorityFilters,
  signal?: AbortSignal,
): Promise<PrioritiesResponse> {
  const query = new URLSearchParams({ limit: "100", offset: "0" });
  if (filters.district) query.set("district", filters.district);
  return parsePriorities(await requestJson(`/api/priorities?${query.toString()}`, signal));
}

export async function getGridCell(cellId: string, signal?: AbortSignal): Promise<GridFeature> {
  return parseGridFeature(await requestJson(`/api/grid/${encodeURIComponent(cellId)}`, signal));
}

export async function getServiceHealth(signal?: AbortSignal): Promise<void> {
  const response = await requestJson("/api/health", signal);
  if (
    !isRecord(response) ||
    response.status !== "ok" ||
    response.service !== "agni-scan"
  ) {
    throw new Error("The health endpoint did not return the documented AGNI-SCAN response.");
  }
}
