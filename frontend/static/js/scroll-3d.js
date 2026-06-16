/**
 * Webflow-style 3D scroll transitions — native scroll + one rAF loop.
 * Panels use sticky inner cards that rotateX / translateZ based on scroll progress.
 * No scroll hijacking; listener only active while stage is in viewport.
 */

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function easeOutCubic(t) {
  return 1 - (1 - t) ** 3;
}

function panelMotion(progress) {
  if (progress < 0.32) {
    const t = easeOutCubic(progress / 0.32);
    return {
      rotateX: 38 * (1 - t),
      translateZ: -320 * (1 - t),
      translateY: 48 * (1 - t),
      scale: 0.78 + 0.22 * t,
      opacity: 0.15 + 0.85 * t,
    };
  }
  if (progress > 0.68) {
    const t = easeOutCubic((progress - 0.68) / 0.32);
    return {
      rotateX: -32 * t,
      translateZ: -300 * t,
      translateY: -36 * t,
      scale: 1 - 0.14 * t,
      opacity: 1 - 0.75 * t,
    };
  }
  return { rotateX: 0, translateZ: 0, translateY: 0, scale: 1, opacity: 1 };
}

const stages = new WeakMap();

function updateStage(stage) {
  const vh = window.innerHeight;
  const panels = stage.querySelectorAll("[data-scroll-panel]");

  panels.forEach((panel, index) => {
    const inner = panel.querySelector("[data-scroll-panel-inner]");
    if (!inner) return;

    const rect = panel.getBoundingClientRect();
    const range = Math.max(panel.offsetHeight - vh, 1);
    const scrolled = clamp(-rect.top, 0, range);
    const progress = scrolled / range;
    const motion = panelMotion(progress);

    inner.style.setProperty("--rx", `${motion.rotateX}deg`);
    inner.style.setProperty("--rz", `${motion.translateZ}px`);
    inner.style.setProperty("--ry", `${motion.translateY}px`);
    inner.style.setProperty("--sc", String(motion.scale));
    inner.style.setProperty("--op", String(motion.opacity));

    panel.dataset.scrollState =
      progress < 0.32 ? "enter" : progress > 0.68 ? "exit" : "active";

    if (panel.dataset.chainStep != null) {
      const connector = panel.querySelector(".rv-chain-connector-fill");
      if (connector) {
        connector.style.setProperty("--chain-fill", String(clamp((progress - 0.2) / 0.6, 0, 1)));
      }
    }

    panel.style.setProperty("--panel-index", String(index));
  });

  const progressBar = stage.querySelector("[data-scroll-3d-progress]");
  if (progressBar && panels.length) {
    const first = panels[0].getBoundingClientRect();
    const last = panels[panels.length - 1];
    const lastRect = last.getBoundingClientRect();
    const total = last.offsetTop + last.offsetHeight - panels[0].offsetTop - vh;
    const current = clamp(window.scrollY - panels[0].offsetTop, 0, Math.max(total, 1));
    progressBar.style.setProperty("--scroll-3d-pct", String(current / Math.max(total, 1)));
  }
}

function mountScroll3D(stage) {
  if (!stage || stages.has(stage)) return;

  const state = {
    ticking: false,
    active: false,
    onScroll: null,
    io: null,
  };

  state.onScroll = () => {
    if (!state.active || state.ticking) return;
    state.ticking = true;
    requestAnimationFrame(() => {
      state.ticking = false;
      if (state.active) updateStage(stage);
    });
  };

  state.io = new IntersectionObserver(
    (entries) => {
      const entry = entries[0];
      if (!entry) return;
      state.active = entry.isIntersecting;
      if (state.active) {
        window.addEventListener("scroll", state.onScroll, { passive: true });
        window.addEventListener("resize", state.onScroll, { passive: true });
        updateStage(stage);
      } else {
        window.removeEventListener("scroll", state.onScroll);
        window.removeEventListener("resize", state.onScroll);
      }
    },
    { rootMargin: "20% 0px 20% 0px", threshold: 0 }
  );

  state.io.observe(stage);
  stages.set(stage, state);
  updateStage(stage);
}

function unmountScroll3D(stage) {
  const state = stages.get(stage);
  if (!state) return;
  state.io?.disconnect();
  window.removeEventListener("scroll", state.onScroll);
  window.removeEventListener("resize", state.onScroll);
  stages.delete(stage);
}

function remountScroll3D(stage) {
  if (!stage) return;
  unmountScroll3D(stage);
  mountScroll3D(stage);
}

window.FtdcScroll3D = { mount: mountScroll3D, unmount: unmountScroll3D, remount: remountScroll3D };
