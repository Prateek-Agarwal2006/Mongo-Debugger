# Frontend (UI layer)

Bootstrap 5 + motion layer for Mongo Debugger. **All product logic lives in the FastAPI backend** (`backend/app/api/`, `backend/app/simagix/`).

| Path | Purpose |
|------|---------|
| `templates/` | Jinja2 pages served by `backend/app/web/routes.py` |
| `templates/swagger_ui.html` | Branded Swagger UI at `/docs` |
| `templates/redoc_ui.html` | Branded ReDoc at `/redoc` |
| `static/css/theme.css` | Brand theme on top of Bootstrap dark mode |
| `static/unnamed.png` | Favicon / Apple touch icon (Sprinklr splash) |
| `static/css/agent-chat-stitch.css` | Post-report chatbot (Stitch Claude-like surface) |
| `static/css/tool-trace.css` | Agent tool activity table (Stitch Modern workspace) |
| `static/css/phase-rail.css` | Phase A→B→C rail (Stitch Modern workspace iframe) |
| `static/css/motion.css` | Lightweight scroll reveals, phase rail (Classic), glass cards |
| `static/css/report-viewer.css` | Interactive RCA report sections + causal chain (Classic theme) |
| `static/css/report-viewer-stitch.css` | Stitch Modern report tab — side nav, Lora body, confidence ring |
| `static/css/theme-modern.css` | Modern light theme — Mongo green, solid surfaces (perf-friendly) |
| `static/css/app-theme-toggle.css` | Classic / Modern pill toggle |
| `static/js/app-theme.js` | Global theme toggle + `localStorage` (`mdb-app-theme`) |
| `static/modern/` | Built Modern React shell (`npm run build` in `frontend/`) |
| `src/` | React pages: Home (DotGrid), Uploads, Upload |
| `static/js/swagger-docs.js` | `/docs` quick-jump cards → expand Swagger operations |
| `static/css/swagger-theme.css` | Swagger UI dark overrides |
| `static/js/motion.js` | Lightweight IO reveals on marketing pages |
| `static/js/scroll-3d.js` | Webflow-style 3D panel transitions (native scroll + rAF) |
| `static/css/scroll-3d.css` | Sticky panel deck, progress rail, causal chain rails |
| `static/js/report-viewer.js` | JSON report renderer — Classic (`rv-*`) or Stitch (`report-viewer--stitch`) |
| `static/js/phase-rail.js` | Sticky Phase A→B→C progress bar on run detail |
| `static/js/clarify-wizard.js` | Phase B one-question-at-a-time UI |
| `static/css/clarify-chat-stitch.css` | Stitch-themed Phase B progress dots + answer area |
| `static/js/agent-chat.js` | Post-report chatbot — markdown, mermaid, copy, file attachments |
| `static/css/clarify-chat.css` | Wizard dots + chat bubbles |
| `static/js/rca.js` | Phase 2 RCA panel (calls `/simagix/...` APIs) |
| `static/js/grafana.js` | Grafana load/links — first-visit auto-load, sessionStorage reload guard, debounced dashboard open |

**Motion stack:** Native scroll + `scroll-3d.js` (sticky panels, `rotateX`/`translateZ` deck transitions). No Lenis/smooth-scroll hijacking. Report JSON from `/phase2/reports/latest`.

To reskin the app later, replace files here only — no Phase 2 or pipeline changes required.

**Modern theme:** full React shell on Home, Uploads, and Upload. Run analysis / MCP pages use Classic UI. Lazy-loaded bundle when you pick Modern.

```bash
cd frontend && npm run build
```

## Google Stitch MCP (design → Modern UI)

Stitch designs can be pulled into Cursor and implemented under `frontend/src/`.

| Step | Action |
|------|--------|
| 1 | [Stitch settings](https://stitch.withgoogle.com/settings) → create **API key** (rotate any key exposed in chat) |
| 2 | `cp .env.example .env` → set `STITCH_API_KEY=...` (`.env` is gitignored) |
| 3 | `bash scripts/setup-stitch-mcp.sh` |
| 4 | Cursor **Settings → MCP** → toggle **stitch** → restart Cursor |
| 5 | Agent chat: *List my Stitch projects* |

Config: `.cursor/mcp.json` runs `scripts/stitch-mcp-proxy.sh` (sources `.env` → `@davideast/stitch-mcp proxy`).

**Skills installed** (`.agents/skills/`, 14 total):

| Skill | Use |
|-------|-----|
| `design-md` | Stitch project → `DESIGN.md` |
| `stitch-react-components` | Stitch screens → React in `frontend/src/` |
| `stitch-generate-design` | New/edit screens in Stitch from prompts |
| `enhance-prompt` | Polish Stitch prompts |
| `stitch-loop` | Multi-page site from one prompt |
| `stitch-code-to-design`, `stitch-upload-to-stitch`, … | See `.agents/skills/` |

Reinstall: `npx skills add google-labs-code/stitch-skills --yes`
