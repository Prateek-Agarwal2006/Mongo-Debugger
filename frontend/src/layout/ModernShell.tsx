import type { ReactNode } from "react";
import { currentPath } from "@/lib/pageData";
import { StitchFooter } from "@/layout/StitchFooter";

const NAV = [
  { href: "/", label: "Home", icon: "⌂" },
  { href: "/runs", label: "Runs", icon: "▤" },
  { href: "/upload", label: "Upload", icon: "↑" },
  { href: "/mcp-workarea", label: "MCP", icon: "⚡" },
  { href: "/docs", label: "API", icon: "{}" },
];

export function ModernShell({ children }: { children: ReactNode }) {
  const path = currentPath();

  return (
    <div className="modern-app m-shell">
      <header className="m-nav">
        <a href="/" className="m-nav__brand">
          <span className="m-nav__icon">⬢</span>
          <span>Mongo Debugger</span>
        </a>
        <nav>
          <ul className="m-nav__links">
            {NAV.map((item) => (
              <li key={item.href}>
                <a
                  href={item.href}
                  className={`m-nav__link${
                    item.href === "/runs" && path.startsWith("/runs") && path !== "/upload"
                      ? " is-active"
                      : path === item.href
                        ? " is-active"
                        : ""
                  }`}
                >
                  <span aria-hidden="true">{item.icon}</span>
                  {item.label}
                </a>
              </li>
            ))}
          </ul>
        </nav>
      </header>
      <main className="m-main">{children}</main>
      <StitchFooter />
    </div>
  );
}
