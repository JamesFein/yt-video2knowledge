(function () {
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

