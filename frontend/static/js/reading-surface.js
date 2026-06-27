/**
 * Scoped light/dark reading surface for RCA report + chatbot.
 * Preference: localStorage key mdb-reading-theme ("light" | "dark").
 */

const READING_THEME_KEY = "mdb-reading-theme";

function getReadingTheme() {
  const el = document.getElementById("reading-surface");
  const theme = el?.dataset.readingTheme;
  return theme === "light" || theme === "dark" ? theme : "dark";
}

function resolveDefaultReadingTheme() {
  const saved = localStorage.getItem(READING_THEME_KEY);
  if (saved === "light" || saved === "dark") return saved;
  return window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

function updateReadingToggleIcons(theme) {
  const btn = document.getElementById("reading-theme-toggle");
  if (!btn) return;
  const sun = btn.querySelector(".reading-theme-icon--light");
  const moon = btn.querySelector(".reading-theme-icon--dark");
  if (sun) sun.hidden = theme !== "dark";
  if (moon) moon.hidden = theme !== "light";
  btn.setAttribute(
    "aria-label",
    theme === "dark" ? "Switch reading surface to light mode" : "Switch reading surface to dark mode"
  );
  btn.title = theme === "dark" ? "Light reading mode" : "Dark reading mode";
}

function applyReadingTheme(theme) {
  const el = document.getElementById("reading-surface");
  if (!el || theme !== "light" && theme !== "dark") return;
  el.dataset.readingTheme = theme;
  updateReadingToggleIcons(theme);
  document.dispatchEvent(new CustomEvent("reading-theme-change", { detail: { theme } }));
}

function initReadingSurface() {
  const el = document.getElementById("reading-surface");
  const btn = document.getElementById("reading-theme-toggle");
  if (!el) return;

  applyReadingTheme(resolveDefaultReadingTheme());

  btn?.addEventListener("click", () => {
    const next = getReadingTheme() === "dark" ? "light" : "dark";
    localStorage.setItem(READING_THEME_KEY, next);
    applyReadingTheme(next);
  });
}

window.getReadingTheme = getReadingTheme;

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initReadingSurface);
} else {
  initReadingSurface();
}
