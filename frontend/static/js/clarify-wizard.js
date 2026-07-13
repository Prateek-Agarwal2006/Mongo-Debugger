/**
 * Phase B — one question per card (answer / skip / prev / next).
 * Still submits the same { answers: { id: text } } payload to POST /phase2/clarify.
 */

let wizardQuestions = [];
let wizardIndex = 0;
let wizardAnswers = {};

/** Stitch/Tailwind pages use class `hidden`; Classic uses the `hidden` attribute — toggle both. */
function setElVisible(el, visible) {
  if (!el) return;
  el.hidden = !visible;
  el.classList.toggle("hidden", !visible);
}

function isStitchClarifyWizard() {
  const form = document.getElementById("clarify-form");
  return form?.classList.contains("clarify-wizard--stitch");
}

function getWizardEls() {
  return {
    form: document.getElementById("clarify-form"),
    actions: document.getElementById("clarify-actions"),
    container: document.getElementById("questions-container"),
    progress: document.getElementById("clarify-progress"),
    prevBtn: document.getElementById("clarify-prev"),
    skipBtn: document.getElementById("clarify-skip"),
    nextBtn: document.getElementById("clarify-next"),
    submitBtn: document.getElementById("clarify-submit"),
    textarea: document.getElementById("clarify-answer-input"),
  };
}

/** setSubmitting(true) hides the whole action bar; show/hide must restore it for the next Phase B. */
function resetClarifyActions() {
  const { actions, prevBtn, skipBtn, nextBtn, submitBtn } = getWizardEls();
  setElVisible(actions, true);
  [prevBtn, skipBtn, nextBtn, submitBtn].forEach((btn) => {
    if (btn) btn.disabled = false;
  });
}

function currentQuestion() {
  return wizardQuestions[wizardIndex] || null;
}

function saveCurrentAnswer() {
  const q = currentQuestion();
  const { textarea } = getWizardEls();
  if (!q || !textarea) return;
  wizardAnswers[q.id] = textarea.value.trim();
}

function renderWizardProgress() {
  const { progress } = getWizardEls();
  if (!progress) return;
  if (!wizardQuestions.length) {
    progress.innerHTML = "";
    return;
  }
  const dots = wizardQuestions
    .map((q, i) => {
      const answered = Boolean(wizardAnswers[q.id]);
      const active = i === wizardIndex;
      const cls = ["clarify-dot", active ? "clarify-dot--active" : "", answered ? "clarify-dot--done" : ""]
        .filter(Boolean)
        .join(" ");
      return `<span class="${cls}" title="Question ${i + 1}"></span>`;
    })
    .join("");

  if (isStitchClarifyWizard()) {
    progress.innerHTML = `
      <span class="clarify-progress-label">Progress</span>
      <div class="clarify-progress-dots" role="list">${dots}</div>`;
    return;
  }
  progress.innerHTML = dots;
}

function renderWizardCard() {
  const { container, textarea, prevBtn, skipBtn, nextBtn, submitBtn } = getWizardEls();
  if (!container) return;

  if (!wizardQuestions.length) {
    container.innerHTML = isStitchClarifyWizard()
      ? '<p class="clarify-empty-msg">No clarifying questions needed — submit to run final RCA.</p>'
      : '<p class="text-secondary small mb-0">No clarifying questions needed — submit to run final RCA.</p>';
    setElVisible(prevBtn, false);
    setElVisible(skipBtn, false);
    setElVisible(nextBtn, false);
    setElVisible(submitBtn, true);
    renderWizardProgress();
    return;
  }

  const q = currentQuestion();
  if (!q) return;

  if (isStitchClarifyWizard()) {
    container.innerHTML = `
    <div class="clarify-card clarify-card--stitch">
      <div class="clarify-card__header">
        <span class="clarify-card__badge">Question ${wizardIndex + 1} of ${wizardQuestions.length}</span>
      </div>
      <h3 class="clarify-card__question">${escapeWizardHtml(q.question)}</h3>
      <p class="clarify-card__rationale">${escapeWizardHtml(q.rationale)}</p>
      <div class="clarify-answer-block">
        <label class="clarify-answer-label" for="clarify-answer-input">Your answer</label>
        <textarea class="clarify-answer-input" id="clarify-answer-input" rows="4" placeholder="Share what you know — or skip if unknown…"></textarea>
      </div>
    </div>`;
  } else {
    container.innerHTML = `
    <div class="clarify-card glass-card p-4">
      <div class="d-flex justify-content-between align-items-center mb-2">
        <span class="badge text-bg-dark border border-secondary-subtle">Question ${wizardIndex + 1} of ${wizardQuestions.length}</span>
      </div>
      <h3 class="h6 mb-2">${escapeWizardHtml(q.question)}</h3>
      <p class="text-secondary small mb-3">${escapeWizardHtml(q.rationale)}</p>
      <label class="form-label small text-secondary" for="clarify-answer-input">Your answer</label>
      <textarea class="form-control" id="clarify-answer-input" rows="4" placeholder="Type an answer or skip if unknown…"></textarea>
    </div>`;
  }

  const input = document.getElementById("clarify-answer-input");
  if (input) {
    input.value = wizardAnswers[q.id] || "";
    input.focus();
  }

  setElVisible(prevBtn, wizardIndex > 0);
  setElVisible(skipBtn, true);
  setElVisible(nextBtn, wizardIndex < wizardQuestions.length - 1);
  setElVisible(submitBtn, wizardIndex >= wizardQuestions.length - 1);

  renderWizardProgress();
}

function escapeWizardHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function showClarifyWizard(questions, existingAnswers = {}) {
  const { form } = getWizardEls();
  if (!form) return;

  wizardQuestions = questions || [];
  wizardIndex = 0;
  wizardAnswers = { ...existingAnswers };

  resetClarifyActions();
  setElVisible(form, true);
  renderWizardCard();
}

function hideClarifyWizard() {
  const { form } = getWizardEls();
  if (form) {
    setElVisible(form, false);
    delete form.dataset.submitting;
  }
  resetClarifyActions();
  wizardQuestions = [];
  wizardIndex = 0;
  wizardAnswers = {};
}

function setSubmitting(busy) {
  const { form, prevBtn, skipBtn, nextBtn, submitBtn } = getWizardEls();
  if (!form) return;

  if (busy) {
    form.dataset.submitting = "1";
    const actions = document.getElementById("clarify-actions");
    setElVisible(actions, false);
    const container = document.getElementById("questions-container");
    if (container) {
      container.innerHTML = isStitchClarifyWizard()
        ? `
        <div class="clarify-card clarify-card--stitch clarify-card--loading">
          <div class="clarify-spinner" role="status" aria-hidden="true"></div>
          <p class="clarify-loading-title">Phase C — generating final RCA…</p>
          <p class="clarify-loading-hint">Please wait — do not submit again.</p>
        </div>`
        : `
        <div class="clarify-card glass-card p-4 text-center">
          <div class="spinner-border text-success mb-3" role="status" aria-hidden="true"></div>
          <p class="mb-0 fw-semibold">Phase C — generating final RCA…</p>
          <p class="text-secondary small mb-0 mt-1">Please wait — do not submit again.</p>
        </div>`;
    }
    [prevBtn, skipBtn, nextBtn, submitBtn].forEach((btn) => {
      if (btn) btn.disabled = true;
    });
    return;
  }

  delete form.dataset.submitting;
  resetClarifyActions();
  renderWizardCard();
}

function collectWizardAnswers() {
  saveCurrentAnswer();
  const answers = { ...wizardAnswers };
  wizardQuestions.forEach((q) => {
    if (!(q.id in answers)) answers[q.id] = "";
  });
  return answers;
}

function initClarifyWizard() {
  const { prevBtn, skipBtn, nextBtn } = getWizardEls();

  prevBtn?.addEventListener("click", () => {
    saveCurrentAnswer();
    if (wizardIndex > 0) {
      wizardIndex -= 1;
      renderWizardCard();
    }
  });

  skipBtn?.addEventListener("click", () => {
    const q = currentQuestion();
    if (q) wizardAnswers[q.id] = "";
    if (wizardIndex < wizardQuestions.length - 1) {
      wizardIndex += 1;
    }
    renderWizardCard();
  });

  nextBtn?.addEventListener("click", () => {
    saveCurrentAnswer();
    if (wizardIndex < wizardQuestions.length - 1) {
      wizardIndex += 1;
      renderWizardCard();
    }
  });
}

/** ponytail: browser-console check — FtdcClarifyWizard._selfCheck() */
function _clarifyWizardSelfCheck() {
  const probe = document.createElement("div");
  probe.classList.add("hidden");
  probe.hidden = true;
  setElVisible(probe, true);
  const ok = !probe.hidden && !probe.classList.contains("hidden");
  probe.remove();
  return ok;
}

window.FtdcClarifyWizard = {
  show: showClarifyWizard,
  hide: hideClarifyWizard,
  collectAnswers: collectWizardAnswers,
  setSubmitting,
  init: initClarifyWizard,
  _selfCheck: _clarifyWizardSelfCheck,
};

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initClarifyWizard);
} else {
  initClarifyWizard();
}
