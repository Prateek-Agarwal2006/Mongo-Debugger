import { createRoot } from "react-dom/client";
import App from "./App";
import "./styles/stitch.css";

const el = document.getElementById("modern-app-root");
if (el) {
  createRoot(el).render(<App />);
}
