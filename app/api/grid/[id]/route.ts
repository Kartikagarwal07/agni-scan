import { NextResponse } from "next/server";
import { DEMO_GRID, notFoundError } from "@/lib/api-core";

export function GET(_: Request, { params }: { params: Promise<{ id: string }> }) {
  return params.then(({ id }) => {
    const cell = DEMO_GRID.find((feature) => feature.properties.cell_id === id);
    return cell
      ? NextResponse.json(cell)
      : NextResponse.json(notFoundError("Grid cell not found"), { status: 404 });
  });
}
