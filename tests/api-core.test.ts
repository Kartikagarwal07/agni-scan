import assert from "node:assert/strict";
import test from "node:test";
import { GRID_METADATA, gridFor, parseInspection, parsePagination, RequestValidationError, RISK_GRID } from "../lib/api-core.ts";

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

test("inspection validation accepts only a pipeline cell and allowed result", () => {
  const cellId = RISK_GRID.features[0].properties.cell_id;
  assert.deepEqual(parseInspection({ cell_id: cellId, result: "inconclusive", notes: "  Demo field check  " }), {
    cell_id: cellId, result: "inconclusive", notes: "Demo field check",
  });
  assert.throws(() => parseInspection({ cell_id: "SYNTH-PB-999", result: "inconclusive", notes: "No cell" }), RequestValidationError);
  assert.throws(() => parseInspection({ cell_id: cellId, result: "other", notes: "No" }), RequestValidationError);
});
