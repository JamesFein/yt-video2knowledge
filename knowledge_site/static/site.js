(function () {
  const scrollKey = `knowledge-site:scroll:${window.location.pathname}${window.location.search}`;
  let saveScrollTimer = null;

  function getSessionStorage() {
    try {
      return window.sessionStorage;
    } catch (error) {
      return null;
    }
  }

  function saveScrollPosition(options = {}) {
    const storage = getSessionStorage();
    if (!storage) {
      return;
    }
    const scrollY = Math.max(0, Math.round(window.scrollY));
    const storedY = Number.parseInt(storage.getItem(scrollKey) || "", 10);
    if (options.preservePositiveOnZero && scrollY === 0 && Number.isFinite(storedY) && storedY > 0) {
      return;
    }
    storage.setItem(scrollKey, String(scrollY));
  }

  function restoreScrollPosition() {
    if (window.location.hash) {
      return;
    }
    const storage = getSessionStorage();
    if (!storage) {
      return;
    }
    const value = Number.parseInt(storage.getItem(scrollKey) || "", 10);
    if (!Number.isFinite(value) || value <= 0) {
      return;
    }
    if (Math.abs(window.scrollY - value) > 8) {
      window.scrollTo(0, value);
    }
    window.setTimeout(() => {
      if (Math.abs(window.scrollY - value) > 8) {
        window.scrollTo(0, value);
      }
    }, 80);
  }

  function shouldSaveBeforeNavigation(link, event) {
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
      return false;
    }
    if (link.target && link.target !== "_self") {
      return false;
    }
    if (link.hasAttribute("download")) {
      return false;
    }
    const destination = new URL(link.href, window.location.href);
    return destination.origin === window.location.origin;
  }

  if ("scrollRestoration" in window.history) {
    window.history.scrollRestoration = "auto";
  }
  restoreScrollPosition();
  window.addEventListener(
    "scroll",
    () => {
      window.clearTimeout(saveScrollTimer);
      saveScrollTimer = window.setTimeout(saveScrollPosition, 100);
    },
    { passive: true }
  );
  window.addEventListener(
    "click",
    (event) => {
      if (!(event.target instanceof Element)) {
        return;
      }
      const link = event.target.closest("a[href]");
      if (link && shouldSaveBeforeNavigation(link, event)) {
        saveScrollPosition();
      }
    },
    true
  );
  window.addEventListener("pagehide", () => {
    saveScrollPosition({ preservePositiveOnZero: true });
  });
  window.addEventListener("pageshow", restoreScrollPosition);

  const workspace = document.querySelector("[data-video-id]");
  if (!workspace) {
    return;
  }

  const videoId = workspace.getAttribute("data-video-id");
  const editor = workspace.querySelector("[data-meta-editor]");
  const saveState = workspace.querySelector("[data-save-state]");

  function setState(text) {
    if (saveState) {
      saveState.textContent = text;
    }
  }

  function selectedBlockText() {
    const checked = workspace.querySelectorAll("[data-block-check]:checked");
    return Array.from(checked)
      .map((input) => {
        const block = input.closest(".summary-block");
        const text = block ? block.querySelector(".block-text") : null;
        return text ? text.value.trim() : "";
      })
      .filter(Boolean)
      .join("\n\n");
  }

  async function saveMeta(content) {
    setState("保存中");
    const response = await fetch(`/api/v1/videos/${encodeURIComponent(videoId)}/meta-summary`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content }),
    });
    if (!response.ok) {
      setState("保存失败");
      return;
    }
    const payload = await response.json();
    editor.value = payload.content || "";
    setState("已保存");
  }

  workspace.addEventListener("click", (event) => {
    const button = event.target.closest("[data-action]");
    if (!button) {
      return;
    }
    const action = button.getAttribute("data-action");
    if (action === "append-selected") {
      const text = selectedBlockText();
      if (!text) {
        return;
      }
      const prefix = editor.value.trim() ? `${editor.value.trim()}\n\n` : "";
      editor.value = `${prefix}${text}`;
      setState("已写入");
    }
    if (action === "save-meta") {
      saveMeta(editor.value);
    }
    if (action === "clear-meta") {
      editor.value = "";
      saveMeta("");
    }
  });
})();
