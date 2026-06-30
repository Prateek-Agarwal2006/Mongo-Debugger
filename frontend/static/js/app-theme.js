/**
 * Global app theme: classic (dark Mongo) vs modern (React shell).
 */

const APP_THEME_KEY = "mdb-app-theme";
const MODERN_BUNDLE_CSS_ID = "modern-bundle-css";
const MODERN_BUNDLE_JS_ID = "modern-bundle-js";
const MODERN_ASSET_V = "20260629-copyright-2026";

function getAppTheme() {
  const theme = document.documentElement.dataset.appTheme;
  return theme === "modern" || theme === "classic" ? theme : "classic";
}

function isModernShellPage() {
  return document.body.classList.contains("mdb-modern-page");
}

function loadModernBundle() {
  if (document.getElementById(MODERN_BUNDLE_JS_ID)) return;

  if (!document.getElementById(MODERN_BUNDLE_CSS_ID)) {
    const link = document.createElement("link");
    link.id = MODERN_BUNDLE_CSS_ID;
    link.rel = "stylesheet";
    link.href = `/static/modern/assets/index.css?v=${MODERN_ASSET_V}`;
    document.head.appendChild(link);
  }

  const script = document.createElement("script");
  script.id = MODERN_BUNDLE_JS_ID;
  script.type = "module";
  script.src = `/static/modern/assets/index.js?v=${MODERN_ASSET_V}`;
  document.body.appendChild(script);
}

function syncModernShell(theme) {
  const chrome = document.getElementById("classic-chrome");
  const root = document.getElementById("modern-app-root");
  const useModern = theme === "modern" && isModernShellPage();

  if (chrome) chrome.hidden = useModern;
  if (!root) return;

  root.hidden = !useModern;
  if (useModern) {
    loadModernBundle();
  } else {
    document.dispatchEvent(new CustomEvent("modern-app-unmount"));
  }
}

function applyAppTheme(theme) {
  if (theme !== "classic" && theme !== "modern") return;
  document.documentElement.dataset.appTheme = theme;
  document.documentElement.setAttribute("data-bs-theme", theme === "modern" ? "light" : "dark");
  localStorage.setItem(APP_THEME_KEY, theme);
  syncThemeToggles(theme);
  syncModernShell(theme);
  document.dispatchEvent(new CustomEvent("app-theme-change", { detail: { theme } }));
}

function buildToggleMarkup(compact) {
  const classicLabel = compact ? "Classic" : "Classic dark";
  const modernLabel = compact ? "Modern" : "Modern React";
  return `
    <div class="app-theme-toggle${compact ? " app-theme-toggle--compact" : ""}" role="radiogroup" aria-label="App appearance">
      <button type="button" class="app-theme-toggle__btn" data-app-theme-option="classic" aria-checked="false">
        <i class="bi bi-moon-stars-fill" aria-hidden="true"></i><span>${classicLabel}</span>
      </button>
      <button type="button" class="app-theme-toggle__btn" data-app-theme-option="modern" aria-checked="false">
        <i class="bi bi-sun-fill" aria-hidden="true"></i><span>${modernLabel}</span>
      </button>
    </div>
  `;
}

function syncThemeToggles(theme) {
  document.querySelectorAll(".app-theme-toggle").forEach((group) => {
    group.querySelectorAll("[data-app-theme-option]").forEach((btn) => {
      const active = btn.dataset.appThemeOption === theme;
      btn.classList.toggle("is-active", active);
      btn.setAttribute("aria-checked", active ? "true" : "false");
    });
  });
}

function mountThemeToggles() {
  document.querySelectorAll("[data-app-theme-toggle]").forEach((host) => {
    if (host.dataset.appThemeBound) return;
    const compact = host.getAttribute("data-app-theme-toggle") === "compact";
    host.innerHTML = buildToggleMarkup(compact);
    host.dataset.appThemeBound = "1";
    host.querySelectorAll("[data-app-theme-option]").forEach((btn) => {
      btn.addEventListener("click", () => applyAppTheme(btn.dataset.appThemeOption));
    });
  });
  syncThemeToggles(getAppTheme());
}

function initAppTheme() {
  mountThemeToggles();
  applyAppTheme(getAppTheme());
}

function bootAppTheme() {
  const saved = localStorage.getItem(APP_THEME_KEY);
  const theme =
    saved === "modern" || saved === "classic"
      ? saved
      : document.documentElement.dataset.appTheme === "modern"
        ? "modern"
        : "classic";
  document.documentElement.dataset.appTheme = theme;
  document.documentElement.setAttribute(
    "data-bs-theme",
    theme === "modern" ? "light" : "dark"
  );
  syncModernShell(theme);
}

window.getAppTheme = getAppTheme;
window.applyAppTheme = applyAppTheme;

bootAppTheme();

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initAppTheme);
} else {
  initAppTheme();
}
