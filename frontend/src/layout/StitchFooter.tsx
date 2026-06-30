/** Shared footer — matches MCP WorkArea / stitch-nav.js */
export function StitchFooter() {
  return (
    <footer className="mdb-stitch-footer" aria-label="Site footer">
      <div className="mdb-stitch-footer__inner">
        <div className="mdb-stitch-footer__brand">
          <span className="mdb-stitch-footer__name">Mongo Debugger</span>
          <span className="mdb-stitch-footer__copy">© 2026 Mongo Debugger</span>
        </div>
        <div className="mdb-stitch-footer__links">
          <a className="mdb-stitch-footer__link" href="/docs" target="_top" rel="noopener noreferrer">
            API
          </a>
        </div>
      </div>
    </footer>
  );
}
