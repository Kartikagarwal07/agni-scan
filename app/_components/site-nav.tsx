import Link from "next/link";
import { DataNotice } from "./data-notice";

const SECTIONS = [
  { href: "/#problem", label: "Problem" },
  { href: "/#prioritise", label: "Prioritise" },
  { href: "/#verify", label: "Verify" },
];

export function SiteNav({ current }: { current: "home" | "dashboard" }) {
  return (
    <header className="site-header">
      <DataNotice />
      <nav className="site-nav" aria-label="Main">
        <Link href="/" className="site-wordmark" aria-current={current === "home" ? "page" : undefined}>
          AGNI-SCAN
        </Link>
        <ul className="site-links">
          {SECTIONS.map((section) => (
            <li key={section.href} className="site-sectionLink">
              <Link href={section.href}>{section.label}</Link>
            </li>
          ))}
          <li>
            <Link
              href="/dashboard"
              className="site-cta"
              aria-current={current === "dashboard" ? "page" : undefined}
            >
              Dashboard
            </Link>
          </li>
        </ul>
      </nav>
    </header>
  );
}
