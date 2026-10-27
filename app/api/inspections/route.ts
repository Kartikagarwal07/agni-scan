import { NextRequest, NextResponse } from "next/server";
import { parseInspection, parsePagination, RequestValidationError, validationError } from "@/lib/api-core";
import {
  createInspection,
  InspectionStoreConfigurationError,
  InspectionStoreUnavailableError,
  listInspections,
} from "@/lib/inspections-store";

function internalError() {
  return NextResponse.json({ error: { code: "INTERNAL_ERROR", message: "Unexpected server error" } }, { status: 500 });
}

function storeError(error: unknown) {
  if (error instanceof InspectionStoreConfigurationError) {
    return NextResponse.json({ error: { code: "INSPECTION_STORE_NOT_CONFIGURED", message: error.message } }, { status: 503 });
  }
  if (error instanceof InspectionStoreUnavailableError) {
    return NextResponse.json({ error: { code: "INSPECTION_STORE_UNAVAILABLE", message: "Inspection storage is temporarily unavailable." } }, { status: 503 });
  }
  return internalError();
}

export async function GET(request: NextRequest) {
  try {
    const { limit, offset } = parsePagination(request.nextUrl.searchParams);
    const cellId = request.nextUrl.searchParams.get("cell_id");
    const inspections = await listInspections(cellId, limit, offset);
    return NextResponse.json({ ...inspections, limit, offset });
  } catch (error) {
    if (error instanceof RequestValidationError) return NextResponse.json(validationError(error.message), { status: 400 });
    return storeError(error);
  }
}

export async function POST(request: NextRequest) {
  const configuredToken = process.env.AGNI_SCAN_WRITE_TOKEN;
  const suppliedToken = request.headers.get("x-agni-scan-write-token");
  const localDemoMode = process.env.NODE_ENV !== "production" && !configuredToken;
  if (!localDemoMode && (!configuredToken || suppliedToken !== configuredToken)) {
    return NextResponse.json({ error: { code: "WRITE_NOT_AUTHORIZED", message: "Inspection writes require authorization." } }, { status: 403 });
  }

  try {
    const body: unknown = await request.json();
    return NextResponse.json(await createInspection(parseInspection(body)), { status: 201 });
  } catch (error) {
    if (error instanceof RequestValidationError || error instanceof SyntaxError) {
      return NextResponse.json(validationError(error instanceof Error ? error.message : undefined), { status: 400 });
    }
    return storeError(error);
  }
}
