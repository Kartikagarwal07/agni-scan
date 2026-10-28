import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /* config options here */
  experimental: {
    agentFeedback: true,
  },
  cacheComponents: true,
  partialPrefetching: true,
  // lib/api-core.ts reads the grid at runtime from AGNI_GRID_PATH, which file tracing cannot follow,
  // so ship both grids with the API routes.
  outputFileTracingIncludes: {
    "/api/**": ["./data-pipeline/demo/risk_grid.geojson", "./data-pipeline/output/real/risk_grid.geojson"],
  },
};

export default nextConfig;
