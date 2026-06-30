import { createRoot, type Root } from "react-dom/client";
import App from "./App";
import "./styles/stitch.css";

declare global {
  interface Window {
    applyAppTheme?: (theme: string) => void;
  }
}

let reactRoot: Root | null = null;

function shouldMount() {
  return (
    document.body.classList.contains("mdb-modern-page") &&
    document.documentElement.dataset.appTheme === "modern"
  );
}

function mountModernApp() {
  const el = document.getElementById("modern-app-root");
  if (!el || el.dataset.mounted === "1" || !shouldMount()) return;

  el.dataset.mounted = "1";
  reactRoot = createRoot(el);
  reactRoot.render(<App />);
}

function unmountModernApp() {
  const el = document.getElementById("modern-app-root");
  if (!el || el.dataset.mounted !== "1") return;

  reactRoot?.unmount();
  reactRoot = null;
  el.dataset.mounted = "0";
  el.replaceChildren();
}

mountModernApp();

document.addEventListener("app-theme-change", (ev) => {
  const theme = (ev as CustomEvent<{ theme: string }>).detail?.theme;
  if (theme === "modern") mountModernApp();
  else unmountModernApp();
});

document.addEventListener("modern-app-unmount", unmountModernApp);
