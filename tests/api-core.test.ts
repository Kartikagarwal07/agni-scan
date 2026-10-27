import assert from "node:assert/strict";
import test from "node:test";
import { GRID_METADATA, gridFor, parseInspection, parsePagination, prioritiesFor, RequestValidationError, RISK_GRID } from "../lib/api-core.ts";

test("synthetic pipeline grid preserves provenance and shared feature invariants", () => {
  assert.equal(GRID_METADATA.synthetic, true);
  assert.equal(GRID_METADATA.data_provenance, "SYNTHETIC_DEMONSTRATION_NOT_REAL_SATELLITE_DATA");
  assert.ok(RISK_GRID.features.length > 0);
  for (const feature of RISK_GRID.features) {
    assert.equal(feature.id, feature.properties.cell_id);
    assert.equal(feature.geometry.type, "Polygon");
    const ring = feature.geometry.coordinates[0];
    assert.deepEqual(ring[0], ring[ring.length - 1]);
  }
});

test("grid filters and priority pagination use contract query parameters", () => {
  assert.equal(gridFor(new URLSearchParams("district=SYNTHETIC-DISTRICT-WEST")).length, 22);
  assert.equal(gridFor(new URLSearchParams("risk_level=high")).length, 1);
  assert.deepEqual(parsePagination(new URLSearchParams("limit=1&offset=2")), { limit: 1, offset: 2 });
  assert.throws(() => parsePagination(new URLSearchParams("limit=101")), RequestValidationError);
});

test("priority rank preserves a pipeline tie-break while older grids retain score ordering", () => {
  const cells = RISK_GRID.features.slice(0, 3).map((cell, index) => ({
    ...cell,
    properties: {
      ...cell.properties,
      cell_id: `CELL-${index + 1}`,
      risk_score: 50,
      priority_rank: [2, 1, undefined][index],
    },
    id: `CELL-${index + 1}`,
  }));
  assert.deepEqual(prioritiesFor(cells, null).map((item) => item.cell_id), ["CELL-2", "CELL-1", "CELL-3"]);

  const legacy = cells.map(({ properties, ...cell }) => ({
    ...cell,
    properties: { ...properties, priority_rank: undefined, risk_score: properties.cell_id === "CELL-3" ? 76 : 50 },
  }));
  assert.deepEqual(prioritiesFor(legacy, null).map((item) => item.cell_id), ["CELL-3", "CELL-1", "CELL-2"]);
});

test("inspection validation accepts only a pipeline cell and allowed result", () => {
  const cellId = RISK_GRID.features[0].properties.cell_id;
  assert.deepEqual(parseInspection({ cell_id: cellId, result: "inconclusive", notes: "  Demo field check  " }), {
    cell_id: cellId, result: "inconclusive", notes: "Demo field check",
  });
  assert.throws(() => parseInspection({ cell_id: "SYNTH-PB-999", result: "inconclusive", notes: "No cell" }), RequestValidationError);
  assert.throws(() => parseInspection({ cell_id: cellId, result: "other", notes: "No" }), RequestValidationError);
});
