(async () => {
  const { api, requireAuth, toast, escapeHtml } = window.MIDENA;
  const me = await requireAuth();
  if (me.effective_role !== "admin") {
    window.location.href = "/index.html";
    return;
  }

  const colours = [
    "#6f42c1",
    "#0d6efd",
    "#198754",
    "#dc3545",
    "#fd7e14",
    "#20c997",
    "#0dcaf0",
    "#d63384",
    "#6610f2",
    "#6c757d",
  ];
  let tags = [];

  function randomColour() {
    return colours[Math.floor(Math.random() * colours.length)];
  }

  function normaliseHex(value) {
    const colour = String(value || "").trim();
    return /^#[0-9a-fA-F]{6}$/.test(colour)
      ? colour.toLowerCase()
      : randomColour();
  }

  function renderRows() {
    document.getElementById("tagCount").textContent = String(tags.length);
    const rows = document.getElementById("tagRows");
    if (!tags.length) {
      rows.innerHTML =
        '<tr><td colspan="4" class="text-secondary p-4">No tags yet.</td></tr>';
      return;
    }
    rows.innerHTML = tags
      .map(
        (tag) => `<tr data-tag-id="${tag.id}">
      <td>
        <input class="form-control" data-tag-name="${tag.id}" value="${escapeHtml(tag.name)}" maxlength="80" aria-label="Tag name">
      </td>
      <td><input class="form-control form-control-color" type="color" data-tag-color="${tag.id}" value="${escapeHtml(normaliseHex(tag.color))}" title="Choose tag colour"></td>
      <td><span class="badge text-bg-light">${Number(tag.count || 0)}</span></td>
      <td class="text-end"><button class="btn btn-sm btn-outline-primary" type="button" data-save-tag="${tag.id}"><i class="bi bi-check2 me-1"></i>Save</button></td>
    </tr>`,
      )
      .join("");
    rows
      .querySelectorAll("[data-save-tag]")
      .forEach((btn) =>
        btn.addEventListener("click", () =>
          saveTag(Number(btn.dataset.saveTag)),
        ),
      );
  }

  async function loadTags() {
    const data = await api("/api/v1/tags");
    tags = data.items || [];
    renderRows();
  }

  async function saveTag(id) {
    const name = document.querySelector(`[data-tag-name="${id}"]`).value.trim();
    const color = document.querySelector(`[data-tag-color="${id}"]`).value;
    if (!name) {
      toast("Tag name must not be empty.", "warning");
      return;
    }
    await api(`/api/v1/tags/${id}`, { method: "PATCH", body: { name, color } });
    toast("Tag saved.", "success");
    await loadTags();
  }

  document.getElementById("randomTagColorBtn").addEventListener("click", () => {
    document.getElementById("newTagColor").value = randomColour();
  });
  document
    .getElementById("newTagForm")
    .addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const name = document.getElementById("newTagName").value.trim();
      const color = document.getElementById("newTagColor").value;
      if (!name) {
        toast("Tag name must not be empty.", "warning");
        return;
      }
      try {
        await api("/api/v1/tags", { method: "POST", body: { name, color } });
        toast("Tag added.", "success");
        document.getElementById("newTagForm").reset();
        document.getElementById("newTagColor").value = randomColour();
        await loadTags();
      } catch (err) {
        toast(err.message, "error");
      }
    });

  document.getElementById("newTagColor").value = randomColour();
  try {
    await loadTags();
  } catch (err) {
    toast(err.message, "error");
  }
})();
