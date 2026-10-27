import { NextRequest, NextResponse } from "next/server";
import { parsePagination, prioritiesFor, RequestValidationError, RISK_GRID, validationError } from "@/lib/api-core";

export function GET(request: NextRequest) {
  try {
    const { limit, offset } = parsePagination(request.nextUrl.searchParams);
    const district = request.nextUrl.searchParams.get("district");
    const items = prioritiesFor(RISK_GRID.features, district);
    return NextResponse.json({ items: items.slice(offset, offset + limit), total: items.length, limit, offset });
  } catch (error) {
    if (error instanceof RequestValidationError) return NextResponse.json(validationError(error.message), { status: 400 });
    return NextResponse.json({ error: { code: "INTERNAL_ERROR", message: "Unexpected server error" } }, { status: 500 });
  }
}
