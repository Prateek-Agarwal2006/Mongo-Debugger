/**
 * Shared Modern shell top nav + MCP WorkArea footer on all Stitch iframe pages.
 */
(function () {
  const LINKS = [
    {
      key: "uploads",
      href: "/runs",
      label: "Uploads",
      match: (path) => path === "/runs" || path.startsWith("/runs/"),
    },
    {
      key: "upload",
      href: "/upload",
      label: "Upload",
      match: (path) => path === "/upload",
    },
    {
      key: "mcp",
      href: "/mcp-workarea",
      label: "MCP WorkArea",
      match: (path) => path === "/mcp-workarea",
    },
    {
      key: "skill",
      href: "/skill-workarea",
      label: "Skill WorkArea",
      match: (path) => path === "/skill-workarea",
    },
  ];

  function appPath() {
    try {
      if (window.parent && window.parent !== window) {
        const parentPath = window.parent.location.pathname.replace(/\/$/, "") || "/";
        if (!parentPath.startsWith("/static/")) return parentPath;
      }
    } catch {
      /* cross-origin parent */
    }
    const path = window.location.pathname.replace(/\/$/, "") || "/";
    return path.startsWith("/static/") ? "/" : path;
  }

  function activeKey(path) {
    for (const link of LINKS) {
      if (link.match(path)) return link.key;
    }
    return null;
  }

  function linkHtml(link, active) {
    const cls = active ? "mdb-stitch-nav__link is-active" : "mdb-stitch-nav__link";
    return `<a class="${cls}" href="${link.href}" target="_top">${link.label}</a>`;
  }

  function renderNav() {
    const path = appPath();
    const active = activeKey(path);
    const linksHtml = LINKS.map((link) => linkHtml(link, link.key === active)).join("");

    return `<nav class="mdb-stitch-nav fixed top-0 w-full z-50 bg-[#faf9f5]/80 backdrop-blur-md border-b border-[#afb3ac]/30 shadow-sm" aria-label="Main">
<div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between gap-4">
<a href="/" target="_top" class="flex items-center gap-3 shrink-0 hover:opacity-90 transition-opacity" aria-label="Mongo Debugger home">
<span class="material-symbols-outlined text-[#C96442] text-3xl mdb-stitch-nav__logo">bug_report</span>
<span class="text-xl font-bold text-[#2f342e]">Mongo Debugger</span>
</a>
<div class="hidden md:flex items-center gap-6 text-sm font-medium">${linksHtml}</div>
<button type="button" class="mdb-stitch-nav__cta shrink-0" onclick="window.top.location.href='/upload'">Start analysis</button>
</div>
</nav>`;
  }

  function renderFooter() {
    return `<footer class="mdb-stitch-footer" aria-label="Site footer">
<div class="mdb-stitch-footer__inner">
<div class="mdb-stitch-footer__brand">
<span class="mdb-stitch-footer__name">Mongo Debugger</span>
<span class="mdb-stitch-footer__copy">© 2026 Mongo Debugger</span>
</div>
<div class="mdb-stitch-footer__links">
<a class="mdb-stitch-footer__link" href="/docs" target="_top" rel="noopener">API</a>
</div>
</div>
</footer>`;
  }

  function mountNav() {
    const mount = document.getElementById("mdb-stitch-nav-mount");
    const html = renderNav();
    if (mount) {
      mount.outerHTML = html;
      return;
    }
    document.body.insertAdjacentHTML("afterbegin", html);
  }

  function mountFooter() {
    const mount = document.getElementById("mdb-stitch-footer-mount");
    const html = renderFooter();
    if (mount) {
      mount.outerHTML = html;
      return;
    }
    document.body.insertAdjacentHTML("beforeend", html);
  }

  mountNav();
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", mountFooter);
  } else {
    mountFooter();
  }
})();
