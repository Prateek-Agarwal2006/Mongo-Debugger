/**
 * Lightweight scroll reveals — Intersection Observer + CSS only.
 * No Lenis, no GSAP ScrollTrigger (native scroll stays instant).
 */

function prefersReducedMotion() {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

let revealObserver = null;

function initReveals() {
  if (prefersReducedMotion()) {
    document.querySelectorAll("[data-reveal]").forEach((el) => el.classList.add("is-revealed"));
    return;
  }

  revealObserver = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        entry.target.classList.add("is-revealed");
        revealObserver.unobserve(entry.target);
      }
    },
    { rootMargin: "0px 0px -6% 0px", threshold: 0.06 }
  );

  document.querySelectorAll("[data-reveal]").forEach((el) => {
    el.classList.add("reveal-pending");
    revealObserver.observe(el);
  });
}

function initDropzoneTilt() {
  const zone = document.getElementById("upload-dropzone");
  if (!zone || prefersReducedMotion()) return;

  zone.classList.add("upload-dropzone-3d");

  let raf = 0;
  zone.addEventListener("mousemove", (e) => {
    if (raf) return;
    raf = requestAnimationFrame(() => {
      raf = 0;
      const rect = zone.getBoundingClientRect();
      const px = (e.clientX - rect.left) / rect.width - 0.5;
      const py = (e.clientY - rect.top) / rect.height - 0.5;
      zone.style.transform = `perspective(900px) rotateX(${-py * 6}deg) rotateY(${px * 8}deg)`;
    });
  });

  zone.addEventListener("mouseleave", () => {
    zone.style.transform = "";
  });
}

function scrollToElement(el) {
  if (!el) return;
  el.scrollIntoView({ behavior: prefersReducedMotion() ? "auto" : "smooth", block: "start" });
}

function bootMotion() {
  initReveals();
  initDropzoneTilt();
}

window.FtdcMotion = { scrollTo: scrollToElement };

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", bootMotion);
} else {
  bootMotion();
}
