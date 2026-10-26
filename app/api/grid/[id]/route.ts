import { NextResponse } from "next/server";
import { notFoundError, RISK_GRID } from "@/lib/api-core";

export function GET(_: Request, { params }: { params: Promise<{ id: string }> }) {
  return params.then(({ id }) => {
    const cell = RISK_GRID.features.find((feature) => feature.properties.cell_id === id);
    return cell
      ? NextResponse.json(cell)
      : NextResponse.json(notFoundError("Grid cell not found"), { status: 404 });
  });
}
