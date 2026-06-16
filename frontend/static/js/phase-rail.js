/**
 * Phase A → B → C progress rail — single state, explicit transitions.
 * pending (grey) | current (blue) | running (amber pulse) | done (green)
 */

const PHASE_LABELS = {
  idle: "Ready — click Run RCA to start Phase A",
  A: "Phase A — tier-2 investigation (MCP tools)",
  B: "Phase B — answer clarifying questions",
  C: "Phase C — generating final RCA report",
  done: "RCA complete — report below",
};

const STEPS = ["A", "B", "C"];

const HIDE_AFTER_SCROLL_Y = 120;
const SHOW_BELOW_SCROLL_Y = 48;

/** @type {{ active: string, running: boolean, completed: Record<string, boolean> }} */
let railState = {
  active: "idle",
  running: false,
  completed: { A: false, B: false, C: false },
};

let railShellHidden = false;
let scrollListenersReady = false;

function emptyCompleted() {
  return { A: false, B: false, C: false };
}

function getRailShell() {
  return document.getElementById("phase-rail-shell");
}

function getNodeVisual(step) {
  const { active, running, completed } = railState;

  if (active === "done") {
    return "done";
  }

  if (step === active && running) {
    return "running";
  }

  if (completed[step] && step !== active) {
    return "done";
  }

  if (completed[step] && step === active && !running) {
    return "done";
  }

  if (step === active) {
    return "current";
  }

  return "pending";
}

function computeFillPct() {
  const { active, running, completed } = railState;

  if (active === "done") {
    return 100;
  }

  let pct = 0;
  if (completed.A) pct = 34;
  if (completed.B) pct = 67;
  if (completed.C) pct = 100;

  if (running && active === "A") pct = Math.max(pct, 17);
  if (running && active === "B") pct = Math.max(pct, 50);
  if (running && active === "C") pct = Math.max(pct, 84);

  if (!running && active === "B" && completed.A) pct = Math.max(pct, 34);
  if (!running && active === "C" && completed.A && completed.B) pct = Math.max(pct, 67);

  return pct;
}

function pageScrollY() {
  return (
    window.scrollY ||
    window.pageYOffset ||
    document.documentElement.scrollTop ||
    document.body.scrollTop ||
    0
  );
}

function shouldHideRailShell() {
  if (railState.running) return false;
  return pageScrollY() > HIDE_AFTER_SCROLL_Y;
}

function shouldShowRailShell() {
  return pageScrollY() <= SHOW_BELOW_SCROLL_Y;
}

function setRailShellHidden(hidden) {
  const shell = getRailShell();
  if (!shell) return;

  if (railState.running) {
    hidden = false;
  }

  if (hidden === railShellHidden) return;
  railShellHidden = hidden;
  shell.classList.toggle("phase-rail-shell--hidden", hidden);
  shell.setAttribute("aria-hidden", hidden ? "true" : "false");
}

function showRailShell() {
  setRailShellHidden(false);
}

function refreshRailShellVisibility() {
  if (railState.running) {
    setRailShellHidden(false);
    return;
  }
  if (shouldHideRailShell()) {
    setRailShellHidden(true);
    return;
  }
  if (shouldShowRailShell()) {
    setRailShellHidden(false);
  }
}

function initRailScrollHide() {
  if (scrollListenersReady) return;
  scrollListenersReady = true;

  const onMove = () => refreshRailShellVisibility();

  window.addEventListener("scroll", onMove, { passive: true });
  window.addEventListener("resize", onMove, { passive: true });
}

function renderRail() {
  const rail = document.getElementById("phase-rail");
  if (!rail) return;

  const { active, running } = railState;
  rail.dataset.phase = active === "idle" ? "idle" : active;
  rail.dataset.running = running ? "1" : "0";

  STEPS.forEach((step) => {
    const node = rail.querySelector(`.phase-node[data-step="${step}"]`);
    if (!node) return;
    const visual = getNodeVisual(step);
    node.classList.remove("phase-node--done", "phase-node--running", "phase-node--current");
    node.dataset.visual = visual;
    if (visual === "done") node.classList.add("phase-node--done");
    if (visual === "running") node.classList.add("phase-node--running");
    if (visual === "current") node.classList.add("phase-node--current");
  });

  const pct = computeFillPct();
  rail.style.setProperty("--phase-fill", `${pct}%`);
  const fillEl = rail.querySelector(".phase-rail-fill");
  if (fillEl) {
    fillEl.style.width = `${pct}%`;
  }

  const statusEl = document.getElementById("phase-rail-status");
  if (statusEl) {
    if (active === "A" && running) {
      statusEl.textContent = "Phase A in progress — MCP tools running…";
    } else if (active === "B" && running) {
      statusEl.textContent = "Phase B in progress…";
    } else if (active === "C" && running) {
      statusEl.textContent = "Phase C in progress — generating report (this may take a minute)…";
    } else if (active === "done") {
      statusEl.textContent = PHASE_LABELS.done;
    } else {
      statusEl.textContent = PHASE_LABELS[active] || PHASE_LABELS.idle;
    }
  }

  refreshRailShellVisibility();
}

function applyState(next) {
  if (next.completed !== undefined) {
    railState.completed = { ...emptyCompleted(), ...next.completed };
  }
  if (next.active !== undefined) {
    railState.active = next.active;
  }
  if (next.running !== undefined) {
    railState.running = next.running;
  }
  renderRail();
}

function resetRail() {
  railState = { active: "idle", running: false, completed: emptyCompleted() };
  renderRail();
  showRailShell();
}

function setPhase(active, options = {}) {
  const { running = false } = options;

  if (active === "done") {
    railState = {
      active: "done",
      running: false,
      completed: { A: true, B: true, C: true },
    };
    renderRail();
    return;
  }

  const normalized = ["idle", "A", "B", "C"].includes(active) ? active : "idle";
  railState.active = normalized;
  railState.running = running;
  renderRail();
}

function markComplete(step) {
  if (!STEPS.includes(step)) return;
  railState.completed[step] = true;
  renderRail();
}

function setFromApiStatus(apiStatus) {
  if (apiStatus === "awaiting_clarifications") {
    railState = {
      active: "B",
      running: false,
      completed: { A: true, B: false, C: false },
    };
    renderRail();
    showRailShell();
    return;
  }
  if (apiStatus === "running_rca") {
    railState = {
      active: "C",
      running: true,
      completed: { A: true, B: true, C: false },
    };
    renderRail();
    return;
  }
  if (apiStatus === "completed") {
    railState = {
      active: "done",
      running: false,
      completed: { A: true, B: true, C: true },
    };
    renderRail();
    showRailShell();
    return;
  }
  resetRail();
}

function bootPhaseRail() {
  initRailScrollHide();
  renderRail();
  showRailShell();
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", bootPhaseRail);
} else {
  bootPhaseRail();
}

window.FtdcPhaseRail = {
  setPhase,
  markComplete,
  reset: resetRail,
  applyState,
  setFromApiStatus,
  showShell: showRailShell,
  getState: () => ({ ...railState, completed: { ...railState.completed } }),
  refreshShell: refreshRailShellVisibility,
};
