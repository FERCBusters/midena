(async () => {
  const { api, requireAuth, toast, escapeHtml } = window.MIDENA;
  await requireAuth();

  let folders = [];
  let draggedFolderId = null;
  const modal = new bootstrap.Modal(document.getElementById("folderModal"));

  function parentName(id) {
    return folders.find((f) => f.id === id)?.name || "—";
  }

  function childrenOf(parentId) {
    return folders
      .filter((f) => (f.parent_id || null) === (parentId || null))
      .sort(
        (a, b) => a.sort_order - b.sort_order || a.name.localeCompare(b.name),
      );
  }

  function descendantIds(id, out = new Set()) {
    childrenOf(id).forEach((child) => {
      out.add(child.id);
      descendantIds(child.id, out);
    });
    return out;
  }

  function folderPath(folder) {
    const byId = new Map(folders.map((f) => [f.id, f]));
    const parts = [];
    let current = folder;
    const seen = new Set();
    while (current && !seen.has(current.id)) {
      seen.add(current.id);
      parts.unshift(current.name);
      current = current.parent_id ? byId.get(current.parent_id) : null;
    }
    return parts.join(" / ");
  }

  function renderParentSelect(currentId = null) {
    const blocked = currentId ? descendantIds(currentId) : new Set();
    const options = folders
      .filter((f) => f.id !== currentId && !blocked.has(f.id))
      .slice()
      .sort((a, b) => folderPath(a).localeCompare(folderPath(b)))
      .map(
        (f) => `<option value="${f.id}">${escapeHtml(folderPath(f))}</option>`,
      )
      .join("");
    document.getElementById("parentId").innerHTML =
      '<option value="">No parent</option>' + options;
  }

  function treeHtml(parentId = null) {
    const kids = childrenOf(parentId);
    if (!kids.length)
      return parentId
        ? ""
        : '<div class="text-secondary small">No folders yet.</div>';
    return `<ul class="folder-tree">${kids
      .map(
        (f) => `
      <li>
        <div class="folder-tree-node" draggable="true" data-folder-node="${f.id}">
          <span class="folder-tree-grip" title="Drag to move"><i class="bi bi-grip-vertical"></i></span>
          <span class="fw-semibold"><i class="bi bi-folder me-1"></i>${escapeHtml(f.name)}</span>
          <span class="ms-auto small text-secondary">${escapeHtml(f.description || "")}</span>
          <button class="btn btn-link btn-sm py-0" data-edit="${f.id}" type="button">Edit</button>
          <button class="btn btn-link btn-sm py-0 text-danger" data-delete="${f.id}" type="button">Delete</button>
        </div>
        ${treeHtml(f.id)}
      </li>`,
      )
      .join("")}</ul>`;
  }

  function wireTreeDrag() {
    document.querySelectorAll("[data-folder-node]").forEach((node) => {
      node.addEventListener("dragstart", (ev) => {
        draggedFolderId = Number(node.dataset.folderNode);
        ev.dataTransfer.effectAllowed = "move";
        ev.dataTransfer.setData("text/plain", String(draggedFolderId));
        node.classList.add("dragging");
      });
      node.addEventListener("dragend", () => {
        node.classList.remove("dragging");
        draggedFolderId = null;
        document
          .querySelectorAll(".folder-tree-node.drag-over")
          .forEach((el) => el.classList.remove("drag-over"));
      });
      node.addEventListener("dragover", (ev) => {
        ev.preventDefault();
        node.classList.add("drag-over");
      });
      node.addEventListener("dragleave", () =>
        node.classList.remove("drag-over"),
      );
      node.addEventListener("drop", async (ev) => {
        ev.preventDefault();
        node.classList.remove("drag-over");
        const targetId = Number(node.dataset.folderNode);
        await moveFolder(draggedFolderId, targetId);
      });
    });

    const root = document.querySelector("[data-root-drop]");
    if (root) {
      root.addEventListener("dragover", (ev) => {
        ev.preventDefault();
        root.classList.add("drag-over");
      });
      root.addEventListener("dragleave", () =>
        root.classList.remove("drag-over"),
      );
      root.addEventListener("drop", async (ev) => {
        ev.preventDefault();
        root.classList.remove("drag-over");
        await moveFolder(draggedFolderId, null);
      });
    }
  }

  function renderTree() {
    document.getElementById("folderTree").innerHTML = treeHtml(null);
    document
      .querySelectorAll("[data-edit]")
      .forEach((btn) =>
        btn.addEventListener("click", () => edit(Number(btn.dataset.edit))),
      );
    document
      .querySelectorAll("[data-delete]")
      .forEach((btn) =>
        btn.addEventListener("click", () => remove(Number(btn.dataset.delete))),
      );
    wireTreeDrag();
  }

  function renderTable() {
    document.getElementById("folderRows").innerHTML =
      folders
        .map(
          (f) =>
            `<tr><td class="fw-semibold">${escapeHtml(f.name)}</td><td>${escapeHtml(parentName(f.parent_id))}</td><td>${escapeHtml(f.description || "")}</td><td class="text-end"><button class="btn btn-sm btn-outline-secondary" data-edit="${f.id}">Edit</button> <button class="btn btn-sm btn-outline-danger" data-delete="${f.id}">Delete</button></td></tr>`,
        )
        .join("") ||
      '<tr><td colspan="4" class="text-secondary p-4">No folders yet.</td></tr>';
    document
      .querySelectorAll("[data-edit]")
      .forEach((btn) =>
        btn.addEventListener("click", () => edit(Number(btn.dataset.edit))),
      );
    document
      .querySelectorAll("[data-delete]")
      .forEach((btn) =>
        btn.addEventListener("click", () => remove(Number(btn.dataset.delete))),
      );
  }

  async function load() {
    const data = await api("/api/v1/folders");
    folders = data.items || [];
    renderTree();
    renderTable();
  }

  async function moveFolder(folderId, parentId) {
    if (!folderId) return;
    if (folderId === parentId) {
      toast("A folder cannot be moved below itself.", "warning");
      return;
    }
    if (parentId && descendantIds(folderId).has(parentId)) {
      toast("A folder cannot be moved below its own descendant.", "warning");
      return;
    }
    const folder = folders.find((f) => f.id === folderId);
    if (!folder || (folder.parent_id || null) === (parentId || null)) return;
    try {
      await api(`/api/v1/folders/${folderId}`, {
        method: "PATCH",
        body: { parent_id: parentId },
      });
      toast("Folder moved.", "success");
      await load();
    } catch (err) {
      toast(err.message, "error");
    }
  }

  function edit(id) {
    const f = folders.find((x) => x.id === id);
    if (!f) return;
    document.getElementById("folderId").value = f.id;
    document.getElementById("folderName").value = f.name;
    document.getElementById("folderDescription").value = f.description || "";
    renderParentSelect(f.id);
    document.getElementById("parentId").value = f.parent_id || "";
    document.getElementById("folderModalTitle").textContent = "Edit folder";
    modal.show();
  }

  async function remove(id) {
    if (
      !confirm(
        "Delete this folder? Diagrams inside it will be moved to no folder.",
      )
    )
      return;
    try {
      await api(`/api/v1/folders/${id}`, { method: "DELETE" });
      toast("Folder deleted.", "success");
      await load();
    } catch (err) {
      toast(err.message, "error");
    }
  }

  document.getElementById("newFolderBtn").addEventListener("click", () => {
    document.getElementById("folderForm").reset();
    document.getElementById("folderId").value = "";
    renderParentSelect();
    document.getElementById("folderModalTitle").textContent = "New folder";
    modal.show();
  });

  document
    .getElementById("folderForm")
    .addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const id = document.getElementById("folderId").value;
      const body = {
        name: document.getElementById("folderName").value,
        parent_id: document.getElementById("parentId").value
          ? Number(document.getElementById("parentId").value)
          : null,
        description: document.getElementById("folderDescription").value,
      };
      try {
        await api(id ? `/api/v1/folders/${id}` : "/api/v1/folders", {
          method: id ? "PATCH" : "POST",
          body,
        });
        modal.hide();
        await load();
      } catch (err) {
        toast(err.message, "error");
      }
    });

  try {
    await load();
  } catch (err) {
    toast(err.message, "error");
  }
})();
