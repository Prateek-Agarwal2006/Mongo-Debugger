/** Disable a button and show a circular spinner while long work runs. */
(function () {
  const SPINNER =
    '<span class="mdb-btn-spinner" aria-hidden="true"></span>';

  function start(btn, label) {
    if (!btn) return;
    if (!btn.dataset.mdbIdleHtml) {
      btn.dataset.mdbIdleHtml = btn.innerHTML;
    }
    btn.disabled = true;
    btn.setAttribute("aria-busy", "true");
    btn.innerHTML = SPINNER + "<span>" + (label || "Working…") + "</span>";
  }

  function stop(btn) {
    if (!btn) return;
    btn.removeAttribute("aria-busy");
    if (btn.dataset.mdbIdleHtml) {
      btn.innerHTML = btn.dataset.mdbIdleHtml;
    }
    btn.disabled = false;
  }

  window.MdbBtnBusy = { start, stop };
})();
