# Cursor Agent: Preventing Local Shell Execution and Routing Code Through a Daytona Sandbox

Research notes, 2026-07-18. Cursor ships fast (current release line: 3.11, 2026-07-10), so
every claim below is cited to the page that owns it; re-verify against
[cursor.com/docs](https://cursor.com/docs) before shipping config. Context: this repo already
runs LLM-authored matplotlib scripts in ephemeral Daytona microVMs
(`backend/app/simagix/evidence/sandbox_plot.py`, `chart_tools.py`); the goal is to give
Cursor's agent the same "untrusted code never touches the local machine" property.

## TL;DR

- **There is no official "disable terminal" switch in Cursor.** The docs describe no setting
  that removes the shell tool from the agent entirely.
- **The one deterministic blocking mechanism is Hooks** (`.cursor/hooks.json`,
  `beforeShellExecution`), introduced as beta in 1.7 (2025-09-29) and now a production
  feature. A hook script can `deny` every shell command except a whitelisted
  `daytona-exec`-style wrapper, and returns an `agent_message` steering the agent to the
  approved path. Set `failClosed: true` — hooks fail *open* by default.
- **The legacy command denylist is dead**: Backslash Security demonstrated four trivial
  bypasses (Base64, subshells, script files, quote-fragmentation) and Cursor deprecated the
  denylist in release 1.3. Never rely on string-matching denial.
- **Cursor's own sandbox** (macOS Seatbelt via `sandbox-exec`; Linux Landlock + seccomp)
  blocks network and out-of-workspace filesystem access, and is on by default on macOS since
  2.0 (2025-10-29) — but it **cannot be forced for all commands** ("Some commands need full
  system access and bypass the sandbox") and does not exist on Windows. Treat it as
  defense-in-depth, not the primary control.
- **Rules (`.cursor/rules/*.mdc`, `AGENTS.md`) are advisory only** — use them to tell the
  agent *how* to use the Daytona path, never to *enforce* it.
- **Daytona offers two ready-made execution routes**: an official MCP server
  (`daytona mcp init cursor`) exposing sandbox create/exec/file tools, and the SDK
  (`sandbox.process.code_run` / `process.exec` / sessions + `fs.upload_file`/`download_file`)
  this repo already uses — a thin `daytona-exec` CLI wrapper over the SDK is the cleanest
  single allowlistable entry point.
- **Recommended stack (below, §6)**: hook that denies all shell except the wrapper (hard) +
  Daytona MCP server or wrapper CLI (the sanctioned path) + Auto-review
  `permissions.json` block-instructions (best-effort) + a rules file (advisory).

---

## 1. Cursor's permission model for terminal commands

### Current model: Run Modes + `permissions.json`

Cursor's current docs ([Run Modes](https://cursor.com/docs/agent/security/run-modes))
define three modes governing agent autonomy:

1. **Auto-review** (recommended by Cursor): "Allowlisted calls run immediately. Other shell
   commands run in the sandbox when possible." Calls that can't be sandboxed go to an
   LLM classifier, which "can allow the call, ask the agent to take a different approach, or
   ask you to approve."
2. **Allowlist**: only allowlisted actions execute without approval; sandboxing optional.
3. **Run Everything**: every tool call runs automatically, no safety checks.

Allow/block behavior is configured in `permissions.json`:

- User level: `~/.cursor/permissions.json`; project level: `<project>/.cursor/permissions.json`.
- Schema uses `autoRun.allow_instructions` and `autoRun.block_instructions` **arrays of
  plain-English sentences** (e.g. `"Every AWS CLI command should go through approval
  first."`) interpreted by the classifier — not regex/prefix matching.

The docs are candid that this is soft: "The classifier can make mistakes. It can allow a
call you would have blocked, or block a call you would have allowed," and the separate
[security page](https://cursor.com/docs/agent/security) calls Run Modes "best-effort
guardrails rather than a hard security boundary."

Note the churn here: "Ask Every Time" was deprecated in 3.5 (2026-05-22) per the changelog
reference on the Run Modes page, and the old settings-UI "Command Allowlist"/"Command
Denylist" toggles have been folded into this Run Modes + `permissions.json` model.

### The denylist's documented failure

The legacy auto-run denylist is the cautionary tale for any string-matching approach.
[Backslash Security's research](https://www.backslash.security/blog/cursor-ai-security-flaw-autorun-denylist)
showed four bypass families — Base64 obfuscation, subshell wrapping, writing the blocked
command into a script file and running the script, and quote-fragmentation (`"e"cho`,
`""e""cho`, …, giving infinite variants of any name) — and reports that Cursor told them it
was "officially deprecating the denylist feature in release 1.3." Their conclusion
generalizes: *for every denylisted command there are infinitely many equivalent commands not
on the list*. Any enforcement we build must therefore be **default-deny** (allowlist a
single exact wrapper), not deny-by-pattern.

### Can terminal use be disabled entirely?

**No — not via any documented setting.** Neither the
[terminal page](https://cursor.com/docs/agent/terminal) nor the Run Modes/security pages
offer a way to remove the shell tool from the agent. The closest hard equivalents are:

- a `beforeShellExecution` hook returning `permission: "deny"` for everything (§3) — this is
  the real answer;
- Auto-review with a `block_instructions` entry like "never run shell commands" —
  classifier-mediated, so best-effort only;
- Enterprise-tier team/MDM-managed hooks (hooks.json at
  `/Library/Application Support/Cursor/hooks.json` on macOS, `/etc/cursor/hooks.json` on
  Linux) if you need it non-removable by the developer.

### Relevant config files (workspace vs user)

| File | Scope | Purpose |
|---|---|---|
| `~/.cursor/permissions.json` | user | Auto-review allow/block instructions |
| `<project>/.cursor/permissions.json` | project | same, project-specific |
| `~/.cursor/sandbox.json` | user | sandbox network domains, readable/writable paths, `/tmp` access |
| `<project>/.sandbox.json` | project | same; project wins when both exist |
| `~/.cursor/hooks.json` | user | hooks (§3) |
| `<project>/.cursor/hooks.json` | project | hooks; runs from project root |
| `~/.cursor/mcp.json` / `<project>/.cursor/mcp.json` | user / project | MCP servers (§5) |

(Sources: [Run Modes](https://cursor.com/docs/agent/security/run-modes),
[Hooks](https://cursor.com/docs/hooks), [MCP](https://cursor.com/docs/mcp).)

---

## 2. Cursor Rules: steering, not enforcement

Per [cursor.com/docs/context/rules](https://cursor.com/docs/context/rules):

- Project rules live in `.cursor/rules/` as `.mdc` files (Markdown + frontmatter; plain
  `.md` files in that directory are ignored). Frontmatter fields: `description`, `globs`,
  `alwaysApply`.
- `alwaysApply: true` → injected into every agent session (globs/description ignored) — the
  right type for an execution-policy rule.
- `AGENTS.md` in the project root (and nested in subdirectories) is supported as a
  frontmatter-free alternative; nested files override parents.
- User Rules (global, settings UI) apply to Agent chat only. Team Rules
  (Enterprise/Teams) can be marked enforced so users can't disable them.

**Honesty check:** rules are prompt injection into the model's context. Nothing in the docs
claims they are enforced, and the security page's framing of even the *permission* layer as
"best-effort guardrails" applies doubly to rules. A rule saying "never use the terminal"
will usually work and will degrade agent thrash (fewer denied attempts), but a confused or
prompt-injected agent can ignore it. Use rules to make the sanctioned path (Daytona wrapper
/ MCP tools) discoverable and well-documented — pair with hooks for enforcement. Example
rule file in §6.

---

## 3. Cursor Hooks: the deterministic layer

Hooks shipped as beta in [1.7 (2025-09-29)](https://cursor.com/changelog/1-7) ("audit Agent
usage, block commands, or redact secrets") and are now documented as a production feature
at [cursor.com/docs/hooks](https://cursor.com/docs/hooks). Cloud-agent hook coverage was
expanded in [3.11 (2026-07-10)](https://cursor.com/changelog).

### Configuration

`hooks.json` is read from four levels, highest precedence first: Enterprise (MDM paths
above) → Team (dashboard) → Project (`<project>/.cursor/hooks.json`) → User
(`~/.cursor/hooks.json`). Project hook commands run from the project root. Format:

```json
{
  "version": 1,
  "hooks": {
    "beforeShellExecution": [
      { "command": "./.cursor/hooks/gate-shell.sh", "timeout": 10, "failClosed": true }
    ]
  }
}
```

Per-hook options: `command`, `type` (`"command"` default, or `"prompt"` for LLM-evaluated
hooks), `timeout` (seconds), `matcher` (regex filter — for `beforeShellExecution` it matches
command text), `failClosed` (default **false** = fail-open), `loop_limit`.

### Events relevant here

- **`beforeShellExecution`** — fires before *any* shell command the agent wants to run.
  Stdin JSON includes `command` (full command line), `cwd`, `sandbox` (bool), plus common
  fields (`conversation_id`, `workspace_roots`, `hook_event_name`, `cursor_version`, …).
  Stdout JSON decides:

  ```json
  { "permission": "allow" | "deny" | "ask",
    "user_message": "shown to the human",
    "agent_message": "fed back to the agent" }
  ```

  Exit code 2 also blocks (equivalent to deny); other nonzero exits **fail open** unless
  `failClosed: true`.
- **`beforeMCPExecution`** — same allow/deny/ask contract for MCP tool calls (input:
  `tool_name`, `tool_input`, server `url`/`command`). Docs recommend `failClosed: true`
  for security-critical uses. Lets you pin *which* MCP tools may run (e.g. only
  `daytona-mcp` tools).
- **`preToolUse`** — generic pre-tool hook (matchers: `Shell`, `Read`, `Write`, `MCP:<tool>`,
  `Task`…) supporting `permission: allow|deny` and even `updated_input` (rewriting the tool
  call) — i.e. you could deterministically *rewrite* a shell command into a
  `daytona-exec` invocation, though deny-with-instructions is simpler and less surprising.
- `afterShellExecution` / `postToolUse*` — audit/log only.

### Caveats

- `failClosed` defaults to false: a crashing/missing hook script silently allows commands.
  Always set it.
- Since hooks are keyed off Cursor's tool-call layer (not a kernel boundary), they are only
  as strong as Cursor's implementation; a project-level `hooks.json` can also be edited by
  the agent itself unless config-file edits require approval (the
  [security page](https://cursor.com/docs/agent/security) says configuration-file
  modifications require approval) or you place the hook at user/Enterprise level, which the
  workspace agent can't touch.
- Community reports note the Cursor CLI historically did not emit every hook event
  ([forum thread](https://forum.cursor.com/t/cursor-cli-doesnt-send-all-events-defined-in-hooks/148316));
  verify `beforeShellExecution` fires in every surface you use (IDE agent, CLI, cloud
  agents — cloud agents do support it per the hooks docs).

Despite the caveats, this is the only mechanism Cursor documents that can **deterministically
deny every shell command** — it is the enforcement backbone of §6.

---

## 4. Cursor's own sandboxed terminal

From [Run Modes → Sandboxing](https://cursor.com/docs/agent/security/run-modes) and the
[2.0 changelog](https://cursor.com/changelog/2-0) (2025-10-29: "Sandboxed terminals are now
GA for macOS. We now run agent commands in the secure sandbox by default on macOS"):

- **macOS**: Seatbelt via `sandbox-exec`; a generated profile "limits file access, network
  access, and other process behavior for the full subprocess tree."
- **Linux**: Landlock (filesystem) + seccomp (syscall filtering); requires kernel ≥ 6.2
  with Landlock v3 and unprivileged user namespaces.
- **Windows**: not mentioned — no sandbox.
- Isolation defaults: read/write inside the workspace only (protected paths like
  `.git/config`, `.vscode`, `.cursorignore` blocked); **network blocked by default**, opened
  per-domain via `sandbox.json` (plus ~100 default registry domains); `/tmp` writable unless
  disabled. Env markers: `CURSOR_SANDBOX`, `CURSOR_ORIG_UID/GID`,
  `CURSOR_SANDBOX_LANDLOCK_STATUS`.
- **It cannot be made universal**: "Some commands need full system access and bypass the
  sandbox. Cursor will indicate when a command runs outside the sandbox and ask for your
  approval." So sandbox-escape is a *user-approval* event, not impossible.
- Known rough edges from the community (secondary sources, but instructive): allowlist and
  sandbox interacted badly in early 2.x — e.g. ["Command Allowlist is silently ignored when
  'Auto-Run in Sandbox' is enabled"](https://forum.cursor.com/t/command-allowlist-is-silently-ignored-when-auto-run-in-sandbox-is-enabled/152136),
  and [Luca Becker's analysis](https://luca-becker.me/blog/cursor-sandboxing-leaks-secrets/)
  of workspace-readable secrets (a sandboxed command can still read `.env` in the workspace
  and, with any allowed network domain, exfiltrate). The sandbox protects the *machine*,
  not workspace secrets, and not at all on Windows.

**Verdict for our use case:** keep it on (it's free hardening for anything that slips
through), but it does not achieve "nothing executes locally" — commands still run on the
developer's machine with workspace read/write. Only the hook layer + remote execution does.

---

## 5. Routing execution through Daytona

### What this repo already does (the pattern to extend)

`backend/app/simagix/evidence/sandbox_plot.py` establishes the model: privileged code runs
pod-side; untrusted LLM code runs in an ephemeral Daytona microVM that sees only a CSV.
Concretely it uses the Python SDK: `Daytona(DaytonaConfig(api_key=...))` →
`client.create(timeout=60)` → `sandbox.fs.upload_file(bytes, "data.csv")` →
`sandbox.process.code_run(script, timeout=120)` (checks `exit_code` / `result`) →
`sandbox.fs.download_file("chart.png")` → `sandbox.delete()` in a `finally`. The same
verbs cover general script execution.

### Daytona SDK surface for a generic executor

Per [Process & Code Execution docs](https://www.daytona.io/docs/en/process-code-execution/):

- `process.code_run(code, ...)` — stateless Python/JavaScript/TypeScript execution, clean
  interpreter per call, env vars/argv/timeout params, returns artifacts (including
  matplotlib charts).
- `process.exec(command, ...)` — arbitrary shell commands; default timeout 10 s; custom
  cwd/env/timeout. Available in Python, TypeScript, Ruby, Go, Java SDKs, REST API and CLI.
- Sessions for stateful/long-running work: `create_session()`, `execute_session_command()`
  (with `run_async`), `send_session_command_input()`, log streaming, `delete_session()`.
- File I/O via the `fs` module (`upload_file`, `download_file`) as used in
  `sandbox_plot.py`.

### Option A — official Daytona MCP server (lowest effort)

Daytona ships an [official MCP server](https://www.daytona.io/docs/en/mcp/) with tools for
sandbox management (create/destroy), process & code execution, file operations, git
operations, and preview links. Setup:

```bash
brew install daytonaio/cli/daytona
daytona login
daytona mcp init cursor        # writes the Cursor MCP config
# or: daytona mcp config       # prints JSON to paste into .cursor/mcp.json
```

Generated config (goes in `<project>/.cursor/mcp.json` or `~/.cursor/mcp.json`, per
[Cursor MCP docs](https://cursor.com/docs/mcp)):

```json
{
  "mcpServers": {
    "daytona-mcp": {
      "command": "daytona",
      "args": ["mcp", "start"],
      "env": { "HOME": "${env:HOME}", "PATH": "${env:HOME}:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin" }
    }
  }
}
```

With this, the agent runs code via MCP tool calls (no local shell involved), and MCP calls
follow the same Run Modes — allowlist the Daytona tools so they run without friction, and
gate everything else with `beforeMCPExecution` if desired. MCP tools can be pre-approved
(security page: "MCP allowlist"; Enterprise adds per-server tool allowlists under Team
Settings → MCP Configuration).

Trade-off: the stock MCP server executes in *Daytona's* sandboxes with your API key from
`daytona login` — fine for generic script running; if you want the Mongo-Debugger data
contract (push CSV in, pull PNG out, no credentials inside), a custom MCP server or wrapper
around the repo's existing `execute_plot_script`-style functions is better.

### Option B — a `daytona-exec` wrapper CLI (single allowlistable command)

A ~40-line script in this repo (e.g. `scripts/daytona-exec`) that mirrors
`sandbox_plot.py`: read a script from a file/stdin, `client.create()`, upload any `--input`
files, `process.code_run` (or `process.exec` for shell), print stdout/exit code, download
`--output` artifacts to a local dir, `sandbox.delete()`. This becomes the **only** command
the shell gate allows, so even the agent's habit of "write script, run it in terminal"
works — the terminal command just happens to execute remotely. This is the best fit when
you want hooks to allow exactly one binary by exact prefix.

---

## 6. Recommended setup for this repo (layered)

| Layer | Mechanism | Enforcement level |
|---|---|---|
| 1. Shell gate | `.cursor/hooks.json` `beforeShellExecution` deny-all-except-wrapper, `failClosed: true` | **Hard** (deterministic, within Cursor's tool layer) |
| 2. MCP gate | `beforeMCPExecution` hook allowing only `daytona-mcp` tools | **Hard** (same caveat) |
| 3. Sanctioned path | Daytona MCP server and/or `scripts/daytona-exec` wrapper | n/a (the escape valve) |
| 4. Run Mode | Auto-review + `permissions.json` block instructions | Best-effort (classifier) |
| 5. Cursor sandbox | on by default (macOS); `sandbox.json` with no extra network domains | Defense-in-depth; bypassable with user approval; no Windows |
| 6. Rules | `.cursor/rules/execution-policy.mdc` (`alwaysApply: true`) | **Advisory only** |

Layer 1 is what actually prevents local execution; 4–6 exist to keep the agent productive
(fewer denials, clear redirection) and to catch config drift. Prefer putting `hooks.json`
at the **user level** (`~/.cursor/hooks.json`) or Enterprise level in addition to the repo
copy, since a repo-level hook is workspace content the agent could propose edits to
(config edits require approval, but a human can mis-approve).

### 6.1 `.cursor/hooks.json`

```json
{
  "version": 1,
  "hooks": {
    "beforeShellExecution": [
      { "command": "./.cursor/hooks/gate-shell.sh", "timeout": 10, "failClosed": true }
    ],
    "beforeMCPExecution": [
      { "command": "./.cursor/hooks/gate-mcp.sh", "timeout": 10, "failClosed": true }
    ],
    "afterShellExecution": [
      { "command": "./.cursor/hooks/audit-log.sh", "timeout": 5 }
    ]
  }
}
```

### 6.2 `.cursor/hooks/gate-shell.sh`

```bash
#!/usr/bin/env bash
# Deny all agent shell commands except the Daytona wrapper (and a tiny read-only set).
set -euo pipefail
input=$(cat)
cmd=$(printf '%s' "$input" | jq -r '.command // empty')

# Exact-prefix allow: the wrapper itself, plus harmless introspection.
case "$cmd" in
  "scripts/daytona-exec "*|"./scripts/daytona-exec "*|"git status"|"git diff"*|"git log"*)
    printf '{"permission":"allow"}\n'; exit 0 ;;
esac

jq -n --arg cmd "$cmd" '{
  permission: "deny",
  user_message: ("Blocked local shell: " + $cmd),
  agent_message: "Local shell execution is disabled in this repo. Run code remotely instead: write your script to a file and execute it with `scripts/daytona-exec --script <file> [--input <data-file>] [--output <artifact>]`, or use the daytona-mcp tools. Never retry the command locally or try to work around this via subshells, base64, or script files — those are blocked too."
}'
```

Notes: default-deny means the Backslash bypass classes (base64, subshells, `bash foo.sh`,
quote-splitting) all fall through to `deny` — we never try to enumerate bad commands. Keep
the allow prefixes exact and boring; anything with `;`, `&&`, `|` won't match the prefixes
above. Test that `jq` exists on every dev machine or inline with `python3 -c`.

### 6.3 `.cursor/hooks/gate-mcp.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail
input=$(cat)
tool=$(printf '%s' "$input" | jq -r '.tool_name // empty')
case "$tool" in
  daytona*|mcp_daytona*)
    printf '{"permission":"allow"}\n' ;;
  *)
    jq -n --arg t "$tool" '{permission:"ask",
      user_message:("MCP tool not pre-approved: " + $t)}' ;;
esac
```

### 6.4 `.cursor/permissions.json` (best-effort backstop)

```json
{
  "autoRun": {
    "allow_instructions": [
      "Running scripts/daytona-exec is always allowed.",
      "Calling daytona-mcp tools is always allowed."
    ],
    "block_instructions": [
      "Any terminal command other than scripts/daytona-exec or read-only git commands must be reviewed before execution.",
      "Never run python, node, bash, sh, uv, pip or npm directly on this machine."
    ]
  }
}
```

### 6.5 `.cursor/rules/execution-policy.mdc` (advisory)

```markdown
---
description: All code execution must go through the Daytona sandbox
alwaysApply: true
---

# Execution policy

- NEVER run code, scripts, tests, or package managers in the local terminal.
  Local shell execution is blocked by a hook; do not attempt workarounds
  (subshells, base64, writing wrapper scripts).
- To execute anything, use ONE of:
  1. `scripts/daytona-exec --script <file> [--input <file>...] [--output <artifact>]`
     — runs the script in an ephemeral Daytona microVM; inputs are uploaded to the
     sandbox cwd; artifacts are downloaded back. Exit code and stdout are relayed.
  2. The `daytona-mcp` MCP tools (create sandbox, execute command, file ops).
- The sandbox has no repo checkout, no DB credentials, and no cluster access.
  Ship data in explicitly (files), ship artifacts out explicitly — same contract
  as backend/app/simagix/evidence/sandbox_plot.py (data.csv in, chart.png out).
- If the wrapper or MCP server is unavailable, STOP and report it; do not fall
  back to local execution.
```

### 6.6 `scripts/daytona-exec` (sketch, mirrors `sandbox_plot.py`)

```python
#!/usr/bin/env python3
"""Run a script in an ephemeral Daytona sandbox. Usage:
daytona-exec --script run.py [--shell] [--input data.csv ...] [--output out.png ...]"""
import argparse, os, pathlib, sys
from daytona import Daytona, DaytonaConfig

p = argparse.ArgumentParser()
p.add_argument("--script", required=True)
p.add_argument("--shell", action="store_true", help="treat script as shell commands")
p.add_argument("--input", action="append", default=[])
p.add_argument("--output", action="append", default=[])
p.add_argument("--timeout", type=int, default=120)
a = p.parse_args()

client = Daytona(DaytonaConfig(api_key=os.environ["DAYTONA_API_KEY"]))
sandbox = client.create(timeout=60)
try:
    for f in a.input:
        sandbox.fs.upload_file(pathlib.Path(f).read_bytes(), pathlib.Path(f).name)
    src = pathlib.Path(a.script).read_text()
    run = (sandbox.process.exec(src, timeout=a.timeout) if a.shell
           else sandbox.process.code_run(src, timeout=a.timeout))
    print(run.result or "")
    for f in a.output:
        pathlib.Path(f).write_bytes(sandbox.fs.download_file(pathlib.Path(f).name))
    sys.exit(run.exit_code)
finally:
    try: sandbox.delete()
    except Exception: pass
```

Keep `DAYTONA_API_KEY` in the developer's environment, never in workspace files (the Cursor
sandbox does not stop workspace-file reads — see §4).

### Verification checklist

1. Ask the agent to run `echo hi` — expect a deny with the redirect message.
2. Ask it to run `bash -c "$(base64 -d <<< ZWNobyBoaQ==)"` and `sh test.sh` — both denied
   (default-deny, not pattern-matching).
3. Ask it to "run this Python snippet" — expect it to write a file and call
   `scripts/daytona-exec`, which is allowed and executes remotely.
4. Kill/rename the hook script — commands must now be **blocked** (`failClosed: true`), not
   silently allowed.
5. Repeat in every surface the team uses (IDE agent, `cursor-agent` CLI, cloud agents) —
   hook event coverage has differed by surface historically.

---

## Sources

Official Cursor docs (fetched 2026-07-18):

- Hooks reference — <https://cursor.com/docs/hooks> (events, `hooks.json` format, I/O
  schemas, `failClosed`, precedence levels, cloud-agent support)
- Run Modes & sandboxing — <https://cursor.com/docs/agent/security/run-modes>
  (`permissions.json`, `sandbox.json`, Seatbelt/Landlock details, "classifier can make
  mistakes", "some commands … bypass the sandbox")
- Agent security — <https://cursor.com/docs/agent/security> ("best-effort guardrails rather
  than a hard security boundary", MCP allowlist)
- Terminal — <https://cursor.com/docs/agent/terminal>
- Rules — <https://cursor.com/docs/context/rules> (`.mdc` frontmatter, `AGENTS.md`, Team
  Rules enforcement)
- MCP — <https://cursor.com/docs/mcp> (`.cursor/mcp.json` project/global, approval flow,
  Enterprise tool allowlists)
- Changelog 1.7 (2025-09-29, Hooks beta) — <https://cursor.com/changelog/1-7>
- Changelog 2.0 (2025-10-29, sandboxed terminals GA/default on macOS) —
  <https://cursor.com/changelog/2-0>
- Changelog 3.11 (2026-07-10, cloud-agent hooks) — <https://cursor.com/changelog>

Official Daytona docs:

- MCP server — <https://www.daytona.io/docs/en/mcp/> (`daytona mcp init cursor`, tool list)
- Process & code execution — <https://www.daytona.io/docs/en/process-code-execution/>
  (`code_run`, `exec`, sessions)

Secondary (labeled as such in text):

- Backslash Security denylist bypass research —
  <https://www.backslash.security/blog/cursor-ai-security-flaw-autorun-denylist>
- Cursor forum: allowlist ignored under Auto-Run in Sandbox —
  <https://forum.cursor.com/t/command-allowlist-is-silently-ignored-when-auto-run-in-sandbox-is-enabled/152136>
- Cursor forum: CLI hook-event gaps —
  <https://forum.cursor.com/t/cursor-cli-doesnt-send-all-events-defined-in-hooks/148316>
- Luca Becker, "When Sandboxing Leaks Your Secrets" (Nov 2025) —
  <https://luca-becker.me/blog/cursor-sandboxing-leaks-secrets/>

Repo files grounding the recommendation:

- `/Users/prateek.agarwal/Documents/Intern Projects/Mongo Debugger/backend/app/simagix/evidence/sandbox_plot.py`
- `/Users/prateek.agarwal/Documents/Intern Projects/Mongo Debugger/backend/app/simagix/evidence/chart_tools.py`
