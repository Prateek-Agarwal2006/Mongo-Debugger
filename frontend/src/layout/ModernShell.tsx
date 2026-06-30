import type { ReactNode } from "react";
import { currentPath } from "@/lib/pageData";
import { StitchFooter } from "@/layout/StitchFooter";

const NAV = [
  { href: "/", label: "Home", icon: "⌂" },
  { href: "/runs", label: "Uploads", icon: "▤" },
  { href: "/upload", label: "Upload", icon: "↑" },
  { href: "/mcp-workarea", label: "MCP", icon: "⚡" },
  { href: "/docs", label: "API", icon: "{}" },
];

export function ThemeToggle({ compact = false }: { compact?: boolean }) {
  const theme = document.documentElement.dataset.appTheme ?? "classic";

  return (
    <div
      className={`app-theme-toggle${compact ? " app-theme-toggle--compact" : ""}`}
      role="radiogroup"
      aria-label="App appearance"
    >
      <button
        type="button"
        className={`app-theme-toggle__btn${theme === "classic" ? " is-active" : ""}`}
        aria-checked={theme === "classic"}
        onClick={() => window.applyAppTheme?.("classic")}
      >
        <span>Classic</span>
      </button>
      <button
        type="button"
        className={`app-theme-toggle__btn${theme === "modern" ? " is-active" : ""}`}
        aria-checked={theme === "modern"}
        onClick={() => window.applyAppTheme?.("modern")}
      >
        <span>Modern</span>
      </button>
    </div>
  );
}

export function ModernShell({ children }: { children: ReactNode }) {
  const path = currentPath();

  return (
    <div className="modern-app m-shell">
      <header className="m-nav">
        <a href="/" className="m-nav__brand">
          <span className="m-nav__icon">⬢</span>
          <span>FTDC Analyzer</span>
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
            <li>
              <ThemeToggle compact />
            </li>
          </ul>
        </nav>
      </header>
      <main className="m-main">{children}</main>
      <StitchFooter />
    </div>
  );
}
