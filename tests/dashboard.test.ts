import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import test from "node:test";
import {
  ApiError,
  cellUrl,
  createInspection,
  distinctValues,
  EMPTY_FILTERS,
  errorFromResponse,
  fetchJson,
  gridUrl,
  hasFilters,
  inspectionDraftError,
  inspectionsUrl,
  parseCell,
  parseGrid,
  parseInspections,
  parsePriorities,
  prioritiesUrl,
} from "../lib/dashboard/api.ts";
import { formatCount, formatPercent, formatScore, formatTimestamp } from "../lib/dashboard/format.ts";
import { boundsOf, makeProjection } from "../lib/dashboard/projection.ts";
import { readProvenance } from "../lib/dashboard/provenance.ts";

const demo = JSON.parse(readFileSync(join(process.cwd(), "data-pipeline", "demo", "risk_grid.geojson"), "utf8"));
const square = (lon: number, lat: number, size = 0.01) => [
  [[lon, lat], [lon + size, lat], [lon + size, lat + size], [lon, lat + size], [lon, lat]],
];
const cell = (overrides: Record<string, unknown> = {}) => ({
  type: "Feature",
  id: "C-1",
  geometry: { type: "Polygon", coordinates: square(75.8, 30.9) },
  properties: { cell_id: "C-1", district: "D", risk_score: null, risk_level: "unknown" },
  ...overrides,
});

test("query URLs follow the API contract parameter names", () => {
  assert.equal(gridUrl(EMPTY_FILTERS), "/api/grid");
  assert.equal(
    gridUrl({ district: "SYNTHETIC-DISTRICT-WEST", date: "2026-10-26", riskLevel: "unknown" }),
    "/api/grid?district=SYNTHETIC-DISTRICT-WEST&date=2026-10-26&risk_level=unknown",
  );
  assert.equal(gridUrl({ ...EMPTY_FILTERS, district: "A & B" }), "/api/grid?district=A+%26+B");
  assert.equal(cellUrl("SYNTH-PB/1 2"), "/api/grid/SYNTH-PB%2F1%202");
  assert.equal(prioritiesUrl("", 0), "/api/priorities?limit=10&offset=0");
  assert.equal(prioritiesUrl("West", 20, 5), "/api/priorities?limit=5&offset=20&district=West");
  assert.equal(hasFilters(EMPTY_FILTERS), false);
  assert.equal(hasFilters({ ...EMPTY_FILTERS, riskLevel: "high" }), true);
});

test("standard error objects become readable ApiErrors", () => {
  const err = errorFromResponse(400, { error: { code: "VALIDATION_ERROR", message: "date must use YYYY-MM-DD format." } });
  assert.deepEqual([err.status, err.code, err.message], [400, "VALIDATION_ERROR", "date must use YYYY-MM-DD format."]);
  const fallback = errorFromResponse(502, "<html>bad gateway</html>");
  assert.deepEqual([fallback.code, fallback.message], ["HTTP_502", "The API responded with HTTP 502."]);
});

test("the committed demo grid parses and keeps its metadata", () => {
  const grid = parseGrid(demo);
  assert.equal(grid.features.length, demo.features.length);
  assert.equal(grid.metadata.synthetic, true);
  assert.deepEqual(distinctValues(grid.features, "district"), ["SYNTHETIC-DISTRICT-EAST", "SYNTHETIC-DISTRICT-WEST"]);
  assert.deepEqual(distinctValues(grid.features, "analysis_date"), ["2026-10-26"]);
});

test("grid responses that break the contract are rejected", () => {
  const bad = [
    null,
    { type: "Feature" },
    { type: "FeatureCollection", features: [cell({ id: "other" })] },
    { type: "FeatureCollection", features: [cell({ geometry: { type: "MultiPolygon", coordinates: [square(75, 30)] } })] },
    { type: "FeatureCollection", features: [cell({ geometry: { type: "Polygon", coordinates: [[[75, 30], [76, 30]]] } })] },
    { type: "FeatureCollection", features: [cell({ properties: { cell_id: "C-1", risk_level: "severe" } })] },
  ];
  for (const value of bad) {
    assert.throws(() => parseGrid(value), (e: unknown) => e instanceof ApiError && e.code === "INVALID_RESPONSE");
  }
  assert.deepEqual(parseGrid({ type: "FeatureCollection", features: [] }).metadata, {});
  assert.equal(parseCell(cell()).id, "C-1");
  assert.throws(() => parsePriorities({ items: "x" }), ApiError);
});

test("provenance comes only from metadata and defaults to unknown", () => {
  const synthetic = readProvenance(demo.metadata);
  assert.equal(synthetic.kind, "synthetic");
  assert.match(synthetic.headline, /Synthetic demo data/);
  assert.match(synthetic.disclaimer ?? "", /NOT real satellite observations/);
  assert.match(synthetic.interpretation ?? "", /NOT a probability/);
  assert.equal(synthetic.analysisWindow, "2026-10-20 to 2026-10-26");

  assert.equal(readProvenance(undefined).kind, "unknown");
  assert.equal(readProvenance({}).kind, "unknown");
  assert.equal(readProvenance({ synthetic: false }).kind, "unknown", "unlabelled data is never shown as real");
  assert.equal(readProvenance({ data_provenance: "SYNTHETIC_DEMONSTRATION_NOT_REAL_SATELLITE_DATA" }).kind, "synthetic");
  const observed = readProvenance({
    synthetic: false,
    data_provenance: "PROCESSED_USER_SUPPLIED_FIRMS_OBSERVATIONS",
    warnings: ["w1"],
    contract_deviations: ["d1", 3],
  });
  assert.equal(observed.kind, "observed");
  assert.deepEqual(observed.notices, ["d1", "w1"]);
  assert.deepEqual(observed.credits, []);

  assert.deepEqual(synthetic.credits, [], "synthetic demo data credits no real source");
  const credited = readProvenance({ attribution: ["Fire detections: NASA FIRMS", "", 7, "Cropland: ESA WorldCover"] });
  assert.deepEqual(credited.credits, ["Fire detections: NASA FIRMS", "Cropland: ESA WorldCover"]);
});

test("projection fits API polygons north-up into the viewBox", () => {
  // Quarter-degree squares keep the arithmetic exact in binary floating point.
  const sw = square(75.5, 30.5, 0.25);
  const polygons = [{ geometry: { coordinates: sw } }, { geometry: { coordinates: square(75.75, 30.75, 0.25) } }];
  const bounds = boundsOf(polygons);
  assert.deepEqual(bounds, { minLon: 75.5, minLat: 30.5, maxLon: 76, maxLat: 31 });
  assert.equal(boundsOf([]), null);

  const projection = makeProjection(bounds!, 600, 10);
  const points = projection
    .path(sw)
    .match(/-?\d+\.\d+,-?\d+\.\d+/g)!
    .map((pair) => pair.split(",").map(Number));
  const [x0, y0] = points[0]; // south-west corner
  const [, y3] = points[3]; // north-west corner
  assert.equal(x0, 10);
  assert.ok(y3 < y0, "north is drawn above south");
  for (const [x, y] of points) assert.ok(x >= 10 && x <= 590 && y >= 0 && y <= projection.height);
  assert.ok(projection.path(sw).endsWith("Z"));
});

test("formatting never turns a missing score into zero", () => {
  assert.equal(formatScore(null), "No score");
  assert.equal(formatScore(0), "0");
  assert.equal(formatScore(76), "76");
  assert.equal(formatPercent(0.7), "70%");
  assert.equal(formatCount(1, "detection"), "1 detection");
  assert.equal(formatCount(0, "detection"), "0 detections");
});

test("fetchJson maps HTTP, network and parse failures to ApiError", async (t) => {
  const original = globalThis.fetch;
  t.after(() => {
    globalThis.fetch = original;
  });
  const respond = (body: string, status = 200) => {
    globalThis.fetch = async () => new Response(body, { status, headers: { "content-type": "application/json" } });
  };

  respond(JSON.stringify({ status: "ok", service: "agni-scan" }));
  assert.deepEqual(await fetchJson("/api/health", (b) => b), { status: "ok", service: "agni-scan" });

  respond(JSON.stringify({ error: { code: "NOT_FOUND", message: "Grid cell not found" } }), 404);
  await assert.rejects(fetchJson("/api/grid/x", parseCell), { status: 404, code: "NOT_FOUND", message: "Grid cell not found" });

  respond("not json");
  await assert.rejects(fetchJson("/api/grid", parseGrid), { code: "INVALID_RESPONSE" });

  globalThis.fetch = async () => {
    throw new TypeError("fetch failed");
  };
  await assert.rejects(fetchJson("/api/grid", parseGrid), { status: 0, code: "NETWORK_ERROR" });
});

const inspection = {
  id: "inspection-001",
  cell_id: "SYNTH-PB-5000M-N00681-E00118",
  result: "inconclusive",
  notes: "Demo field check",
  created_at: "2026-10-26T14:30:00.000Z",
};

test("inspection URLs and drafts follow the API contract", () => {
  assert.equal(inspectionsUrl(null, 0), "/api/inspections?limit=10&offset=0");
  assert.equal(inspectionsUrl("SYNTH-PB-1", 20, 50), "/api/inspections?limit=50&offset=20&cell_id=SYNTH-PB-1");

  const ok = { cell_id: "C-1", result: "fire_evidence_found" as const, notes: "Smoke seen" };
  assert.equal(inspectionDraftError(ok), null);
  assert.match(inspectionDraftError({ ...ok, cell_id: "" }) ?? "", /Select a cell/);
  assert.match(inspectionDraftError({ ...ok, result: "" }) ?? "", /Choose an inspection result/);
  assert.match(inspectionDraftError({ ...ok, notes: "   " }) ?? "", /Notes are required/);
  assert.match(inspectionDraftError({ ...ok, notes: "x".repeat(1001) }) ?? "", /at most 1000/);
  assert.equal(inspectionDraftError({ ...ok, notes: "x".repeat(1000) }), null);

  assert.equal(parseInspections({ items: [inspection], total: 1, limit: 10, offset: 0 }).items[0].id, "inspection-001");
  assert.throws(() => parseInspections({ items: [{ ...inspection, result: "maybe" }], total: 1 }), ApiError);
  assert.equal(formatTimestamp(inspection.created_at), "2026-10-26 14:30 UTC");
});

test("createInspection posts the contract body and sends the token only when given", async (t) => {
  const original = globalThis.fetch;
  t.after(() => {
    globalThis.fetch = original;
  });
  const calls: { url: string; init: RequestInit }[] = [];
  globalThis.fetch = async (url, init) => {
    calls.push({ url: String(url), init: init ?? {} });
    return new Response(JSON.stringify(inspection), { status: 201 });
  };

  const draft = { cell_id: inspection.cell_id, result: "inconclusive" as const, notes: "  Demo field check  " };
  assert.deepEqual(await createInspection(draft, ""), inspection);
  await createInspection(draft, "secret");

  assert.equal(calls[0].url, "/api/inspections");
  assert.equal(calls[0].init.method, "POST");
  assert.deepEqual(JSON.parse(String(calls[0].init.body)), {
    cell_id: inspection.cell_id,
    result: "inconclusive",
    notes: "Demo field check",
  });
  const headers0 = calls[0].init.headers as Record<string, string>;
  const headers1 = calls[1].init.headers as Record<string, string>;
  assert.equal(headers0["content-type"], "application/json");
  assert.equal("x-agni-scan-write-token" in headers0, false);
  assert.equal(headers1["x-agni-scan-write-token"], "secret");

  globalThis.fetch = async () =>
    new Response(JSON.stringify({ error: { code: "WRITE_NOT_AUTHORIZED", message: "Inspection writes require authorization." } }), {
      status: 403,
    });
  await assert.rejects(createInspection(draft, ""), { status: 403, code: "WRITE_NOT_AUTHORIZED" });
});
