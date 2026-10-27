import type { Metadata } from "next";
import { Dashboard } from "../_components/dashboard";
import { SiteNav } from "../_components/site-nav";

export const metadata: Metadata = {
  title: "Dashboard · AGNI-SCAN",
  description: "Verification priorities, grid cells, and field inspections with clearly labelled data provenance.",
};

// The page shell is static; all data is fetched in the browser from the /api routes,
// so the dashboard only ever shows what the API returns.
export default function DashboardPage() {
  return (
    <>
      <SiteNav current="dashboard" />
      <main>
        <Dashboard />
      </main>
    </>
  );
}
