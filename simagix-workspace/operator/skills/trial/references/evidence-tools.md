# MCP evidence tools (built-in)

Mongo Debugger always attaches **simagix-evidence** on the run page. Optional connectors from MCP WorkArea merge at RCA click time.

## Built-in retrieval pattern

1. Start from bundle summary / tier-1 JSON paths.
2. Request **metric slices** for a specific window and metric family — not whole-file dumps.
3. If MongoDB logs were parsed, use Hatchet tier tools for line-level patterns tied to windows.

## Optional operator MCPs

Connectors configured in **MCP WorkArea** appear as run-page checkboxes. They apply when you click **Run RCA** or submit clarifications — stateless per click.

## web_fetch policy

Only trusted HTTPS URLs per `PHASE2_WEB_FETCH_*` env. Prefer bundle + MCP over arbitrary web pages.
