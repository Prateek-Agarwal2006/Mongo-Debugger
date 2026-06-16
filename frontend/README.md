# Frontend (UI layer)

Bootstrap 5 + motion layer for Mongo Debugger. **All product logic lives in the FastAPI backend** (`backend/app/api/`, `backend/app/simagix/`).

| Path | Purpose |
|------|---------|
| `templates/` | Jinja2 pages served by `backend/app/web/routes.py` |
| `templates/swagger_ui.html` | Branded Swagger UI at `/docs` |
| `templates/redoc_ui.html` | Branded ReDoc at `/redoc` |
| `static/css/theme.css` | Brand theme on top of Bootstrap dark mode |
| `static/css/motion.css` | Lightweight scroll reveals, phase rail, glass cards |
| `static/css/report-viewer.css` | Interactive RCA report sections + causal chain |
| `static/js/swagger-docs.js` | `/docs` quick-jump cards → expand Swagger operations |
| `static/css/swagger-theme.css` | Swagger UI dark overrides |
| `static/js/motion.js` | Lightweight IO reveals on marketing pages |
| `static/js/scroll-3d.js` | Webflow-style 3D panel transitions (native scroll + rAF) |
| `static/css/scroll-3d.css` | Sticky panel deck, progress rail, causal chain rails |
| `static/js/report-viewer.js` | JSON report renderer, causal chain SVG, section nav |
| `static/js/phase-rail.js` | Sticky Phase A→B→C progress bar on run detail |
| `static/js/clarify-wizard.js` | Phase B one-question-at-a-time UI |
| `static/js/agent-chat.js` | Post-report chatbot — markdown render, mermaid, copy button |
| `static/css/clarify-chat.css` | Wizard dots + chat bubbles |
| `static/js/rca.js` | Phase 2 RCA panel (calls `/simagix/...` APIs) |
| `static/js/grafana.js` | Grafana load/links (calls `/simagix/runs/.../grafana/*`) |

**Motion stack:** Native scroll + `scroll-3d.js` (sticky panels, `rotateX`/`translateZ` deck transitions). No Lenis/smooth-scroll hijacking. Report JSON from `/phase2/reports/latest`.

To reskin the app later, replace files here only — no Phase 2 or pipeline changes required.
