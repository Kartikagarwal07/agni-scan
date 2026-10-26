import { Dashboard } from "./_components/dashboard";

// The page shell is static; all data is fetched in the browser from the /api routes,
// so the dashboard only ever shows what the API returns.
export default function Home() {
  return (
    <main>
      <Dashboard />
    </main>
  );
}
