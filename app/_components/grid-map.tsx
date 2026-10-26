import type { KeyboardEvent } from "react";
import type { RiskCell, RiskLevel } from "@/lib/api-core";
import { RISK_LEVELS } from "@/lib/dashboard/api";
import { formatScore, RISK_LABEL } from "@/lib/dashboard/format";
import { makeProjection, type Bounds } from "@/lib/dashboard/projection";

// "Unknown" is hatched so it never reads as a pale "low".
const RISK_FILL: Record<RiskLevel, string> = {
  high: "var(--risk-high)",
  medium: "var(--risk-medium)",
  low: "var(--risk-low)",
  unknown: "url(#unknown-hatch)",
};

type Props = {
  cells: readonly RiskCell[];
  bounds: Bounds;
  selectedId: string | null;
  onSelect: (cellId: string) => void;
};

export function GridMap({ cells, bounds, selectedId, onSelect }: Props) {
  const projection = makeProjection(bounds);
  const counts = Object.fromEntries(RISK_LEVELS.map((level) => [level, 0])) as Record<RiskLevel, number>;
  for (const cell of cells) counts[cell.properties.risk_level] += 1;

  const onKeyDown = (event: KeyboardEvent, cellId: string) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      onSelect(cellId);
    }
  };

  // Draw the selected cell last so neighbouring cells do not cover its outline.
  const ordered = [...cells].sort(
    (a, b) => Number(a.properties.cell_id === selectedId) - Number(b.properties.cell_id === selectedId),
  );

  return (
    <figure className="ag-mapWrap">
      <svg
        viewBox={`0 0 ${projection.width} ${projection.height}`}
        className="ag-map"
        role="group"
        aria-label={`Grid cells from the API, ${cells.length} shown. Select a cell for details.`}
      >
        <defs>
          <pattern id="unknown-hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <rect width="6" height="6" fill="var(--risk-unknown)" />
            <line x1="0" y1="0" x2="0" y2="6" stroke="var(--risk-unknown-line)" strokeWidth="2" />
          </pattern>
        </defs>
        {ordered.map((cell) => {
          const { cell_id, district, risk_level, risk_score } = cell.properties;
          const selected = cell_id === selectedId;
          const label = `${cell_id}, ${district}, ${RISK_LABEL[risk_level]} priority, score ${formatScore(risk_score)}`;
          return (
            <path
              key={cell_id}
              d={projection.path(cell.geometry.coordinates)}
              fill={RISK_FILL[risk_level]}
              fillRule="evenodd"
              stroke={selected ? "var(--foreground)" : "var(--surface)"}
              strokeWidth={selected ? 3 : 1}
              strokeLinejoin="round"
              className="ag-cell"
              role="button"
              tabIndex={0}
              aria-label={label}
              aria-pressed={selected}
              onClick={() => onSelect(cell_id)}
              onKeyDown={(event) => onKeyDown(event, cell_id)}
            >
              <title>{label}</title>
            </path>
          );
        })}
      </svg>
      <figcaption>
        <ul className="ag-legend" aria-label="Legend">
          {RISK_LEVELS.map((level) => (
            <li key={level}>
              <svg width="14" height="14" aria-hidden>
                <rect width="14" height="14" rx="2" fill={RISK_FILL[level]} stroke="var(--border)" />
              </svg>
              {RISK_LABEL[level]} ({counts[level]})
            </li>
          ))}
        </ul>
        <p className="ag-caption">
          Schematic plot of the polygon coordinates returned by <code>GET /api/grid</code>, north up. There is no
          basemap, and the plot makes no claim about real-world places.
        </p>
      </figcaption>
    </figure>
  );
}
