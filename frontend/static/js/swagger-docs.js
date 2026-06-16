/**
 * Swagger /docs quick-jump cards — expand tag + operation and scroll into view.
 */

let swaggerSystem = null;

function captureSwaggerSystem(system) {
  swaggerSystem = system;
}

function scrollToSwaggerPanel() {
  document.querySelector(".swagger-wrap")?.scrollIntoView({ behavior: "smooth", block: "start" });
}

function updateShareableHash(tag, operationId) {
  const hash = `#/${encodeURIComponent(tag)}/${encodeURIComponent(operationId)}`;
  if (window.location.hash !== hash) {
    window.history.replaceState(null, "", hash);
  }
}

function expandTagDom(tag) {
  const tagEl = document.querySelector(`#swagger-ui h3.opblock-tag[data-tag="${tag}"]`);
  if (!tagEl) return false;
  const section = tagEl.closest(".opblock-tag-section");
  if (section && !section.classList.contains("is-open")) {
    tagEl.click();
  }
  return true;
}

function findOperationBlock({ operationId, path, method }) {
  const blocks = document.querySelectorAll("#swagger-ui .opblock");
  const methodNeedle = (method || "").trim().toLowerCase();

  if (path && methodNeedle) {
    for (const block of blocks) {
      const pathEl = block.querySelector(".opblock-summary-path[data-path]");
      const methodEl = block.querySelector(".opblock-summary-method");
      if (pathEl?.dataset.path === path && methodEl?.textContent?.trim().toLowerCase() === methodNeedle) {
        return block;
      }
    }
  }

  if (operationId) {
    for (const block of blocks) {
      const opIdEl = block.querySelector(".opblock-summary-operation-id");
      if (opIdEl?.textContent?.trim() === operationId) {
        return block;
      }
    }
  }

  return null;
}

function revealOperationBlock(block) {
  if (!block) return false;
  if (!block.classList.contains("is-open")) {
    block.querySelector(".opblock-summary")?.click();
  }
  block.scrollIntoView({ behavior: "smooth", block: "center" });
  return true;
}

function revealViaLayoutActions(tag, operationId) {
  if (!swaggerSystem?.layoutActions) return false;

  const tagKey = ["operations-tag", tag];
  const opKey = ["operations", tag, operationId];
  const { layoutActions } = swaggerSystem;

  layoutActions.show(tagKey, true);
  layoutActions.show(opKey, true);
  window.setTimeout(() => {
    layoutActions.scrollTo(opKey);
  }, 60);

  return true;
}

function revealOperationDom(target, retriesLeft) {
  expandTagDom(target.tag);
  const block = findOperationBlock(target);
  if (revealOperationBlock(block)) {
    return;
  }
  if (retriesLeft <= 0) return;
  window.setTimeout(() => revealOperationDom(target, retriesLeft - 1), 120);
}

function navigateSwaggerQuickLink(target) {
  const { tag, operationId } = target;
  if (!tag || !operationId) return;

  updateShareableHash(tag, operationId);
  scrollToSwaggerPanel();
  const usedLayout = revealViaLayoutActions(tag, operationId);

  window.setTimeout(() => {
    revealOperationDom(target, 8);
  }, usedLayout ? 100 : 0);
}

function initSwaggerQuickLinks() {
  document.querySelectorAll(".api-quick-links .quick-link-card[data-swagger-tag]").forEach((link) => {
    link.addEventListener("click", (event) => {
      event.preventDefault();
      navigateSwaggerQuickLink({
        tag: link.dataset.swaggerTag,
        operationId: link.dataset.swaggerOp,
        path: link.dataset.swaggerPath || "",
        method: link.dataset.swaggerMethod || "",
      });
    });
  });
}

function navigateFromLocationHash() {
  const raw = window.location.hash;
  if (!raw || raw.length < 3 || raw.charAt(1) !== "/") return;

  const parts = decodeURIComponent(raw.slice(1))
    .split("/")
    .filter(Boolean);
  if (parts.length < 2) return;

  navigateSwaggerQuickLink({
    tag: parts[0],
    operationId: parts[1],
    path: "",
    method: "",
  });
}

function createCaptureSystemPlugin() {
  return {
    statePlugins: {
      spec: {
        wrapActions: {
          updateJsonSpec: (original, system) => (...args) => {
            captureSwaggerSystem(system);
            return original(...args);
          },
        },
      },
    },
  };
}

window.FtdcSwaggerDocs = {
  captureSwaggerSystem,
  createCaptureSystemPlugin,
  initSwaggerQuickLinks,
  navigateFromLocationHash,
  navigateSwaggerQuickLink,
};
