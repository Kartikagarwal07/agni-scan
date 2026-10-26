import { NextRequest, NextResponse } from "next/server";
import { GRID_METADATA, gridFor, RequestValidationError, validationError } from "@/lib/api-core";

export function GET(request: NextRequest) {
  try {
    return NextResponse.json({ type: "FeatureCollection", metadata: GRID_METADATA, features: gridFor(request.nextUrl.searchParams) });
  } catch (error) {
    if (error instanceof RequestValidationError) return NextResponse.json(validationError(error.message), { status: 400 });
    return NextResponse.json({ error: { code: "INTERNAL_ERROR", message: "Unexpected server error" } }, { status: 500 });
  }
}
