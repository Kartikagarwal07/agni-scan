import { Landing } from "./_components/landing/landing";
import { SiteNav } from "./_components/site-nav";

export default function Home() {
  return (
    <>
      <SiteNav current="home" />
      <main>
        <Landing />
      </main>
    </>
  );
}
