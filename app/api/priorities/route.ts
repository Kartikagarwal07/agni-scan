import { NextRequest, NextResponse } from "next/server";
import { DEMO_GRID, parsePagination, RequestValidationError, validationError } from "@/lib/api-core";

export function GET(request: NextRequest) {
  try {
    const { limit, offset } = parsePagination(request.nextUrl.searchParams);
    const district = request.nextUrl.searchParams.get("district");
    const items = DEMO_GRID
      .filter((cell) => district === null || cell.properties.district === district)
      .map(({ properties }) => ({
        cell_id: properties.cell_id,
        district: properties.district,
        risk_score: properties.risk_score,
        risk_level: properties.risk_level,
        evidence_completeness: properties.evidence_completeness,
        verification_status: properties.verification_status,
      }))
      .sort((left, right) => (right.risk_score ?? -1) - (left.risk_score ?? -1));
    return NextResponse.json({ items: items.slice(offset, offset + limit), total: items.length, limit, offset });
  } catch (error) {
    if (error instanceof RequestValidationError) return NextResponse.json(validationError(error.message), { status: 400 });
    return NextResponse.json({ error: { code: "INTERNAL_ERROR", message: "Unexpected server error" } }, { status: 500 });
  }
}
