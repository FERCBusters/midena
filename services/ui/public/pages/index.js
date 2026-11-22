(async () => {
  const { api, requireAuth, toast, escapeHtml, formatDate } = window.MIDENA;
  await requireAuth();
  const state = {
    offset: 0,
    limit: 50,
    folders: [],
    currentFolderId: null,
    selectedTags: new Set(),
    tags: [],
    tagMap: new Map(),
  };
  const newDiagramAi = { type: null, messages: [], lastCode: "", status: null };
  const modal = new bootstrap.Modal(document.getElementById("diagramModal"));

  function tagKey(value) {
    return String(value || "")
      .trim()
      .toLowerCase();
  }

  function tagColour(name) {
    return state.tagMap.get(tagKey(name))?.color || "#f8f9fa";
  }

  function textColourForBackground(color) {
    const hex = String(color || "").replace("#", "");
    if (!/^[0-9a-fA-F]{6}$/.test(hex)) return "#212529";
    const [r, g, b] = [0, 2, 4].map(
      (idx) => parseInt(hex.slice(idx, idx + 2), 16) / 255,
    );
    const linear = [r, g, b].map((c) =>
      c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4,
    );
    const luminance =
      0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2];
    return luminance < 0.45 ? "#ffffff" : "#212529";
  }

  function tagSearchUrl(name) {
    return `/index.html?tag=${encodeURIComponent(String(name || "").trim())}`;
  }

  function tagBadge(name, extra = "") {
    const color = tagColour(name);
    const textColor = textColourForBackground(color);
    return `<span class="badge rounded-pill me-1 ${extra}" style="background-color:${escapeHtml(color)}; color:${textColor};">${escapeHtml(name)}</span>`;
  }

  function tagLinkBadge(name, extra = "") {
    const color = tagColour(name);
    const textColor = textColourForBackground(color);
    const label = escapeHtml(name);
    return `<a class="badge rounded-pill me-1 tag-link-pill ${extra}" href="${tagSearchUrl(name)}" target="_blank" rel="noopener noreferrer" title="Open diagrams tagged ${label}" style="background-color:${escapeHtml(color)}; color:${textColor};">${label}<i class="bi bi-box-arrow-up-right ms-1" aria-hidden="true"></i></a>`;
  }

  function tagsFromInput(input) {
    return input.value
      .split(",")
      .map((x) => x.trim())
      .filter(Boolean);
  }

  function setTagsOnInput(input, tags) {
    const out = [];
    const seen = new Set();
    tags.forEach((tag) => {
      const clean = String(tag || "").trim();
      const key = tagKey(clean);
      if (!clean || seen.has(key)) return;
      seen.add(key);
      out.push(clean);
    });
    input.value = out.join(", ");
  }

  function appendTagToInput(input, tag) {
    setTagsOnInput(input, [...tagsFromInput(input), tag]);
    input.focus();
    renderDiagramTagChoices();
  }

  function replaceCurrentTag(input, tag) {
    const parts = input.value.split(",");
    parts[parts.length - 1] = ` ${tag}`;
    setTagsOnInput(input, parts);
    input.focus();
    renderDiagramTagChoices();
  }

  function currentTagQuery(input) {
    return String(input.value.split(",").pop() || "")
      .trim()
      .toLowerCase();
  }

  function renderDiagramTagSuggestions() {
    const menu = document.getElementById("diagramTagSuggestionsMenu");
    const input = document.getElementById("diagramTags");
    if (!menu || !input) return;
    const query = currentTagQuery(input);
    const selected = new Set(tagsFromInput(input).map(tagKey));
    const matches = query
      ? state.tags
          .filter(
            (tag) =>
              tag.name.toLowerCase().includes(query) &&
              !selected.has(tagKey(tag.name)),
          )
          .slice(0, 12)
      : [];
    menu.classList.toggle("d-none", !matches.length);
    menu.innerHTML = matches
      .map(
        (tag) =>
          `<button class="tag-choice" type="button" data-suggest-tag="${escapeHtml(tag.name)}" style="--tag-color:${escapeHtml(tag.color)}">${escapeHtml(tag.name)}</button>`,
      )
      .join("");
    menu
      .querySelectorAll("[data-suggest-tag]")
      .forEach((btn) =>
        btn.addEventListener("click", () =>
          replaceCurrentTag(input, btn.dataset.suggestTag),
        ),
      );
  }

  function renderDiagramTagChoices() {
    const host = document.getElementById("diagramTagChoices");
    const input = document.getElementById("diagramTags");
    if (!host || !input) return;
    const selected = tagsFromInput(input);
    host.innerHTML =
      selected
        .map(
          (tag) =>
            `${tagBadge(tag, "tag-selected-pill")}<button class="tag-remove" type="button" aria-label="Remove ${escapeHtml(tag)}" data-remove-input-tag="${escapeHtml(tag)}"><i class="bi bi-x"></i></button>`,
        )
        .join("") ||
      '<span class="small text-secondary">No tags selected. Type to create or choose an existing tag.</span>';
    host.querySelectorAll("[data-remove-input-tag]").forEach((btn) =>
      btn.addEventListener("click", () => {
        setTagsOnInput(
          input,
          tagsFromInput(input).filter(
            (tag) => tagKey(tag) !== tagKey(btn.dataset.removeInputTag),
          ),
        );
        renderDiagramTagChoices();
      }),
    );
    renderDiagramTagSuggestions();
  }

  function bindDiagramTagInput() {
    const input = document.getElementById("diagramTags");
    if (!input || input.dataset.tagEditorBound) return;
    input.dataset.tagEditorBound = "1";
    input.addEventListener("input", renderDiagramTagChoices);
    input.addEventListener("focus", renderDiagramTagChoices);
    input.addEventListener("blur", () =>
      window.setTimeout(
        () =>
          document
            .getElementById("diagramTagSuggestionsMenu")
            ?.classList.add("d-none"),
        180,
      ),
    );
  }

  async function loadTagCatalog() {
    const data = await api("/v1/tags");
    state.tags = data.items || [];
    state.tagMap = new Map(state.tags.map((tag) => [tagKey(tag.name), tag]));
    const datalist = document.getElementById("tagSuggestions");
    if (datalist)
      datalist.innerHTML = state.tags
        .map((tag) => `<option value="${escapeHtml(tag.name)}"></option>`)
        .join("");
    renderDiagramTagChoices();
  }

  function orderedFolders() {
    const byParent = new Map();
    const byId = new Map();
    state.folders.forEach((folder) => {
      byId.set(Number(folder.id), folder);
      const parentKey =
        folder.parent_id === null || folder.parent_id === undefined
          ? "root"
          : String(folder.parent_id);
      if (!byParent.has(parentKey)) byParent.set(parentKey, []);
      byParent.get(parentKey).push(folder);
    });
    byParent.forEach((items) =>
      items.sort(
        (a, b) =>
          Number(a.sort_order || 0) - Number(b.sort_order || 0) ||
          String(a.name || "").localeCompare(String(b.name || "")),
      ),
    );
    const output = [];
    const visited = new Set();
    function visit(folder, depth, pathParts) {
      const id = Number(folder.id);
      if (visited.has(id)) return;
      visited.add(id);
      const path = [...pathParts, folder.name || "Untitled folder"];
      output.push({ ...folder, depth, path: path.join(" / ") });
      (byParent.get(String(id)) || []).forEach((child) =>
        visit(child, depth + 1, path),
      );
    }
    (byParent.get("root") || []).forEach((folder) => visit(folder, 0, []));
    state.folders.forEach((folder) => {
      const id = Number(folder.id);
      if (!visited.has(id))
        visit(folder, byId.has(Number(folder.parent_id)) ? 1 : 0, []);
    });
    return output;
  }

  function folderOptions(firstLabel) {
    return (
      `<option value="">${escapeHtml(firstLabel)}</option>` +
      orderedFolders()
        .map((folder) => {
          const indent =
            folder.depth > 0 ? `${"&nbsp;&nbsp;".repeat(folder.depth)}↳ ` : "";
          return `<option value="${folder.id}" title="${escapeHtml(folder.path)}">${indent}${escapeHtml(folder.name)}</option>`;
        })
        .join("")
    );
  }

  function folderById(id) {
    const wanted = Number(id);
    return state.folders.find((folder) => Number(folder.id) === wanted) || null;
  }

  function currentFolder() {
    return state.currentFolderId ? folderById(state.currentFolderId) : null;
  }

  function folderAncestors(folderId) {
    const chain = [];
    const seen = new Set();
    let folder = folderById(folderId);
    while (folder && !seen.has(Number(folder.id))) {
      seen.add(Number(folder.id));
      chain.unshift(folder);
      folder = folder.parent_id ? folderById(folder.parent_id) : null;
    }
    return chain;
  }

  function childFolders(parentId) {
    const parentKey =
      parentId === null || parentId === undefined ? null : Number(parentId);
    return state.folders
      .filter((folder) => {
        const actual =
          folder.parent_id === null || folder.parent_id === undefined
            ? null
            : Number(folder.parent_id);
        return actual === parentKey;
      })
      .sort(
        (a, b) =>
          Number(a.sort_order || 0) - Number(b.sort_order || 0) ||
          String(a.name || "").localeCompare(String(b.name || "")),
      );
  }

  function folderHref(folderId) {
    const params = new URLSearchParams(window.location.search || "");
    if (folderId) params.set("folder_id", String(folderId));
    else params.delete("folder_id");
    const query = params.toString();
    return `${window.location.pathname || "/index.html"}${query ? `?${query}` : ""}`;
  }

  function syncFolderUrl(push = false) {
    const url = folderHref(state.currentFolderId);
    try {
      window.history[push ? "pushState" : "replaceState"]({}, "", url);
    } catch (_) {}
  }

  function setCurrentFolder(folderId, { push = false, reload = true } = {}) {
    const next = folderId ? Number(folderId) : null;
    state.currentFolderId =
      Number.isFinite(next) && folderById(next) ? next : null;
    const select = document.getElementById("folderFilter");
    if (select)
      select.value = state.currentFolderId ? String(state.currentFolderId) : "";
    state.offset = 0;
    renderFolderBrowser();
    syncFolderUrl(push);
    if (reload) loadDiagrams().catch((err) => toast(err.message, "error"));
  }

  function renderFolderBrowser() {
    const breadcrumb = document.getElementById("folderBreadcrumb");
    const childrenHost = document.getElementById("folderChildren");
    if (!breadcrumb || !childrenHost) return;
    const folder = currentFolder();
    const chain = folder ? folderAncestors(folder.id) : [];
    const crumbs = [
      `<a href="${escapeHtml(folderHref(null))}" data-folder-enter="" class="folder-browser-crumb ${folder ? "" : "active"}">All diagrams</a>`,
      ...chain.map((item, idx) => {
        const active = idx === chain.length - 1;
        return `<a href="${escapeHtml(folderHref(item.id))}" data-folder-enter="${escapeHtml(item.id)}" class="folder-browser-crumb ${active ? "active" : ""}">${escapeHtml(item.name)}</a>`;
      }),
    ];
    breadcrumb.innerHTML = crumbs.join(
      '<span class="folder-browser-separator">/</span>',
    );

    const children = childFolders(folder ? folder.id : null);
    if (!children.length) {
      childrenHost.innerHTML =
        '<div class="text-secondary small">No child folders here.</div>';
    } else {
      childrenHost.innerHTML = children
        .map(
          (
            child,
          ) => `<a class="folder-browser-tile" href="${escapeHtml(folderHref(child.id))}" data-folder-enter="${escapeHtml(child.id)}">
        <span class="folder-browser-icon"><i class="bi bi-folder2-open"></i></span>
        <span class="folder-browser-title">${escapeHtml(child.name)}</span>
        ${child.description ? `<span class="folder-browser-description">${escapeHtml(child.description)}</span>` : ""}
      </a>`,
        )
        .join("");
    }
    [breadcrumb, childrenHost].forEach((host) =>
      host.querySelectorAll("[data-folder-enter]").forEach((link) =>
        link.addEventListener("click", (ev) => {
          ev.preventDefault();
          setCurrentFolder(link.dataset.folderEnter || null, { push: true });
        }),
      ),
    );
  }

  async function loadFolders() {
    const data = await api("/v1/folders");
    state.folders = data?.items || [];
    for (const sel of [
      document.getElementById("folderFilter"),
      document.getElementById("diagramFolder"),
    ]) {
      const firstLabel =
        sel.id === "folderFilter" ? "All folders" : "No folder";
      sel.innerHTML = folderOptions(firstLabel);
      if (sel.id === "folderFilter" && state.currentFolderId)
        sel.value = String(state.currentFolderId);
    }
    if (state.currentFolderId && !folderById(state.currentFolderId))
      state.currentFolderId = null;
    renderFolderBrowser();
  }

  function tagPillStyle(color) {
    const textColor = textColourForBackground(color);
    return `background-color:${escapeHtml(color)}; color:${textColor}; border-color:${escapeHtml(color)};`;
  }

  function tagCountBadgeStyle(color) {
    const textColor = textColourForBackground(color);
    const badgeBg =
      textColor === "#ffffff" ? "rgba(255,255,255,.22)" : "rgba(0,0,0,.08)";
    return `background-color:${badgeBg}; color:${textColor};`;
  }

  function renderSelectedTags() {
    const host = document.getElementById("selectedTags");
    const tags = Array.from(state.selectedTags).sort((a, b) =>
      a.localeCompare(b),
    );
    host.innerHTML =
      tags
        .map(
          (tag) =>
            `<button class="btn btn-sm rounded-pill tag-filter-pill tag-filter-selected" style="${tagPillStyle(tagColour(tag))}" type="button" data-remove-tag="${escapeHtml(tag)}">${escapeHtml(tag)} <i class="bi bi-x"></i></button>`,
        )
        .join("") ||
      '<span class="small text-secondary">No tag filters selected.</span>';
    host.querySelectorAll("[data-remove-tag]").forEach((btn) =>
      btn.addEventListener("click", () => {
        state.selectedTags.delete(btn.dataset.removeTag);
        state.offset = 0;
        renderSelectedTags();
        loadTagCloud().catch(() => {});
        loadDiagrams().catch((err) => toast(err.message, "error"));
      }),
    );
  }

  async function loadTagCloud() {
    const data = await api("/v1/diagram-tags");
    const host = document.getElementById("tagCloud");
    host.innerHTML =
      (data.items || [])
        .map((item) => {
          const selected = state.selectedTags.has(item.tag);
          const color = item.color || tagColour(item.tag);
          return `<a class="btn btn-sm rounded-pill me-1 mb-1 tag-filter-pill ${selected ? "tag-filter-selected" : ""}" style="${tagPillStyle(color)}" href="${tagSearchUrl(item.tag)}" target="_blank" rel="noopener noreferrer" title="Open diagrams tagged ${escapeHtml(item.tag)}">${escapeHtml(item.tag)} <span class="badge" style="${tagCountBadgeStyle(color)}">${item.count}</span><i class="bi bi-box-arrow-up-right ms-1" aria-hidden="true"></i></a>`;
        })
        .join("") || '<span class="small text-secondary">No tags yet.</span>';
  }

  function visibilityBadge(visibility) {
    if (visibility === "public")
      return '<span class="badge text-bg-success">Public</span>';
    if (visibility === "internal")
      return '<span class="badge text-bg-info">Private internal</span>';
    return '<span class="badge text-bg-secondary">Private to me</span>';
  }

  function bindSearchFiltersToggle() {
    const filters = document.getElementById("searchFiltersBody");
    const button = document.getElementById("searchFiltersToggle");
    if (!filters || !button) return;
    const setLabel = (expanded) => {
      button.setAttribute("aria-expanded", expanded ? "true" : "false");
      button.querySelector("span").textContent = expanded
        ? "Collapse"
        : "Expand";
      const icon = button.querySelector("i");
      icon.classList.toggle("bi-chevron-up", expanded);
      icon.classList.toggle("bi-chevron-down", !expanded);
    };
    filters.addEventListener("shown.bs.collapse", () => setLabel(true));
    filters.addEventListener("hidden.bs.collapse", () => setLabel(false));
    setLabel(filters.classList.contains("show"));
  }

  async function cloneDiagram(ref) {
    if (!window.confirm("Clone this diagram into a new editable diagram?"))
      return;
    const cloned = await api(`/v1/diagrams/${encodeURIComponent(ref)}/clone`, {
      method: "POST",
    });
    toast("Diagram cloned.", "success");
    window.location.href = `/diagram.html?id=${encodeURIComponent(cloned.uuid)}`;
  }

  function applyInitialFiltersFromUrl() {
    const params = new URLSearchParams(window.location.search || "");
    const rawValues = [params.get("tag"), params.get("tags")].filter(Boolean);
    rawValues
      .flatMap((value) => String(value).split(","))
      .forEach((value) => {
        const tag = value.trim();
        if (tag) state.selectedTags.add(tag);
      });
    const folderParam = params.get("folder_id");
    if (folderParam && /^\d+$/.test(folderParam))
      state.currentFolderId = Number(folderParam);
    if (state.selectedTags.size || state.currentFolderId) {
      const filters = document.getElementById("searchFiltersBody");
      const button = document.getElementById("searchFiltersToggle");
      filters?.classList.add("show");
      button?.setAttribute("aria-expanded", "true");
    }
    if (state.selectedTags.size)
      document.title = `${Array.from(state.selectedTags).join(", ")} · MIDENA diagrams`;
  }

  async function loadDiagrams() {
    const params = new URLSearchParams({
      limit: String(state.limit),
      offset: String(state.offset),
    });
    const q = document.getElementById("q").value.trim();
    const folder = state.currentFolderId
      ? String(state.currentFolderId)
      : document.getElementById("folderFilter").value;
    const visibility = document.getElementById("visibilityFilter").value;
    const type = document.getElementById("typeFilter").value;
    if (q) params.set("q", q);
    if (folder) params.set("folder_id", folder);
    if (visibility) params.set("visibility", visibility);
    if (type) params.set("diagram_type", type);
    if (state.selectedTags.size)
      params.set("tags", Array.from(state.selectedTags).join(","));
    const data = await api(`/v1/diagrams?${params}`);
    const rows = document.getElementById("diagramRows");
    if (!data?.items?.length) {
      rows.innerHTML =
        '<tr><td colspan="8" class="text-secondary p-4">No diagrams found.</td></tr>';
    } else {
      rows.innerHTML = data.items
        .map((d) => {
          const folderLabel = d.folder_name || "—";
          const folderCell = d.folder_id
            ? `<a href="${escapeHtml(folderHref(d.folder_id))}" data-folder-enter="${escapeHtml(d.folder_id)}">${escapeHtml(folderLabel)}</a>`
            : '<span class="text-secondary">—</span>';
          const diagramTypeLabel =
            d.diagram_type === "sequence"
              ? "Web sequence"
              : d.diagram_type === "flowchart"
                ? "Flowchart"
                : "BPMN";
          const diagramTypeBadge =
            d.diagram_type === "sequence"
              ? '<span class="badge text-bg-info">Web sequence</span>'
              : d.diagram_type === "flowchart"
                ? '<span class="badge text-bg-success">Flowchart</span>'
                : '<span class="badge text-bg-primary">BPMN</span>';
          const lockLabel = d.locked
            ? `Locked${d.locked_by ? ` by ${d.locked_by}` : ""}`
            : "Unlocked";
          return `<tr>
        <td data-sort="${escapeHtml(d.name || "")}"><a class="fw-semibold" href="/diagram.html?id=${encodeURIComponent(d.uuid)}">${escapeHtml(d.name)}</a><div class="small text-secondary">${escapeHtml((d.description || "").slice(0, 120))}</div><div class="small">${(d.tags || []).map((t) => tagLinkBadge(t)).join("")}</div></td>
        <td data-sort="${escapeHtml(folderLabel)}">${folderCell}</td>
        <td data-sort="${escapeHtml(diagramTypeLabel)}">${diagramTypeBadge}</td>
        <td data-sort="${Number(d.current_version_number || 0)}">${d.current_version_number ? `v${d.current_version_number}` : "—"}</td>
        <td data-sort="${escapeHtml(d.visibility || "")}">${visibilityBadge(d.visibility)}</td>
        <td data-sort="${escapeHtml(lockLabel)}">${d.locked ? `<span class="badge text-bg-warning">Locked${d.locked_by ? ` by ${escapeHtml(d.locked_by)}` : ""}</span>` : '<span class="text-secondary">Unlocked</span>'}</td>
        <td data-sort="${escapeHtml(d.updated_at || "")}">${escapeHtml(formatDate(d.updated_at))}</td>
        <td class="text-end"><div class="btn-group btn-group-sm"><a class="btn btn-outline-primary" href="/diagram.html?id=${encodeURIComponent(d.uuid)}">Open</a><button class="btn btn-outline-secondary" type="button" data-clone-diagram="${escapeHtml(d.uuid)}"><i class="bi bi-files me-1"></i>Clone</button></div></td>
      </tr>`;
        })
        .join("");
    }
    rows.querySelectorAll("[data-folder-enter]").forEach((link) =>
      link.addEventListener("click", (ev) => {
        ev.preventDefault();
        setCurrentFolder(link.dataset.folderEnter || null, { push: true });
      }),
    );
    rows
      .querySelectorAll("[data-clone-diagram]")
      .forEach((btn) =>
        btn.addEventListener("click", () =>
          cloneDiagram(btn.dataset.cloneDiagram).catch((err) =>
            toast(err.message, "error"),
          ),
        ),
      );
    document.getElementById("pagerInfo").textContent = data.total
      ? `${data.offset + 1}-${Math.min(data.offset + data.limit, data.total)} of ${data.total}`
      : "0 of 0";
    document.getElementById("prevPage").disabled = state.offset <= 0;
    document.getElementById("nextPage").disabled =
      state.offset + state.limit >= data.total;
  }

  function currentNewDiagramAiType() {
    const type = document.getElementById("diagramType")?.value || "bpmn";
    return ["sequence", "flowchart"].includes(type) ? type : null;
  }

  function newDiagramAiTypeLabel(type = currentNewDiagramAiType()) {
    return type === "flowchart" ? "flowchart" : "web sequence diagram";
  }

  function resetNewDiagramAiChat() {
    newDiagramAi.messages = [];
    newDiagramAi.lastCode = "";
    renderNewDiagramAiChat();
  }

  function ensureNewDiagramAiType() {
    const type = currentNewDiagramAiType();
    if (newDiagramAi.type !== type) {
      newDiagramAi.type = type;
      newDiagramAi.messages = [];
      newDiagramAi.lastCode = "";
    }
    return type;
  }

  function renderNewDiagramAiChat() {
    const log = document.getElementById("newDiagramAiChatMessages");
    if (!log) return;
    const type = currentNewDiagramAiType();
    if (!type) {
      log.innerHTML =
        '<div class="text-secondary small p-2">Choose Web sequence diagram or Flowchart to use AI generation.</div>';
      document.getElementById("newDiagramUseAiCodeBtn").disabled = true;
      return;
    }
    if (!newDiagramAi.messages.length) {
      log.innerHTML = `<div class="text-secondary small p-2">Describe the ${escapeHtml(newDiagramAiTypeLabel(type))} you want. Follow up after each response to refine the code.</div>`;
    } else {
      log.innerHTML = newDiagramAi.messages
        .map((msg) => {
          const role = msg.role === "assistant" ? "AI code" : "You";
          const body =
            msg.role === "assistant"
              ? `<pre class="ai-code-block mb-0"><code>${escapeHtml(msg.content)}</code></pre>`
              : `<div>${escapeHtml(msg.content)}</div>`;
          return `<div class="ai-chat-message ai-chat-${escapeHtml(msg.role)} mb-2"><div class="small fw-semibold text-secondary mb-1">${role}</div>${body}</div>`;
        })
        .join("");
      log.scrollTop = log.scrollHeight;
    }
    document.getElementById("newDiagramUseAiCodeBtn").disabled =
      !newDiagramAi.lastCode;
  }

  async function loadNewDiagramAiStatus() {
    if (newDiagramAi.status) return newDiagramAi.status;
    try {
      newDiagramAi.status = await api("/v1/diagram-ai/status");
    } catch (err) {
      newDiagramAi.status = {
        enabled: false,
        error: err.message || String(err),
      };
    }
    return newDiagramAi.status;
  }

  async function refreshNewDiagramAiPanel() {
    const type = ensureNewDiagramAiType();
    const status = await loadNewDiagramAiStatus();
    const warning = document.getElementById("newDiagramAiConfigWarning");
    const canUse = Boolean(type && status?.enabled);
    warning.classList.toggle("d-none", canUse);
    if (!type)
      warning.textContent =
        "Choose Web sequence diagram or Flowchart before asking AI for diagram code.";
    else
      warning.textContent = status?.enabled
        ? ""
        : status?.error ||
          "AI diagram generation is not configured. Set MIDENA_AI_API_KEY and MIDENA_AI_MODEL in the API environment.";
    document.getElementById("newDiagramSendAiPromptBtn").disabled = !canUse;
    renderNewDiagramAiChat();
  }

  async function sendNewDiagramAiPrompt() {
    const type = ensureNewDiagramAiType();
    if (!type) {
      toast("Choose Web sequence diagram or Flowchart first.", "warning");
      return;
    }
    const promptEl = document.getElementById("newDiagramAiPrompt");
    const promptText = String(promptEl.value || "").trim();
    if (!promptText) {
      toast("Describe what you want the diagram to show.", "warning");
      return;
    }
    newDiagramAi.messages.push({ role: "user", content: promptText });
    promptEl.value = "";
    renderNewDiagramAiChat();
    const sendBtn = document.getElementById("newDiagramSendAiPromptBtn");
    const oldSendText = sendBtn.innerHTML;
    sendBtn.disabled = true;
    document.getElementById("newDiagramUseAiCodeBtn").disabled = true;
    sendBtn.innerHTML =
      '<span class="spinner-border spinner-border-sm me-1" aria-hidden="true"></span>Asking…';
    try {
      const data = await api("/v1/diagram-ai/generate", {
        method: "POST",
        body: {
          diagram_type: type,
          messages: newDiagramAi.messages,
          current_source:
            document.getElementById("diagramImportCode").value || "",
        },
      });
      const code = String(data?.code || "").trim();
      if (!code)
        throw new Error("The AI provider returned empty diagram code.");
      newDiagramAi.lastCode = code;
      newDiagramAi.messages.push({ role: "assistant", content: code });
      document.getElementById("diagramImportCode").value = code;
      renderNewDiagramAiChat();
      toast(
        "AI code inserted into the import field. Create the diagram to persist it.",
        "success",
      );
    } catch (err) {
      toast(err.message || String(err), "error");
    } finally {
      const status = await loadNewDiagramAiStatus();
      sendBtn.disabled = !(currentNewDiagramAiType() && status?.enabled);
      sendBtn.innerHTML = oldSendText;
      document.getElementById("newDiagramUseAiCodeBtn").disabled =
        !newDiagramAi.lastCode;
    }
  }

  applyInitialFiltersFromUrl();

  document.getElementById("searchForm").addEventListener("submit", (ev) => {
    ev.preventDefault();
    const selectedFolder = document.getElementById("folderFilter").value;
    state.currentFolderId = selectedFolder ? Number(selectedFolder) : null;
    state.offset = 0;
    renderFolderBrowser();
    syncFolderUrl(true);
    loadDiagrams().catch((err) => toast(err.message, "error"));
  });
  document.getElementById("prevPage").addEventListener("click", () => {
    state.offset = Math.max(0, state.offset - state.limit);
    loadDiagrams();
  });
  document.getElementById("nextPage").addEventListener("click", () => {
    state.offset += state.limit;
    loadDiagrams();
  });
  document.getElementById("newDiagramBtn").addEventListener("click", () => {
    document.getElementById("diagramForm").reset();
    newDiagramAi.type = null;
    newDiagramAi.messages = [];
    newDiagramAi.lastCode = "";
    document.getElementById("newDiagramAiBody")?.classList.remove("show");
    document.getElementById("newDiagramAiPrompt").value = "";
    renderNewDiagramAiChat();
    const folderSelect = document.getElementById("diagramFolder");
    if (folderSelect && state.currentFolderId)
      folderSelect.value = String(state.currentFolderId);
    renderDiagramTagChoices();
    modal.show();
  });
  window.addEventListener("popstate", () => {
    const params = new URLSearchParams(window.location.search || "");
    const folderParam = params.get("folder_id");
    state.currentFolderId =
      folderParam && /^\d+$/.test(folderParam) ? Number(folderParam) : null;
    const select = document.getElementById("folderFilter");
    if (select)
      select.value = state.currentFolderId ? String(state.currentFolderId) : "";
    state.offset = 0;
    renderFolderBrowser();
    loadDiagrams().catch((err) => toast(err.message, "error"));
  });
  bindDiagramTagInput();
  bindSearchFiltersToggle();
  document
    .getElementById("newDiagramAskAiBtn")
    ?.addEventListener("click", () =>
      refreshNewDiagramAiPanel().catch((err) => toast(err.message, "error")),
    );
  document
    .getElementById("diagramType")
    ?.addEventListener("change", () =>
      refreshNewDiagramAiPanel().catch((err) => toast(err.message, "error")),
    );
  document
    .getElementById("newDiagramSendAiPromptBtn")
    ?.addEventListener("click", () => sendNewDiagramAiPrompt());
  document
    .getElementById("newDiagramClearAiChatBtn")
    ?.addEventListener("click", () => {
      resetNewDiagramAiChat();
      document.getElementById("newDiagramAiPrompt")?.focus();
    });
  document
    .getElementById("newDiagramUseAiCodeBtn")
    ?.addEventListener("click", () => {
      if (!newDiagramAi.lastCode) return;
      document.getElementById("diagramImportCode").value =
        newDiagramAi.lastCode;
      toast("Latest AI code inserted into the import field.", "success");
    });
  document
    .getElementById("newDiagramAiPrompt")
    ?.addEventListener("keydown", (ev) => {
      if ((ev.ctrlKey || ev.metaKey) && ev.key === "Enter") {
        ev.preventDefault();
        sendNewDiagramAiPrompt();
      }
    });
  document
    .getElementById("diagramForm")
    .addEventListener("submit", async (ev) => {
      ev.preventDefault();
      try {
        const diagramType = document.getElementById("diagramType").value;
        const importCode = document
          .getElementById("diagramImportCode")
          .value.trim();
        const body = {
          name: document.getElementById("diagramName").value,
          diagram_type: diagramType,
          folder_id: document.getElementById("diagramFolder").value
            ? Number(document.getElementById("diagramFolder").value)
            : null,
          description: document.getElementById("diagramDescription").value,
          tags: document
            .getElementById("diagramTags")
            .value.split(",")
            .map((x) => x.trim())
            .filter(Boolean),
          visibility:
            document.getElementById("diagramVisibility").value || "private",
        };
        if (importCode) {
          if (diagramType === "sequence") body.sequence_text = importCode;
          else if (diagramType === "flowchart")
            body.flowchart_text = importCode;
          else body.bpmn_xml = importCode;
        }
        const diagram = await api("/v1/diagrams", { method: "POST", body });
        modal.hide();
        window.location.href = `/diagram.html?id=${encodeURIComponent(diagram.uuid)}`;
      } catch (err) {
        toast(err.message, "error");
      }
    });

  try {
    await Promise.all([loadFolders(), loadTagCatalog()]);
    renderSelectedTags();
    await Promise.all([loadTagCloud(), loadDiagrams()]);
  } catch (err) {
    toast(err.message, "error");
  }
})();
