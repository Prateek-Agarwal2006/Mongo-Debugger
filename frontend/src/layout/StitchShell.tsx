import type { ReactNode } from "react";
import { currentPath } from "@/lib/pageData";
import { StitchFooter } from "@/layout/StitchFooter";

const NAV = [
  {
    href: "/runs",
    label: "Runs",
    match: (p: string) => p.startsWith("/runs") && p !== "/upload",
  },
  { href: "/upload", label: "Upload", match: (p: string) => p === "/upload" },
  { href: "/mcp-workarea", label: "MCP WorkArea", match: (p: string) => p === "/mcp-workarea" },
  {
    href: "/skill-workarea",
    label: "Skill WorkArea",
    match: (p: string) => p === "/skill-workarea",
  },
];

function navLinkClass(active: boolean) {
  if (active) {
    return "px-3 py-2 text-primary border-b-2 border-primary pb-1 font-medium";
  }
  return "px-3 py-2 text-on-surface-variant hover:text-primary transition-colors hover:bg-surface-container-low rounded-lg";
}

export function StitchShell({ children }: Readonly<{ children: ReactNode }>) {
  const path = currentPath();
  const isHome = path === "/";

  return (
    <div
      className={`${isHome ? "bg-transparent" : "bg-background"} text-on-surface selection:bg-primary-container selection:text-on-primary-container min-h-screen flex flex-col relative`}
    >
      <nav
        className="fixed top-0 w-full z-50 bg-surface/80 backdrop-blur-md border-b border-outline-variant/30 shadow-sm"
        aria-label="Main"
      >
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between gap-4">
          <a
            href="/"
            className="flex items-center gap-3 shrink-0 hover:opacity-90 transition-opacity"
            aria-label="Mongo Debugger home"
          >
            <span
              className="material-symbols-outlined text-accent text-3xl"
              style={{ fontVariationSettings: "FILL 1" }}
            >
              bug_report
            </span>
            <span className="text-xl font-headline font-bold text-on-surface">Mongo Debugger</span>
          </a>
          <div className="hidden md:flex items-center gap-6 text-sm font-medium">
            {NAV.map((item) => (
              <a key={item.href} href={item.href} className={navLinkClass(item.match(path))}>
                {item.label}
              </a>
            ))}
          </div>
          <a
            href="/upload"
            className="bg-accent hover:bg-[#b35636] text-white px-4 py-2 rounded-lg font-medium transition-opacity text-sm shrink-0"
          >
            Start analysis
          </a>
        </div>
      </nav>

      <main className="flex-grow pt-24 min-h-screen relative z-10">{children}</main>

      <StitchFooter />
    </div>
  );
}
