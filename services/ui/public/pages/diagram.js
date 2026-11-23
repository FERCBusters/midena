(async () => {
  const {
    api,
    requireAuth,
    toast,
    escapeHtml,
    formatDate,
    downloadText,
    safeHref,
  } = window.MIDENA;
  const me = await requireAuth();
  const id = new URLSearchParams(window.location.search).get("id");
  if (!id) {
    window.location.href = "/index.html";
    return;
  }

  let diagram = null;
  let diagramType = "bpmn";
  let modeler = null;
  let selectedElement = null;
  let selectedElementId = null;
  let folders = [];
  let links = [];
  let comments = [];
  let metadataLinks = [];
  let shares = [];
  let canManageShares = false;
  let tagCatalog = [];
  let tagMap = new Map();
  let lastSequenceSvg = "";
  let lastFlowchartSvg = "";
  let linkOverlayIds = [];
  let commentOverlayIds = [];
  let markedLinkedElements = new Set();
  let markedCommentedElements = new Set();
  let renderedDiagramTargets = new Map();
  let editorCollapsed = false;
  let aiStatus = null;
  let activeAiType = null;
  const aiChatByType = {
    sequence: { messages: [], lastCode: "" },
    flowchart: { messages: [], lastCode: "" },
  };
  const prefs = me.preferences || {};
  const sidebarCollapsedByDefault =
    prefs.diagram_sidebar_collapsed_by_default !== false;
  const sourceCollapsedDefault =
    prefs.diagram_source_collapsed_by_default !== false;
  const sourcePanelCollapsed = {
    sequence: sourceCollapsedDefault,
    flowchart: sourceCollapsedDefault,
  };
  let contextPadPositionFrame = null;
  let flowchartVisualVisible = false;
  let flowchartVisualSyncing = false;
  let flowchartVisualConnectMode = false;
  let flowchartVisualConnectFrom = null;
  let flowchartVisualConnectDrag = null;
  let flowchartVisualSuppressNextClick = false;
  let flowchartVisualDrag = null;
  let flowchartVisualMarquee = null;
  let flowchartVisualState = null;

  const FLOWCHART_VISUAL_SHAPES = new Set([
    "process",
    "decision",
    "terminator",
    "database",
    "circle",
  ]);
  const FLOWCHART_VISUAL_GRID = 24;
  const FLOWCHART_VISUAL_MARGIN = FLOWCHART_VISUAL_GRID * 2;
  const FLOWCHART_VISUAL_NODE_WIDTH = 170;
  const FLOWCHART_VISUAL_NODE_HEIGHT = 74;

  const DEFAULT_DIAGRAM_THEME = {
    bpmn: {
      fill_color: "#ffffff",
      stroke_color: "#344054",
      text_color: "#1f2937",
      connector_color: "#667085",
      border_width: 1.5,
      connector_width: 1.8,
      font_family: "Arial, sans-serif",
      font_size: 14,
    },
    flowchart: {
      fill_color: "#ffffff",
      stroke_color: "#2563eb",
      text_color: "#111827",
      connector_color: "#64748b",
      border_width: 1.5,
      connector_width: 1.8,
      font_family: "Arial, sans-serif",
      font_size: 14,
    },
    sequence: {
      fill_color: "#ffffff",
      stroke_color: "#2563eb",
      text_color: "#111827",
      connector_color: "#475467",
      border_width: 1.5,
      connector_width: 1.8,
      font_family: "Arial, sans-serif",
      font_size: 14,
    },
  };
  let diagramTheme = JSON.parse(JSON.stringify(DEFAULT_DIAGRAM_THEME));

  const $ = (selector) => document.querySelector(selector);

  const assetPromises = new Map();

  function loadScriptOnce(src) {
    if (assetPromises.has(src)) return assetPromises.get(src);
    const existing = document.querySelector(`script[src="${src}"]`);
    if (existing) {
      const promise =
        existing.dataset.loaded === "1"
          ? Promise.resolve()
          : new Promise((resolve, reject) => {
              existing.addEventListener("load", resolve, { once: true });
              existing.addEventListener(
                "error",
                () => reject(new Error(`Failed to load ${src}`)),
                { once: true },
              );
            });
      assetPromises.set(src, promise);
      return promise;
    }
    const promise = new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = src;
      script.async = true;
      script.onload = () => {
        script.dataset.loaded = "1";
        resolve();
      };
      script.onerror = () => reject(new Error(`Failed to load ${src}`));
      document.head.appendChild(script);
    });
    assetPromises.set(src, promise);
    return promise;
  }

  async function ensureBpmnModeler() {
    if (!window.BpmnJS)
      await loadScriptOnce("/vendor/bpmn-js/bpmn-modeler.production.min.js");
    if (!window.BpmnJS) throw new Error("BPMN editor library is unavailable");
  }

  async function ensureMermaid() {
    if (!window.mermaid) await loadScriptOnce("/vendor/mermaid/mermaid.min.js");
    if (!window.mermaid)
      throw new Error("Mermaid rendering library is unavailable");
  }

  async function ensureHtml2Canvas() {
    if (!window.html2canvas)
      await loadScriptOnce("/vendor/html2canvas/html2canvas.min.js");
    if (!window.html2canvas)
      throw new Error("Rendered export library is unavailable");
  }

  async function ensureJsPdf() {
    if (!window.jspdf) await loadScriptOnce("/vendor/jspdf/jspdf.umd.min.js");
    if (!window.jspdf?.jsPDF)
      throw new Error("PDF export library is unavailable");
  }

  function isSequence() {
    return diagramType === "sequence";
  }
  function isFlowchart() {
    return diagramType === "flowchart";
  }

  function filename(ext) {
    const base =
      (diagram?.name || "diagram")
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, "-")
        .replace(/^-|-$/g, "") || "diagram";
    return `${base}.${ext}`;
  }

  const DEFAULT_SEQUENCE_SOURCE =
    "title MIDENA web sequence diagram\nparticipant User\nparticipant MIDENA\nUser->MIDENA: Open diagram";
  const DEFAULT_FLOWCHART_SOURCE =
    'flowchart LR\n    A[\"Start\"]\n    B[\"Process\"]\n    C[\"End\"]\n    A-->B\n    B-->C';

  function sourceExtension() {
    if (isSequence()) return "wsd";
    if (isFlowchart()) return "mmd";
    return "bpmn";
  }

  function tagKey(value) {
    return String(value || "")
      .trim()
      .toLowerCase();
  }

  function tagColour(name) {
    return tagMap.get(tagKey(name))?.color || "#f8f9fa";
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

  function placeSvg(host, markup) {
    // Parsed as XML and filtered, never assigned as HTML.
    const node = window.MIDENA_RENDERED.svgNodeFromMarkup(markup);
    host.replaceChildren(...(node ? [node] : []));
    return node;
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

  function normaliseDiagramTheme(value) {
    const incoming = value && typeof value === "object" ? value : {};
    const out = JSON.parse(JSON.stringify(DEFAULT_DIAGRAM_THEME));
    ["bpmn", "flowchart", "sequence"].forEach((type) => {
      const row =
        incoming[type] && typeof incoming[type] === "object"
          ? incoming[type]
          : {};
      ["fill_color", "stroke_color", "text_color", "connector_color"].forEach(
        (field) => {
          if (/^#[0-9a-fA-F]{6}$/.test(String(row[field] || "")))
            out[type][field] = String(row[field]).toLowerCase();
        },
      );
      ["border_width", "connector_width"].forEach((field) => {
        const n = Number(row[field]);
        if (Number.isFinite(n))
          out[type][field] = Math.min(8, Math.max(0.5, n));
      });
      const fs = Number(row.font_size);
      if (Number.isFinite(fs))
        out[type].font_size = Math.min(28, Math.max(8, fs));
      const family = String(row.font_family || "").trim();
      if (/^[A-Za-z0-9 ,.'"_-]{1,120}$/.test(family))
        out[type].font_family = family;
    });
    return out;
  }

  function themeFor(type = diagramType) {
    return (
      diagramTheme[type] || diagramTheme.bpmn || DEFAULT_DIAGRAM_THEME.bpmn
    );
  }

  function applyDiagramThemeCss(type = diagramType) {
    const t = themeFor(type);
    const root = document.documentElement;
    root.style.setProperty("--midena-diagram-fill", t.fill_color);
    root.style.setProperty("--midena-diagram-stroke", t.stroke_color);
    root.style.setProperty("--midena-diagram-text", t.text_color);
    root.style.setProperty("--midena-diagram-connector", t.connector_color);
    root.style.setProperty(
      "--midena-diagram-border-width",
      `${t.border_width}px`,
    );
    root.style.setProperty(
      "--midena-diagram-connector-width",
      `${t.connector_width}px`,
    );
    root.style.setProperty("--midena-diagram-font-family", t.font_family);
    root.style.setProperty("--midena-diagram-font-size", `${t.font_size}px`);
    document.body.classList.toggle("diagram-theme-bpmn", type === "bpmn");
  }

  function setSvgAttrs(node, attrs) {
    if (!node) return;
    Object.entries(attrs).forEach(([key, value]) => {
      node.setAttribute(key, String(value));
      try {
        node.style[key.replace(/-([a-z])/g, (_, ch) => ch.toUpperCase())] =
          String(value);
      } catch (_) {
        /* ignore */
      }
    });
  }

  function applyDiagramThemeToRenderedSvg(svg, type = diagramType) {
    if (!svg) return;
    const t = themeFor(type);
    svg.setAttribute("font-family", t.font_family);
    svg.querySelectorAll("text, tspan").forEach((node) =>
      setSvgAttrs(node, {
        fill: t.text_color,
        "font-family": t.font_family,
        "font-size": t.font_size,
      }),
    );
    const boxSelector =
      type === "bpmn"
        ? ".djs-shape .djs-visual > rect, .djs-shape .djs-visual > circle, .djs-shape .djs-visual > ellipse, .djs-shape .djs-visual > polygon"
        : type === "flowchart"
          ? ".node rect, .node polygon, .node circle, .node ellipse, .node path, rect.label-container, polygon.label-container"
          : 'rect.actor, rect[class*="actor"], rect[class*="labelBox"], rect[class*="note"], rect[data-midena-label-badge="1"], .actor > rect';
    svg.querySelectorAll(boxSelector).forEach((node) => {
      if (node.getAttribute("data-midena-svg-bg") === "1") return;
      setSvgAttrs(node, {
        fill: t.fill_color,
        stroke: t.stroke_color,
        "stroke-width": t.border_width,
      });
    });
    if (type === "bpmn") {
      svg.querySelectorAll(".djs-shape .djs-visual > path").forEach((node) =>
        setSvgAttrs(node, {
          stroke: t.stroke_color,
          "stroke-width": t.border_width,
        }),
      );
    }
    const connectorSelector =
      type === "flowchart"
        ? '.edgePath path, path.flowchart-link, path[class*="flowchart-link"], .edge-thickness-normal, .edge-thickness-thick, .edge-thickness-invisible'
        : type === "sequence"
          ? 'line[class*="messageLine"], path[class*="messageLine"], polyline[class*="messageLine"], line[class*="loopLine"], path[class*="loopLine"], polyline[class*="loopLine"]'
          : ".djs-connection .djs-visual > path, .djs-connection .djs-visual > polyline, .djs-connection .djs-visual > line";
    svg.querySelectorAll(connectorSelector).forEach((node) =>
      setSvgAttrs(node, {
        stroke: t.connector_color,
        "stroke-width": t.connector_width,
        fill:
          node.nodeName.toLowerCase() === "path" && type === "bpmn"
            ? "none"
            : node.getAttribute("fill") || "none",
      }),
    );
    svg.querySelectorAll("marker path, marker polygon").forEach((node) =>
      setSvgAttrs(node, {
        fill: t.connector_color,
        stroke: t.connector_color,
      }),
    );
  }

  function applyDiagramThemeToSvgMarkup(svgMarkup, type = diagramType) {
    const parsed = new DOMParser().parseFromString(
      String(svgMarkup || ""),
      "image/svg+xml",
    );
    const svg = parsed.documentElement;
    if (!svg || svg.nodeName.toLowerCase() !== "svg")
      return String(svgMarkup || "");
    applyDiagramThemeToRenderedSvg(svg, type);
    return serialiseSvg(svg);
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
    renderTagChoices();
  }

  function replaceCurrentTag(input, tag) {
    const parts = input.value.split(",");
    parts[parts.length - 1] = ` ${tag}`;
    setTagsOnInput(input, parts);
    input.focus();
    renderTagChoices();
  }

  function currentTagQuery(input) {
    return String(input.value.split(",").pop() || "")
      .trim()
      .toLowerCase();
  }

  function renderTagSuggestions() {
    const menu = $("#tagSuggestionsMenu");
    const input = $("#tagsInput");
    if (!menu || !input) return;
    const query = currentTagQuery(input);
    const selected = new Set(tagsFromInput(input).map(tagKey));
    const matches = query
      ? tagCatalog
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
          `<button class="tag-choice" type="button" data-suggest-tag="${escapeHtml(tag.name)}" style="--tag-color:${escapeHtml(tag.color || "#6f42c1")}">${escapeHtml(tag.name)}</button>`,
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

  function renderTagChoices() {
    const host = $("#tagChoices");
    const input = $("#tagsInput");
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
        renderTagChoices();
      }),
    );
    renderTagSuggestions();
  }

  function bindTagInput() {
    const input = $("#tagsInput");
    if (!input || input.dataset.tagEditorBound) return;
    input.dataset.tagEditorBound = "1";
    input.addEventListener("input", renderTagChoices);
    input.addEventListener("focus", renderTagChoices);
    input.addEventListener("blur", () =>
      window.setTimeout(
        () => $("#tagSuggestionsMenu")?.classList.add("d-none"),
        180,
      ),
    );
  }

  async function loadTagCatalog() {
    const data = await api("/api/v1/tags");
    tagCatalog = data.items || [];
    tagMap = new Map(tagCatalog.map((tag) => [tagKey(tag.name), tag]));
    const datalist = $("#tagSuggestions");
    if (datalist)
      datalist.innerHTML = tagCatalog
        .map((tag) => `<option value="${escapeHtml(tag.name)}"></option>`)
        .join("");
    renderTagChoices();
  }

  function orderedFolders() {
    const byParent = new Map();
    const byId = new Map();
    folders.forEach((folder) => {
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
    folders.forEach((folder) => {
      const id = Number(folder.id);
      if (!visited.has(id))
        visit(folder, byId.has(Number(folder.parent_id)) ? 1 : 0, []);
    });
    return output;
  }

  function renderFolderSelect() {
    const sel = $("#folderInput");
    if (!sel) return;
    sel.innerHTML =
      '<option value="">No folder</option>' +
      orderedFolders()
        .map((folder) => {
          const indent =
            folder.depth > 0 ? `${"&nbsp;&nbsp;".repeat(folder.depth)}↳ ` : "";
          return `<option value="${folder.id}" title="${escapeHtml(folder.path)}">${indent}${escapeHtml(folder.name)}</option>`;
        })
        .join("");
    sel.value = diagram?.folder_id ? String(diagram.folder_id) : "";
  }

  async function loadFolders() {
    const data = await api("/api/v1/folders");
    folders = data.items || [];
    renderFolderSelect();
  }

  function resetBpmnState() {
    selectedElement = null;
    selectedElementId = null;
    linkOverlayIds = [];
    commentOverlayIds = [];
    markedLinkedElements = new Set();
    markedCommentedElements = new Set();
    renderedDiagramTargets = new Map();
  }

  function destroyModeler() {
    if (!modeler) return;
    try {
      modeler.destroy();
    } catch (_) {
      /* best effort */
    }
    modeler = null;
    resetBpmnState();
  }

  function setEditorMode(type) {
    diagramType =
      type === "sequence"
        ? "sequence"
        : type === "flowchart"
          ? "flowchart"
          : "bpmn";
    $("#bpmnToolbar")?.classList.toggle(
      "d-none",
      isSequence() || isFlowchart(),
    );
    $("#canvas")?.classList.toggle("d-none", isSequence() || isFlowchart());
    $("#sequencePane")?.classList.toggle("d-none", !isSequence());
    $("#flowchartPane")?.classList.toggle("d-none", !isFlowchart());
    if (!isFlowchart() && flowchartVisualVisible)
      setFlowchartVisualVisible(false);
    $("#entityLinkCard")?.classList.remove("d-none");
    $("#entityLinkCardTitle").textContent = isFlowchart()
      ? "Selected flowchart item links"
      : isSequence()
        ? "Selected sequence item links"
        : "Selected BPMN element links";
    $("#commentHelp").textContent = isFlowchart()
      ? "Click a flowchart box in the preview to attach comments to that item."
      : isSequence()
        ? "Click a participant or message label in the preview to attach comments to that item."
        : "Comments can be attached to the selected BPMN element.";
    $(".diagram-card")?.classList.toggle("sequence-diagram-card", isSequence());
    $(".diagram-card")?.classList.toggle(
      "flowchart-diagram-card",
      isFlowchart(),
    );
    if (!isSequence() && !isFlowchart())
      $("#selectionInfo").textContent = "Select an element to link it.";
    document.querySelector('[data-export="bpmn"]').textContent = isSequence()
      ? "Sequence source"
      : isFlowchart()
        ? "Flowchart source"
        : "BPMN XML";
    applyDiagramThemeCss(diagramType);
    setSourcePanelCollapsed("sequence", sourcePanelCollapsed.sequence);
    setSourcePanelCollapsed("flowchart", sourcePanelCollapsed.flowchart);
    refreshEditorPreviewLayout();
  }

  function resizeCanvas() {
    if (!modeler) return;
    const canvas = modeler.get("canvas");
    if (canvas?.resized) canvas.resized();
    canvas.zoom("fit-viewport");
  }

  function optionalModelerService(name) {
    try {
      return modeler ? modeler.get(name) : null;
    } catch (_) {
      return null;
    }
  }

  function setActiveToolbarButton(toolName) {
    document
      .querySelectorAll("[data-tool]")
      .forEach((btn) => btn.classList.remove("active"));
    if (!toolName) return;
    document
      .querySelector(`[data-tool="${toolName}"]`)
      ?.classList.add("active");
  }

  function resetModelerInteraction() {
    if (!modeler) return;
    const dragging = optionalModelerService("dragging");
    try {
      dragging?.cancel?.();
    } catch (_) {
      /* ignore */
    }
    ["globalConnect", "handTool", "lassoTool", "spaceTool"].forEach(
      (serviceName) => {
        const tool = optionalModelerService(serviceName);
        if (!tool) return;
        try {
          tool.deactivate?.();
          tool.cancel?.();
        } catch (_) {
          /* ignore */
        }
      },
    );
    setActiveToolbarButton(null);
  }

  function runModelerTool(toolName, ev) {
    if (!modeler) return;
    if (toolName === "undo" || toolName === "redo") {
      resetModelerInteraction();
      try {
        modeler.get("commandStack")?.[toolName]?.();
      } catch (err) {
        toast(err.message || String(err), "error");
      }
      return;
    }
    const canvas = modeler.get("canvas");
    if (toolName === "zoom-in") {
      resetModelerInteraction();
      canvas.zoom((canvas.zoom() || 1) + 0.15);
      return;
    }
    if (toolName === "zoom-out") {
      resetModelerInteraction();
      canvas.zoom(Math.max(0.2, (canvas.zoom() || 1) - 0.15));
      return;
    }
    if (toolName === "fit") {
      resetModelerInteraction();
      canvas.zoom("fit-viewport");
      return;
    }
    if (toolName === "select") {
      resetModelerInteraction();
      return;
    }
    resetModelerInteraction();
    try {
      const originalEvent = ev?.originalEvent || ev;
      if (toolName === "hand")
        modeler.get("handTool")?.activateHand?.(originalEvent);
      else if (toolName === "lasso")
        modeler.get("lassoTool")?.activateSelection?.(originalEvent);
      else if (toolName === "space")
        modeler.get("spaceTool")?.activateSelection?.(originalEvent);
      else if (toolName === "connect")
        modeler.get("globalConnect")?.start?.(originalEvent);
      setActiveToolbarButton(toolName);
    } catch (err) {
      setActiveToolbarButton(null);
      toast(`Could not activate tool: ${err.message || err}`, "error");
    }
  }

  function withCanvasElement(elementRegistry, elementId, callback) {
    const element = elementRegistry.get(elementId);
    if (!element || element.labelTarget) return null;
    return callback(element);
  }

  function clearLinkDecorations() {
    if (!modeler) return;
    const overlays = modeler.get("overlays");
    const canvas = modeler.get("canvas");
    const elementRegistry = modeler.get("elementRegistry");
    linkOverlayIds.forEach((overlayId) => overlays.remove(overlayId));
    linkOverlayIds = [];
    markedLinkedElements.forEach((elementId) =>
      withCanvasElement(elementRegistry, elementId, (element) =>
        canvas.removeMarker(element, "midena-linked-element"),
      ),
    );
    markedLinkedElements = new Set();
  }

  function clearCommentDecorations() {
    if (!modeler) return;
    const overlays = modeler.get("overlays");
    const canvas = modeler.get("canvas");
    const elementRegistry = modeler.get("elementRegistry");
    commentOverlayIds.forEach((overlayId) => overlays.remove(overlayId));
    commentOverlayIds = [];
    markedCommentedElements.forEach((elementId) =>
      withCanvasElement(elementRegistry, elementId, (element) =>
        canvas.removeMarker(element, "midena-commented-element"),
      ),
    );
    markedCommentedElements = new Set();
  }

  function applyEntityLinkDecorations() {
    if (isSequence() || isFlowchart()) {
      applyRenderedDiagramDecorations();
      return;
    }
    if (!modeler) return;
    clearLinkDecorations();
    const overlays = modeler.get("overlays");
    const canvas = modeler.get("canvas");
    const elementRegistry = modeler.get("elementRegistry");
    const byElement = new Map();
    links.forEach((link) => {
      if (!link.element_id) return;
      if (!byElement.has(link.element_id)) byElement.set(link.element_id, []);
      byElement.get(link.element_id).push(link);
    });
    byElement.forEach((elementLinks, elementId) => {
      const element = elementRegistry.get(elementId);
      if (!element || element.labelTarget) return;
      const primary = elementLinks.find((l) => l.url) || elementLinks[0];
      const label = primary.label || primary.entity_ref || "Open link";
      canvas.addMarker(element, "midena-linked-element");
      markedLinkedElements.add(elementId);
      const html = document.createElement(primary.url ? "a" : "span");
      html.className = "midena-entity-link-overlay";
      html.textContent =
        elementLinks.length > 1
          ? `${label} +${elementLinks.length - 1}`
          : label;
      html.title = primary.url ? `Open ${label}` : label;
      if (primary.url) {
        html.href = safeHref(primary.url) || "#";
        html.target = "_blank";
        html.rel = "noopener noreferrer";
        html.addEventListener("click", (event) => event.stopPropagation());
      }
      linkOverlayIds.push(
        overlays.add(elementId, { position: { bottom: -26, left: 0 }, html }),
      );
    });
  }

  function highlightComment(commentId) {
    const card = document.getElementById(`comment-${commentId}`);
    if (!card) return;
    card.scrollIntoView({ behavior: "smooth", block: "center" });
    card.classList.remove("midena-comment-card-flash");
    void card.offsetWidth;
    card.classList.add("midena-comment-card-flash");
    window.setTimeout(
      () => card.classList.remove("midena-comment-card-flash"),
      1700,
    );
  }

  function buildCommentBubble(elementComments) {
    const bubble = document.createElement("span");
    bubble.className = "midena-comment-bubble";
    elementComments.slice(0, 4).forEach((comment) => {
      const item = document.createElement("span");
      item.className = "midena-comment-bubble-item";
      const author = document.createElement("strong");
      author.textContent = comment.username || "user";
      const body = document.createElement("span");
      body.textContent = comment.body || "";
      item.appendChild(author);
      item.appendChild(body);
      bubble.appendChild(item);
    });
    if (elementComments.length > 4) {
      const more = document.createElement("span");
      more.className = "midena-comment-bubble-more";
      more.textContent = `+${elementComments.length - 4} more comments`;
      bubble.appendChild(more);
    }
    return bubble;
  }

  function applyCommentDecorations() {
    if (isSequence() || isFlowchart()) {
      applyRenderedDiagramDecorations();
      return;
    }
    if (!modeler) return;
    clearCommentDecorations();
    const overlays = modeler.get("overlays");
    const canvas = modeler.get("canvas");
    const elementRegistry = modeler.get("elementRegistry");
    const byElement = new Map();
    comments
      .filter((c) => c.element_id && !c.is_resolved)
      .forEach((comment) => {
        if (!byElement.has(comment.element_id))
          byElement.set(comment.element_id, []);
        byElement.get(comment.element_id).push(comment);
      });
    byElement.forEach((elementComments, elementId) => {
      const element = elementRegistry.get(elementId);
      if (!element || element.labelTarget) return;
      const first = elementComments[0];
      canvas.addMarker(element, "midena-commented-element");
      markedCommentedElements.add(elementId);
      const html = document.createElement("button");
      html.type = "button";
      html.className = "midena-comment-overlay";
      const label = document.createElement("span");
      label.className = "midena-comment-overlay-label";
      label.textContent =
        elementComments.length > 1
          ? `${elementComments.length} comments`
          : "1 comment";
      html.appendChild(label);
      html.appendChild(buildCommentBubble(elementComments));
      html.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        selectedElementId = elementId;
        renderSelection();
        highlightComment(first.id);
      });
      commentOverlayIds.push(
        overlays.add(elementId, { position: { top: -18, right: -12 }, html }),
      );
    });
  }

  function activeRenderedPreview() {
    if (isSequence()) return $("#sequencePreview");
    if (isFlowchart()) return $("#flowchartPreview");
    return null;
  }

  function activeRenderedSvg() {
    return activeRenderedPreview()?.querySelector("svg") || null;
  }

  function renderedElementLabel(elementId) {
    return renderedDiagramTargets.get(elementId)?.label || elementId;
  }

  function applyRenderedDiagramDecorations() {
    if (!isSequence() && !isFlowchart()) return;
    const svg = activeRenderedSvg();
    if (!svg || !window.MIDENA_RENDERED?.applySvgInteractions) return;
    renderedDiagramTargets = window.MIDENA_RENDERED.applySvgInteractions({
      svg,
      diagramType,
      links,
      comments,
      selectedElementId,
      selectable: !editorCollapsed,
      openTargetLinks: editorCollapsed,
      onSelect: (elementId) => {
        selectedElement = null;
        selectedElementId = elementId;
        renderSelection();
        applyRenderedDiagramDecorations();
      },
      onCommentClick: (comment) => {
        selectedElement = null;
        selectedElementId = comment.element_id || null;
        renderSelection();
        applyRenderedDiagramDecorations();
        if (comment?.id) highlightComment(comment.id);
      },
    });
  }

  function applyAllDecorations() {
    if (isSequence() || isFlowchart()) {
      applyRenderedDiagramDecorations();
      return;
    }
    applyEntityLinkDecorations();
    applyCommentDecorations();
  }

  function renderSelection() {
    const info = $("#selectionInfo");
    const list = $("#entityLinks");
    const itemLabel = isFlowchart()
      ? "flowchart item"
      : isSequence()
        ? "sequence item"
        : "BPMN element";
    if (!selectedElementId) {
      info.textContent = `Select a ${itemLabel} to link it or attach comments.`;
      list.innerHTML = "";
      return;
    }
    const displayLabel =
      isSequence() || isFlowchart()
        ? renderedElementLabel(selectedElementId)
        : selectedElementId;
    info.textContent = `Selected ${itemLabel}: ${displayLabel}`;
    const items = links.filter((l) => l.element_id === selectedElementId);
    list.innerHTML = items.length
      ? items
          .map(
            (l) =>
              `<div class="d-flex justify-content-between align-items-start gap-2 border rounded p-2 mb-2"><div><div class="fw-semibold">${escapeHtml(l.label || l.entity_ref || "Link")}</div>${safeHref(l.url) ? `<a class="small" href="${safeHref(l.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(l.url)}</a>` : `<span class="small">${escapeHtml(l.url || "")}</span>`}</div><button class="btn btn-sm btn-outline-danger" type="button" data-delete-link="${l.id}"><i class="bi bi-trash"></i></button></div>`,
          )
          .join("")
      : '<div class="text-secondary small">No links for this element.</div>';
    document.querySelectorAll("[data-delete-link]").forEach((btn) =>
      btn.addEventListener("click", async () => {
        try {
          await api(`/api/v1/entity-links/${btn.dataset.deleteLink}`, {
            method: "DELETE",
          });
          await loadLinks();
        } catch (err) {
          toast(err.message, "error");
        }
      }),
    );
  }

  function renderComments() {
    $("#commentCount").textContent = String(comments.length);
    $("#comments").innerHTML =
      comments
        .map(
          (c) =>
            `<div class="comment-card border rounded p-2 mb-2 ${c.is_resolved ? "opacity-75" : ""}" id="comment-${c.id}"><div class="d-flex justify-content-between gap-2"><strong>${escapeHtml(c.username || "user")}</strong><small class="text-secondary">${escapeHtml(formatDate(c.created_at))}</small></div><div>${escapeHtml(c.body)}</div><div class="small text-secondary">${c.element_id ? `Element ${escapeHtml(isSequence() || isFlowchart() ? renderedElementLabel(c.element_id) : c.element_id)}` : "Diagram-level comment"}${c.is_resolved ? " · resolved" : ""}</div><div class="d-flex gap-1 mt-2"><button class="btn btn-sm btn-outline-secondary" type="button" data-resolve-comment="${c.id}" data-resolved="${c.is_resolved ? "0" : "1"}">${c.is_resolved ? "Reopen" : "Resolve"}</button><button class="btn btn-sm btn-outline-danger" type="button" data-delete-comment="${c.id}">Delete</button></div></div>`,
        )
        .join("") || '<div class="text-secondary small">No comments yet.</div>';
    document.querySelectorAll("[data-resolve-comment]").forEach((btn) =>
      btn.addEventListener("click", async () => {
        try {
          await api(`/api/v1/comments/${btn.dataset.resolveComment}`, {
            method: "PATCH",
            body: { is_resolved: btn.dataset.resolved === "1" },
          });
          await loadComments();
        } catch (err) {
          toast(err.message, "error");
        }
      }),
    );
    document.querySelectorAll("[data-delete-comment]").forEach((btn) =>
      btn.addEventListener("click", async () => {
        try {
          await api(`/api/v1/comments/${btn.dataset.deleteComment}`, {
            method: "DELETE",
          });
          await loadComments();
        } catch (err) {
          toast(err.message, "error");
        }
      }),
    );
    applyCommentDecorations();
  }

  function renderMetadataLinks() {
    $("#metadataLinkCount").textContent = String(metadataLinks.length);
    $("#metadataLinks").innerHTML = metadataLinks.length
      ? metadataLinks
          .map(
            (link) =>
              `<div class="border rounded p-2 mb-2"><div class="d-flex justify-content-between gap-2"><div>${safeHref(link.url) ? `<a class="fw-semibold" href="${safeHref(link.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(link.label)}</a>` : `<span class="fw-semibold">${escapeHtml(link.label)}</span>`}<div class="small text-secondary text-break">${escapeHtml(link.url)}</div>${link.notes ? `<div class="small mt-1">${escapeHtml(link.notes)}</div>` : ""}</div><button class="btn btn-sm btn-outline-danger align-self-start" type="button" data-delete-meta-link="${link.id}"><i class="bi bi-trash"></i></button></div></div>`,
          )
          .join("")
      : '<div class="text-secondary small">No metadata links yet.</div>';
    document.querySelectorAll("[data-delete-meta-link]").forEach((btn) =>
      btn.addEventListener("click", async () => {
        try {
          await api(`/api/v1/metadata-links/${btn.dataset.deleteMetaLink}`, {
            method: "DELETE",
          });
          await loadMetadataLinks();
        } catch (err) {
          toast(err.message, "error");
        }
      }),
    );
  }

  function renderShares() {
    $("#shareCount").textContent = String(shares.length);
    const ownerNote =
      String(diagram?.created_by_user_id ?? "") === String(me.id)
        ? "You own this diagram."
        : "";
    $("#shareHelp").textContent = canManageShares
      ? `${ownerNote} Add collaborators for private diagrams, or notify users about public diagrams.`.trim()
      : "Only the diagram author or an administrator can manage sharing permissions.";
    $("#shareForm")?.classList.toggle("d-none", !canManageShares);
    $("#shares").innerHTML = shares.length
      ? shares
          .map(
            (share) =>
              `<div class="d-flex justify-content-between align-items-start gap-2 border rounded p-2 mb-2"><div><div class="fw-semibold">${escapeHtml(share.username || share.email || `User ${share.user_id}`)} <span class="badge text-bg-light border">${escapeHtml(share.role)}</span></div>${share.email ? `<div class="small text-secondary">${escapeHtml(share.email)}</div>` : ""}</div>${canManageShares ? `<button class="btn btn-sm btn-outline-danger" type="button" data-delete-share="${share.id}"><i class="bi bi-trash"></i></button>` : ""}</div>`,
          )
          .join("")
      : '<div class="text-secondary small">No collaborators added.</div>';
    document.querySelectorAll("[data-delete-share]").forEach((btn) =>
      btn.addEventListener("click", async () => {
        try {
          await api(`/api/v1/diagram-shares/${btn.dataset.deleteShare}`, {
            method: "DELETE",
          });
          await loadShares();
        } catch (err) {
          toast(err.message, "error");
        }
      }),
    );
  }

  function renderVersions(items) {
    const list = $("#versions");
    list.innerHTML =
      (items || [])
        .map(
          (v) =>
            `<button type="button" class="list-group-item list-group-item-action" data-version="${v.id}"><div class="d-flex justify-content-between"><strong>v${v.version_number}</strong><span class="badge text-bg-light border">${escapeHtml(v.diagram_type || "bpmn")}</span></div><div class="small text-secondary">${escapeHtml(formatDate(v.created_at))}</div><div class="small">${escapeHtml(v.change_summary || "")}</div></button>`,
        )
        .join("") ||
      '<div class="list-group-item text-secondary">No versions.</div>';
    document.querySelectorAll("[data-version]").forEach((btn) =>
      btn.addEventListener("click", async () => {
        try {
          const version = await api(
            `/api/v1/diagram-versions/${btn.dataset.version}`,
          );
          const source = version.source_text || version.bpmn_xml || "";
          if ((version.diagram_type || "bpmn") === "sequence") {
            destroyModeler();
            setEditorMode("sequence");
            $("#sequenceSource").value = source;
            autoSizeSequenceSource();
            await renderSequence();
          } else if ((version.diagram_type || "bpmn") === "flowchart") {
            destroyModeler();
            setEditorMode("flowchart");
            $("#flowchartSource").value = source;
            autoSizeFlowchartSource();
            flowchartVisualState = null;
            if (flowchartVisualVisible) loadFlowchartVisualFromSource();
            await renderFlowchart();
          } else {
            setEditorMode("bpmn");
            await ensureModeler(source);
          }
          toast(
            `Loaded version ${version.version_number} into the editor. Save it to make it current.`,
            "info",
          );
        } catch (err) {
          toast(err.message, "error");
        }
      }),
    );
  }

  function visibilityLabel(visibility) {
    if (visibility === "public") return "Public";
    if (visibility === "internal") return "Private internal";
    return "Private to me only";
  }

  function visibilityHelp(visibility, embedUrl) {
    if (visibility === "public" && embedUrl)
      return `Public and embeddable: <code>${escapeHtml(embedUrl)}</code>`;
    if (visibility === "internal")
      return "Visible to authenticated MIDENA users in listings and search; not publicly embeddable.";
    return "Private to you and explicitly shared collaborators only; not publicly embeddable.";
  }

  function canDeleteDiagram() {
    if (diagram?.can_delete !== undefined) return Boolean(diagram.can_delete);
    return (
      me?.effective_role === "admin" ||
      String(diagram?.created_by_user_id ?? "") === String(me?.id ?? "-")
    );
  }

  function refreshEditorCollapseButton() {
    const button = $("#toggleEditorBtn");
    if (!button) return;
    button.innerHTML = editorCollapsed
      ? '<i class="bi bi-pencil-square me-1"></i>Expand editor'
      : '<i class="bi bi-eye me-1"></i>Collapse editor';
    button.setAttribute("aria-pressed", editorCollapsed ? "true" : "false");
    button.setAttribute(
      "title",
      editorCollapsed
        ? "Show editing controls again"
        : "Hide editing controls and focus on the diagram preview",
    );
  }

  function refreshEditorPreviewLayout() {
    window.setTimeout(() => {
      if (isSequence()) fitSequencePreviewToSvg();
      else if (isFlowchart()) fitFlowchartPreviewToSvg();
      else resizeCanvas();
    }, 60);
  }

  function setEditorCollapsed(collapsed) {
    editorCollapsed = Boolean(collapsed);
    const workspace = $("#diagramWorkspace");
    workspace?.classList.toggle("editor-collapsed", editorCollapsed);
    if (editorCollapsed) {
      resetModelerInteraction();
      setSidebarExpanded(false);
    }
    refreshEditorCollapseButton();
    applyAllDecorations();
    refreshEditorPreviewLayout();
  }

  function setSidebarExpanded(expanded) {
    const workspace = $("#diagramWorkspace");
    const editor = $("#editorCol");
    const sidebar = $("#diagramSidebar");
    const button = $("#toggleSidebarBtn");
    workspace?.classList.toggle("sidebar-collapsed", !expanded);
    workspace?.classList.toggle("sidebar-expanded", expanded);
    editor?.classList.toggle("col-xl-12", !expanded);
    editor?.classList.toggle("col-xl-9", expanded);
    sidebar?.classList.toggle("d-none", !expanded);
    if (button) {
      button.innerHTML = expanded
        ? '<i class="bi bi-layout-sidebar-inset-reverse me-1"></i>Collapse sidebar'
        : '<i class="bi bi-layout-sidebar-inset-reverse me-1"></i>Expand sidebar';
      button.setAttribute("aria-expanded", expanded ? "true" : "false");
    }
    refreshEditorPreviewLayout();
  }

  function setSourcePanelCollapsed(type, collapsed) {
    const isFlow = type === "flowchart";
    const body = isFlow ? $("#flowchartSourceBody") : $("#sequenceSourceBody");
    const button = isFlow
      ? $("#toggleFlowchartSourceBtn")
      : $("#toggleSequenceSourceBtn");
    const panel = isFlow
      ? $("#flowchartPane .sequence-source-panel")
      : $("#sequencePane .sequence-source-panel");
    sourcePanelCollapsed[type] = Boolean(collapsed);
    body?.classList.toggle("d-none", sourcePanelCollapsed[type]);
    panel?.classList.toggle(
      "source-panel-collapsed",
      sourcePanelCollapsed[type],
    );
    if (button) {
      button.innerHTML = sourcePanelCollapsed[type]
        ? '<i class="bi bi-chevron-down me-1"></i>Expand source'
        : '<i class="bi bi-chevron-up me-1"></i>Collapse source';
      button.setAttribute(
        "aria-expanded",
        sourcePanelCollapsed[type] ? "false" : "true",
      );
    }
    refreshEditorPreviewLayout();
  }

  function setupSidebarSectionToggles() {
    document
      .querySelectorAll("#diagramSidebar [data-sidebar-section]")
      .forEach((card) => {
        const header = card.querySelector(".card-header");
        if (!header || header.querySelector("[data-sidebar-section-toggle]"))
          return;
        header.classList.add(
          "d-flex",
          "justify-content-between",
          "align-items-center",
        );
        let titleWrap = header.querySelector(":scope > span");
        if (!titleWrap) {
          titleWrap = document.createElement("span");
          titleWrap.textContent = header.textContent.trim();
          header.textContent = "";
          header.appendChild(titleWrap);
        }
        const button = document.createElement("button");
        button.type = "button";
        button.className =
          "btn btn-sm btn-outline-secondary sidebar-section-toggle";
        button.dataset.sidebarSectionToggle = "1";
        const setExpanded = (expanded) => {
          card
            .querySelectorAll(
              ":scope > .card-body, :scope > .card-footer, :scope > .list-group",
            )
            .forEach((el) => el.classList.toggle("d-none", !expanded));
          button.innerHTML = expanded
            ? '<i class="bi bi-chevron-up me-1"></i>Collapse'
            : '<i class="bi bi-chevron-down me-1"></i>Expand';
          button.setAttribute("aria-expanded", expanded ? "true" : "false");
        };
        button.addEventListener("click", () =>
          setExpanded(button.getAttribute("aria-expanded") !== "true"),
        );
        header.appendChild(button);
        setExpanded(true);
      });
  }

  function renderDetails() {
    if (!diagram) return;
    diagramType =
      diagram.diagram_type === "sequence"
        ? "sequence"
        : diagram.diagram_type === "flowchart"
          ? "flowchart"
          : "bpmn";
    $("#diagramTitle").textContent = diagram.name || "Diagram";
    $("#diagramMeta").textContent =
      `${diagramType === "sequence" ? "Web sequence diagram" : diagramType === "flowchart" ? "Flowchart" : "BPMN diagram"} · Version ${diagram.current_version_number || 1} · ${visibilityLabel(diagram.visibility)}${diagram.locked ? ` · Locked by ${diagram.locked_by || "someone"}` : ""}`;
    const tagDisplay = $("#diagramTagsDisplay");
    if (tagDisplay) {
      const tags = diagram.tags || [];
      tagDisplay.innerHTML = tags.length
        ? tags.map((tag) => tagLinkBadge(tag)).join("")
        : "";
      tagDisplay.classList.toggle("d-none", !tags.length);
    }
    $("#diagramHeader").textContent = diagram.header_text || "";
    $("#diagramFooter").textContent = diagram.footer_text || "";
    diagramTheme = normaliseDiagramTheme(diagram.diagram_theme);
    applyDiagramThemeCss(diagramType);
    $("#nameInput").value = diagram.name || "";
    $("#descriptionInput").value = diagram.description || "";
    $("#tagsInput").value = (diagram.tags || []).join(", ");
    renderTagChoices();
    $("#visibilityInput").value = diagram.visibility || "private";
    $("#embedBtn").disabled = diagram.visibility !== "public";
    const embedUrl = publicEmbedUrl();
    $("#embedInfo").innerHTML = visibilityHelp(diagram.visibility, embedUrl);
    $("#deleteDiagramBtn")?.classList.toggle("d-none", !canDeleteDiagram());
    renderFolderSelect();
  }

  function rectsIntersect(a, b, padding = 0) {
    if (!a || !b) return false;
    return !(
      a.right + padding <= b.left ||
      a.left >= b.right + padding ||
      a.bottom + padding <= b.top ||
      a.top >= b.bottom + padding
    );
  }

  function rectOverlapArea(a, b) {
    if (!a || !b) return 0;
    const width = Math.max(
      0,
      Math.min(a.right, b.right) - Math.max(a.left, b.left),
    );
    const height = Math.max(
      0,
      Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top),
    );
    return width * height;
  }

  function bpmnShapeScreenRects() {
    if (!modeler) return [];
    const registry = modeler.get("elementRegistry");
    const canvas = modeler.get("canvas");
    if (!registry || !canvas) return [];
    const root = canvas.getRootElement?.();
    return registry
      .getAll()
      .filter((element) => {
        if (!element || element === root || element.waypoints) return false;
        if (!Number.isFinite(element.x) || !Number.isFinite(element.y))
          return false;
        if (!Number.isFinite(element.width) || !Number.isFinite(element.height))
          return false;
        return element.width > 0 && element.height > 0;
      })
      .map((element) => {
        try {
          const graphics = canvas.getGraphics(element);
          const rect = graphics?.getBoundingClientRect?.();
          if (!rect || rect.width <= 0 || rect.height <= 0) return null;
          return {
            element,
            left: rect.left,
            right: rect.right,
            top: rect.top,
            bottom: rect.bottom,
            width: rect.width,
            height: rect.height,
          };
        } catch (_) {
          return null;
        }
      })
      .filter(Boolean);
  }

  function candidateContextPadPositions(selectedRect, padRect, canvasRect) {
    const gap = 18;
    const canvasInset = 8;
    const positions = [
      { left: selectedRect.right + gap, top: selectedRect.top - 6 },
      {
        left: selectedRect.right + gap,
        top: selectedRect.top + (selectedRect.height - padRect.height) / 2,
      },
      {
        left: selectedRect.right + gap,
        top: selectedRect.bottom - padRect.height + 6,
      },
      {
        left: selectedRect.left + (selectedRect.width - padRect.width) / 2,
        top: selectedRect.bottom + gap,
      },
      {
        left: selectedRect.right - padRect.width,
        top: selectedRect.bottom + gap,
      },
      { left: selectedRect.left, top: selectedRect.bottom + gap },
      {
        left: selectedRect.left + (selectedRect.width - padRect.width) / 2,
        top: selectedRect.top - padRect.height - gap,
      },
      {
        left: selectedRect.right - padRect.width,
        top: selectedRect.top - padRect.height - gap,
      },
      { left: selectedRect.left, top: selectedRect.top - padRect.height - gap },
      {
        left: selectedRect.left - padRect.width - gap,
        top: selectedRect.top - 6,
      },
      {
        left: selectedRect.left - padRect.width - gap,
        top: selectedRect.top + (selectedRect.height - padRect.height) / 2,
      },
      {
        left: selectedRect.left - padRect.width - gap,
        top: selectedRect.bottom - padRect.height + 6,
      },
      {
        left: canvasRect.right - padRect.width - canvasInset,
        top: selectedRect.top - 6,
      },
      { left: canvasRect.left + canvasInset, top: selectedRect.top - 6 },
    ];
    return positions.map((pos) => {
      const clampedLeft = Math.min(
        Math.max(pos.left, canvasRect.left + canvasInset),
        canvasRect.right - padRect.width - canvasInset,
      );
      const clampedTop = Math.min(
        Math.max(pos.top, canvasRect.top + canvasInset),
        canvasRect.bottom - padRect.height - canvasInset,
      );
      return {
        left: clampedLeft,
        top: clampedTop,
        right: clampedLeft + padRect.width,
        bottom: clampedTop + padRect.height,
      };
    });
  }

  function positionBpmnContextPadAvoidingShapes() {
    contextPadPositionFrame = null;
    if (!modeler || !selectedElement || isSequence() || isFlowchart()) return;
    const canvasNode = $("#canvas");
    const pad = canvasNode?.querySelector(".djs-context-pad");
    if (!canvasNode || !pad || pad.classList.contains("djs-context-pad-hidden"))
      return;
    const canvas = modeler.get("canvas");
    const selectedGraphics = canvas?.getGraphics?.(selectedElement);
    const selectedRect = selectedGraphics?.getBoundingClientRect?.();
    if (!selectedRect || selectedRect.width <= 0 || selectedRect.height <= 0)
      return;

    pad.style.setProperty("transform", "translate(0px, 0px)", "important");
    const basePadRect = pad.getBoundingClientRect();
    const canvasRect = canvasNode.getBoundingClientRect();
    if (basePadRect.width <= 0 || basePadRect.height <= 0) return;

    const obstacles = bpmnShapeScreenRects();
    const candidates = candidateContextPadPositions(
      selectedRect,
      basePadRect,
      canvasRect,
    );
    const ranked = candidates
      .map((candidate, index) => {
        const overlapArea = obstacles.reduce(
          (total, obstacle) => total + rectOverlapArea(candidate, obstacle),
          0,
        );
        const intersects = obstacles.some((obstacle) =>
          rectsIntersect(candidate, obstacle, 4),
        );
        const outsideCanvas =
          Math.max(0, canvasRect.left - candidate.left) +
          Math.max(0, candidate.right - canvasRect.right) +
          Math.max(0, canvasRect.top - candidate.top) +
          Math.max(0, candidate.bottom - canvasRect.bottom);
        const travel =
          Math.abs(candidate.left - basePadRect.left) +
          Math.abs(candidate.top - basePadRect.top);
        return {
          candidate,
          index,
          intersects,
          score:
            (intersects ? 1000000 : 0) +
            overlapArea +
            outsideCanvas * 10000 +
            travel,
        };
      })
      .sort((a, b) => a.score - b.score || a.index - b.index);

    const best = ranked[0]?.candidate;
    if (!best) return;
    const dx = Math.round(best.left - basePadRect.left);
    const dy = Math.round(best.top - basePadRect.top);
    pad.style.setProperty(
      "transform",
      `translate(${dx}px, ${dy}px)`,
      "important",
    );
  }

  function scheduleBpmnContextPadReposition() {
    if (contextPadPositionFrame) cancelAnimationFrame(contextPadPositionFrame);
    contextPadPositionFrame = requestAnimationFrame(() => {
      contextPadPositionFrame = requestAnimationFrame(
        positionBpmnContextPadAvoidingShapes,
      );
    });
  }

  function publicEmbedUrl() {
    if (diagram?.visibility !== "public" || !diagram?.embed_url) return "";
    return diagram.embed_url.startsWith("http")
      ? diagram.embed_url
      : `${location.origin}${diagram.embed_url}`;
  }

  function publicViewUrl() {
    if (diagram?.visibility !== "public" || !diagram?.public_view_url)
      return "";
    return diagram.public_view_url.startsWith("http")
      ? diagram.public_view_url
      : `${location.origin}${diagram.public_view_url}`;
  }

  async function ensureModeler(xml) {
    if (isSequence() || isFlowchart()) return;
    await ensureBpmnModeler();
    if (!modeler) {
      modeler = new BpmnJS({ container: "#canvas" });
      const eventBus = modeler.get("eventBus");
      eventBus.on("selection.changed", (event) => {
        selectedElement = event.newSelection?.[0] || null;
        selectedElementId = selectedElement?.id || null;
        renderSelection();
        scheduleBpmnContextPadReposition();
      });
      eventBus.on("element.changed", (event) => {
        if (selectedElement && event.element?.id === selectedElement.id)
          scheduleBpmnContextPadReposition();
      });
      eventBus.on("contextPad.open", scheduleBpmnContextPadReposition);
      eventBus.on("canvas.viewbox.changed", scheduleBpmnContextPadReposition);
    }
    if (xml) await modeler.importXML(xml);
    resizeCanvas();
    applyAllDecorations();
  }

  function autoSizeSequenceSource() {
    const textarea = $("#sequenceSource");
    if (!textarea) return;
    textarea.style.height = "auto";
    textarea.style.height = `${Math.max(160, textarea.scrollHeight + 8)}px`;
  }

  function autoSizeFlowchartSource() {
    const textarea = $("#flowchartSource");
    if (!textarea) return;
    textarea.style.height = "auto";
    textarea.style.height = `${Math.max(160, textarea.scrollHeight + 8)}px`;
  }

  function escapeMermaidMessage(message) {
    return String(message || "")
      .replace(/\\n\\/g, "<br/>")
      .replace(/\\n/g, "<br/>")
      .replace(/\\\\/g, "\\");
  }

  function convertWebSequenceLine(line) {
    const raw = String(line || "");
    if (!raw.trim()) return raw;
    if (
      /^\s*(sequenceDiagram|title|participant|actor|autonumber|note\s+(?:left|right|over)|loop|alt|else|opt|par|and|critical|break|rect|end)\b/i.test(
        raw,
      )
    ) {
      return raw.replace(/\\n\\/g, "<br/>").replace(/\\n/g, "<br/>");
    }
    if (
      raw.includes("->>") ||
      raw.includes("-->>") ||
      raw.includes("-x") ||
      raw.includes("--x") ||
      raw.includes("-)") ||
      raw.includes("--)")
    ) {
      return raw.replace(/\\n\\/g, "<br/>").replace(/\\n/g, "<br/>");
    }
    const match = raw.match(/^(\s*)(.+?)\s*(--?>|<--?)\s*(.+?)\s*:\s*(.*)$/);
    if (!match) return raw.replace(/\\n\\/g, "<br/>").replace(/\\n/g, "<br/>");
    const [, indent, leftRaw, arrow, rightRaw, messageRaw] = match;
    const left = leftRaw.trim();
    const right = rightRaw.trim();
    const dashed = arrow.includes("--");
    const mermaidArrow = dashed ? "-->>" : "->>";
    const message = escapeMermaidMessage(messageRaw);
    if (arrow.startsWith("<")) {
      return `${indent}${right}${mermaidArrow}${left}: ${message}`;
    }
    return `${indent}${left}${mermaidArrow}${right}: ${message}`;
  }

  function normaliseSequenceSourceForMermaid(source) {
    const text = String(source || "").trim();
    if (!text)
      return normaliseSequenceSourceForMermaid(DEFAULT_SEQUENCE_SOURCE);
    const hasDirective = /^sequenceDiagram\b/m.test(text);
    const converted = text
      .split(/\r?\n/)
      .map(convertWebSequenceLine)
      .join("\n");
    return hasDirective ? converted : `sequenceDiagram\n${converted}`;
  }

  function normaliseFlowchartSourceForMermaid(source) {
    const text = String(source || "").trim();
    if (!text) return DEFAULT_FLOWCHART_SOURCE;
    const hasDirective = /^[ \t]*(?:flowchart|graph)\b/im.test(text);
    return hasDirective ? text : `flowchart LR\n${text}`;
  }

  function flowchartVisualEmptyState() {
    return {
      direction: "LR",
      nodes: [],
      edges: [],
      selectedKind: null,
      selectedId: null,
      selectedNodes: [],
      selectedEdges: [],
      nextNodeNumber: 1,
      nextEdgeNumber: 1,
    };
  }

  function normaliseFlowchartDirection(value) {
    const upper = String(value || "")
      .trim()
      .toUpperCase();
    if (upper === "TB") return "TD";
    return ["LR", "RL", "TD", "BT"].includes(upper) ? upper : "LR";
  }

  function cleanFlowchartLabel(value) {
    return String(value || "")
      .replace(/<br\s*\/?>/gi, "\n")
      .replace(/^\s*["'`]|["'`]\s*$/g, "")
      .trim();
  }

  function escapeFlowchartLabel(value) {
    return String(value || "")
      .replace(/\\/g, "\\\\")
      .replace(/"/g, '\\"')
      .replace(/\r?\n/g, "<br/>");
  }

  function safeFlowchartId(value, fallback = "Node") {
    let out = String(value || "")
      .trim()
      .replace(/[^A-Za-z0-9_]/g, "_")
      .replace(/_+/g, "_")
      .replace(/^_+|_+$/g, "");
    if (!out) out = fallback;
    if (!/^[A-Za-z]/.test(out)) out = `N_${out}`;
    return out.slice(0, 48) || fallback;
  }

  function uniqueFlowchartId(base, nodes, existingId = "") {
    const existing = new Set(
      (nodes || []).map((node) => node.id).filter((id) => id !== existingId),
    );
    const cleanBase = safeFlowchartId(base || "N", "N");
    if (!existing.has(cleanBase)) return cleanBase;
    let idx = 2;
    while (existing.has(`${cleanBase}_${idx}`)) idx += 1;
    return `${cleanBase}_${idx}`;
  }

  function flowchartElementIdForNode(nodeId) {
    return `flowchart:${nodeId}`;
  }

  function flowchartVisualNodeById(id) {
    return flowchartVisualState?.nodes?.find((node) => node.id === id) || null;
  }

  function flowchartVisualEdgeById(id) {
    return flowchartVisualState?.edges?.find((edge) => edge.id === id) || null;
  }

  function flowchartVisualNormaliseSelection(state = flowchartVisualState) {
    if (!state) return { nodes: [], edges: [], total: 0 };
    if (!Array.isArray(state.selectedNodes)) state.selectedNodes = [];
    if (!Array.isArray(state.selectedEdges)) state.selectedEdges = [];
    state.selectedNodes = [...new Set(state.selectedNodes)].filter((id) =>
      state.nodes?.some((node) => node.id === id),
    );
    state.selectedEdges = [...new Set(state.selectedEdges)].filter((id) =>
      state.edges?.some((edge) => edge.id === id),
    );
    if (
      state.selectedKind === "node" &&
      state.selectedId &&
      !state.selectedNodes.includes(state.selectedId)
    )
      state.selectedNodes.push(state.selectedId);
    if (
      state.selectedKind === "edge" &&
      state.selectedId &&
      !state.selectedEdges.includes(state.selectedId)
    )
      state.selectedEdges.push(state.selectedId);
    const total = state.selectedNodes.length + state.selectedEdges.length;
    if (!total) {
      state.selectedKind = null;
      state.selectedId = null;
    } else if (total === 1) {
      if (state.selectedNodes.length) {
        state.selectedKind = "node";
        state.selectedId = state.selectedNodes[0];
      } else {
        state.selectedKind = "edge";
        state.selectedId = state.selectedEdges[0];
      }
    } else if (state.selectedKind && state.selectedId) {
      const stillSelected =
        state.selectedKind === "node"
          ? state.selectedNodes.includes(state.selectedId)
          : state.selectedEdges.includes(state.selectedId);
      if (!stillSelected) {
        state.selectedKind = state.selectedNodes.length ? "node" : "edge";
        state.selectedId =
          state.selectedNodes[0] || state.selectedEdges[0] || null;
      }
    } else {
      state.selectedKind = state.selectedNodes.length ? "node" : "edge";
      state.selectedId =
        state.selectedNodes[0] || state.selectedEdges[0] || null;
    }
    return { nodes: state.selectedNodes, edges: state.selectedEdges, total };
  }

  function flowchartVisualSetSelection(
    { nodes = [], edges = [] } = {},
    {
      primaryKind = null,
      primaryId = null,
      updateElementSelection = true,
    } = {},
  ) {
    const state = flowchartVisualEnsureState();
    state.selectedNodes = [...new Set(nodes)].filter((id) =>
      state.nodes.some((node) => node.id === id),
    );
    state.selectedEdges = [...new Set(edges)].filter((id) =>
      state.edges.some((edge) => edge.id === id),
    );
    if (primaryKind && primaryId) {
      state.selectedKind = primaryKind;
      state.selectedId = primaryId;
      if (primaryKind === "node" && !state.selectedNodes.includes(primaryId))
        state.selectedNodes.unshift(primaryId);
      if (primaryKind === "edge" && !state.selectedEdges.includes(primaryId))
        state.selectedEdges.unshift(primaryId);
    } else {
      state.selectedKind = null;
      state.selectedId = null;
    }
    const selection = flowchartVisualNormaliseSelection(state);
    if (updateElementSelection) {
      selectedElement = null;
      selectedElementId = null;
      if (selection.total === 1 && state.selectedKind === "node") {
        const node = flowchartVisualNodeById(state.selectedId);
        selectedElementId = node ? flowchartElementIdForNode(node.id) : null;
        if (node && selectedElementId)
          renderedDiagramTargets.set(selectedElementId, {
            label: node.label || node.id,
            kind: "flowchart node",
          });
      }
    }
    renderSelection();
    return selection;
  }

  function flowchartVisualIsSelected(kind, id) {
    const state = flowchartVisualState;
    if (!state || !id) return false;
    const selection = flowchartVisualNormaliseSelection(state);
    return kind === "node"
      ? selection.nodes.includes(id)
      : selection.edges.includes(id);
  }

  function parseFlowchartNodeToken(token) {
    const raw = String(token || "")
      .trim()
      .replace(/;$/, "")
      .trim();
    const idMatch = raw.match(/^([A-Za-z][A-Za-z0-9_]*)\s*(.*)$/);
    if (!idMatch) return null;
    const id = idMatch[1];
    const rest = idMatch[2].trim();
    if (!rest) return { id, label: id, shape: "process", hasDefinition: false };
    const patterns = [
      { shape: "database", re: /^\[\((.*)\)\]$/s },
      { shape: "terminator", re: /^\(\[(.*)\]\)$/s },
      { shape: "circle", re: /^\(\((.*)\)\)$/s },
      { shape: "decision", re: /^\{(.*)\}$/s },
      { shape: "process", re: /^\[(.*)\]$/s },
      { shape: "process", re: /^\((.*)\)$/s },
    ];
    for (const pattern of patterns) {
      const match = rest.match(pattern.re);
      if (match)
        return {
          id,
          label: cleanFlowchartLabel(match[1]),
          shape: pattern.shape,
          hasDefinition: true,
        };
    }
    return {
      id,
      label: cleanFlowchartLabel(rest),
      shape: "process",
      hasDefinition: true,
    };
  }

  function addParsedFlowchartNode(model, parsed) {
    if (!parsed?.id) return null;
    let node = model.nodes.find((item) => item.id === parsed.id);
    if (!node) {
      node = {
        id: parsed.id,
        label: parsed.label || parsed.id,
        shape: FLOWCHART_VISUAL_SHAPES.has(parsed.shape)
          ? parsed.shape
          : "process",
        x: 0,
        y: 0,
        width: FLOWCHART_VISUAL_NODE_WIDTH,
        height: FLOWCHART_VISUAL_NODE_HEIGHT,
      };
      model.nodes.push(node);
    } else if (parsed.hasDefinition) {
      node.label = parsed.label || node.label || node.id;
      node.shape = FLOWCHART_VISUAL_SHAPES.has(parsed.shape)
        ? parsed.shape
        : node.shape;
    }
    return node;
  }

  function parseFlowchartEdgeLine(line) {
    const raw = String(line || "")
      .trim()
      .replace(/;$/, "")
      .trim();
    let match = raw.match(/^(.*?)\s*-\.\s*(.*?)\s*\.->\s*(.*?)$/s);
    if (match)
      return {
        fromToken: match[1],
        arrow: "-.->",
        label: cleanFlowchartLabel(match[2]),
        toToken: match[3],
      };
    match = raw.match(/^(.*?)\s*(-\.->|-->|---)\|([^|]*)\|\s*(.*?)$/s);
    if (match)
      return {
        fromToken: match[1],
        arrow: match[2],
        label: cleanFlowchartLabel(match[3]),
        toToken: match[4],
      };
    match = raw.match(/^(.*?)\s*(-\.->|-->|---)\s*(.*?)$/s);
    if (match)
      return {
        fromToken: match[1],
        arrow: match[2],
        label: "",
        toToken: match[3],
      };
    return null;
  }

  function parseFlowchartVisualSource(source) {
    const model = flowchartVisualEmptyState();
    const text = normaliseFlowchartSourceForMermaid(source);
    const lines = text
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter((line) => line && !line.startsWith("%%"));
    const directive = lines[0]?.match(
      /^(?:flowchart|graph)\s+(TD|TB|BT|LR|RL)\b/i,
    );
    if (directive) {
      model.direction = normaliseFlowchartDirection(directive[1]);
      lines.shift();
    }
    lines.forEach((line) => {
      if (
        /^(?:subgraph|end|classDef|class|click|style|linkStyle)\b/i.test(line)
      )
        return;
      const edge = parseFlowchartEdgeLine(line);
      if (edge) {
        const fromParsed = parseFlowchartNodeToken(edge.fromToken);
        const toParsed = parseFlowchartNodeToken(edge.toToken);
        if (!fromParsed || !toParsed) return;
        addParsedFlowchartNode(model, fromParsed);
        addParsedFlowchartNode(model, toParsed);
        const style =
          edge.arrow === "---"
            ? "line"
            : edge.arrow === "-.->"
              ? "dotted"
              : "arrow";
        model.edges.push({
          id: `E${model.nextEdgeNumber++}`,
          from: fromParsed.id,
          to: toParsed.id,
          label: edge.label || "",
          style,
        });
        return;
      }
      const node = parseFlowchartNodeToken(line);
      if (node?.hasDefinition) addParsedFlowchartNode(model, node);
    });
    if (!model.nodes.length) {
      addParsedFlowchartNode(model, {
        id: "A",
        label: "Start",
        shape: "terminator",
        hasDefinition: true,
      });
      addParsedFlowchartNode(model, {
        id: "B",
        label: "Process",
        shape: "process",
        hasDefinition: true,
      });
      addParsedFlowchartNode(model, {
        id: "C",
        label: "End",
        shape: "terminator",
        hasDefinition: true,
      });
      model.edges.push({
        id: `E${model.nextEdgeNumber++}`,
        from: "A",
        to: "B",
        label: "",
        style: "arrow",
      });
      model.edges.push({
        id: `E${model.nextEdgeNumber++}`,
        from: "B",
        to: "C",
        label: "",
        style: "arrow",
      });
    }
    model.nextNodeNumber = Math.max(
      1,
      ...model.nodes.map((node) => {
        const match = String(node.id).match(/(\d+)$/);
        return match ? Number(match[1]) + 1 : 1;
      }),
    );
    autoLayoutFlowchartVisual(model);
    return model;
  }

  function flowchartNodeMermaidDefinition(node) {
    const id = safeFlowchartId(node.id, "N");
    const label = escapeFlowchartLabel(node.label || id);
    switch (node.shape) {
      case "decision":
        return `${id}{"${label}"}`;
      case "terminator":
        return `${id}(["${label}"])`;
      case "database":
        return `${id}[("${label}")]`;
      case "circle":
        return `${id}(("${label}"))`;
      default:
        return `${id}["${label}"]`;
    }
  }

  function flowchartEdgeMermaidDefinition(edge) {
    const from = safeFlowchartId(edge.from, "A");
    const to = safeFlowchartId(edge.to, "B");
    const label = String(edge.label || "").trim();
    if (edge.style === "line")
      return `${from} ---${label ? `|${escapeFlowchartLabel(label)}|` : ""} ${to}`;
    if (edge.style === "dotted")
      return label
        ? `${from} -. ${escapeFlowchartLabel(label).replace(/\|/g, " ")} .-> ${to}`
        : `${from} -.-> ${to}`;
    return `${from} -->${label ? `|${escapeFlowchartLabel(label)}|` : ""} ${to}`;
  }

  function flowchartVisualToMermaid(model) {
    const state =
      model ||
      flowchartVisualState ||
      parseFlowchartVisualSource(DEFAULT_FLOWCHART_SOURCE);
    const lines = [`flowchart ${normaliseFlowchartDirection(state.direction)}`];
    (state.nodes || []).forEach((node) =>
      lines.push(`    ${flowchartNodeMermaidDefinition(node)}`),
    );
    if (state.nodes?.length && state.edges?.length) lines.push("");
    (state.edges || []).forEach((edge) =>
      lines.push(`    ${flowchartEdgeMermaidDefinition(edge)}`),
    );
    return lines.join("\n");
  }

  function autoLayoutFlowchartVisual(model = flowchartVisualState) {
    if (!model?.nodes?.length) return;
    const nodes = model.nodes;
    const incoming = new Map(nodes.map((node) => [node.id, 0]));
    const outgoing = new Map(nodes.map((node) => [node.id, []]));
    (model.edges || []).forEach((edge) => {
      if (!incoming.has(edge.to) || !outgoing.has(edge.from)) return;
      incoming.set(edge.to, incoming.get(edge.to) + 1);
      outgoing.get(edge.from).push(edge.to);
    });
    const level = new Map();
    const queue = nodes
      .filter((node) => (incoming.get(node.id) || 0) === 0)
      .map((node) => node.id);
    if (!queue.length) queue.push(nodes[0].id);
    queue.forEach((id) => level.set(id, 0));
    for (let idx = 0; idx < queue.length; idx += 1) {
      const id = queue[idx];
      const base = level.get(id) || 0;
      (outgoing.get(id) || []).forEach((to) => {
        const nextLevel = Math.max(level.get(to) || 0, base + 1);
        if (!level.has(to) || nextLevel > level.get(to)) {
          level.set(to, nextLevel);
          queue.push(to);
        }
      });
    }
    nodes.forEach((node, idx) => {
      if (!level.has(node.id)) level.set(node.id, idx);
    });
    const byLevel = new Map();
    nodes.forEach((node) => {
      const lv = level.get(node.id) || 0;
      if (!byLevel.has(lv)) byLevel.set(lv, []);
      byLevel.get(lv).push(node);
    });
    const levels = [...byLevel.keys()].sort((a, b) => a - b);
    const maxLevel = levels.length ? Math.max(...levels) : 0;
    const direction = normaliseFlowchartDirection(model.direction);
    const gapX = FLOWCHART_VISUAL_GRID * 11;
    const gapY = FLOWCHART_VISUAL_GRID * 6;
    const margin = FLOWCHART_VISUAL_MARGIN;
    levels.forEach((lv) => {
      byLevel.get(lv).forEach((node, row) => {
        if (direction === "TD" || direction === "BT") {
          node.x = margin + row * gapX;
          node.y = margin + (direction === "BT" ? maxLevel - lv : lv) * gapY;
        } else {
          node.x = margin + (direction === "RL" ? maxLevel - lv : lv) * gapX;
          node.y = margin + row * gapY;
        }
        node.width = FLOWCHART_VISUAL_NODE_WIDTH;
        node.height = FLOWCHART_VISUAL_NODE_HEIGHT;
        snapFlowchartVisualNode(node);
      });
    });
  }

  function flowchartVisualEnsureState({ force = false } = {}) {
    if (!flowchartVisualState || force)
      flowchartVisualState = parseFlowchartVisualSource(
        $("#flowchartSource")?.value || DEFAULT_FLOWCHART_SOURCE,
      );
    return flowchartVisualState;
  }

  function snapFlowchartVisualValue(value) {
    return (
      Math.round(Number(value || 0) / FLOWCHART_VISUAL_GRID) *
      FLOWCHART_VISUAL_GRID
    );
  }

  function snapFlowchartVisualCoordinate(value) {
    return Math.max(FLOWCHART_VISUAL_GRID, snapFlowchartVisualValue(value));
  }

  function snapFlowchartVisualNode(node) {
    if (!node) return;
    node.x = snapFlowchartVisualCoordinate(node.x);
    node.y = snapFlowchartVisualCoordinate(node.y);
  }

  function flowchartVisualPointFromEvent(ev) {
    const svg = $("#flowchartVisualCanvas");
    if (!svg) return { x: 0, y: 0 };
    const point = svg.createSVGPoint();
    point.x = ev.clientX;
    point.y = ev.clientY;
    const matrix = svg.getScreenCTM();
    if (!matrix) return { x: ev.offsetX || 0, y: ev.offsetY || 0 };
    const transformed = point.matrixTransform(matrix.inverse());
    return { x: transformed.x, y: transformed.y };
  }

  function flowchartVisualNodeAtPoint(point, { exceptId = null } = {}) {
    const state = flowchartVisualEnsureState();
    return (
      [...state.nodes].reverse().find((node) => {
        if (exceptId && node.id === exceptId) return false;
        return (
          point.x >= node.x &&
          point.x <= node.x + node.width &&
          point.y >= node.y &&
          point.y <= node.y + node.height
        );
      }) || null
    );
  }

  function flowchartVisualRectFromPoints(a, b) {
    const x1 = Math.min(a?.x || 0, b?.x || 0);
    const y1 = Math.min(a?.y || 0, b?.y || 0);
    const x2 = Math.max(a?.x || 0, b?.x || 0);
    const y2 = Math.max(a?.y || 0, b?.y || 0);
    return { x: x1, y: y1, width: x2 - x1, height: y2 - y1, x2, y2 };
  }

  function flowchartVisualBoundsIntersect(a, b) {
    if (!a || !b) return false;
    const ax2 = a.x2 ?? a.x + a.width;
    const ay2 = a.y2 ?? a.y + a.height;
    const bx2 = b.x2 ?? b.x + b.width;
    const by2 = b.y2 ?? b.y + b.height;
    return a.x <= bx2 && ax2 >= b.x && a.y <= by2 && ay2 >= b.y;
  }

  function flowchartVisualPointInRect(point, rect) {
    return Boolean(
      point &&
      rect &&
      point.x >= rect.x &&
      point.x <= rect.x2 &&
      point.y >= rect.y &&
      point.y <= rect.y2,
    );
  }

  function flowchartVisualEdgeBounds(edge, padding = 14) {
    const from = flowchartVisualNodeById(edge?.from);
    const to = flowchartVisualNodeById(edge?.to);
    if (!from || !to) return null;
    const endpoint = flowchartVisualEndpoint(from, to);
    const path = flowchartVisualEdgePath(from, to);
    const points = [endpoint.start, endpoint.end, path.mid].filter(Boolean);
    const xs = points.map((point) => point.x);
    const ys = points.map((point) => point.y);
    const x = Math.min(...xs) - padding;
    const y = Math.min(...ys) - padding;
    const x2 = Math.max(...xs) + padding;
    const y2 = Math.max(...ys) + padding;
    return { x, y, width: x2 - x, height: y2 - y, x2, y2, points };
  }

  function flowchartVisualItemsInRect(rect) {
    const state = flowchartVisualEnsureState();
    const nodes = state.nodes
      .filter((node) =>
        flowchartVisualBoundsIntersect(rect, {
          x: node.x,
          y: node.y,
          width: node.width,
          height: node.height,
        }),
      )
      .map((node) => node.id);
    const edges = state.edges
      .filter((edge) => {
        const bounds = flowchartVisualEdgeBounds(edge);
        if (!bounds) return false;
        return (
          flowchartVisualBoundsIntersect(rect, bounds) ||
          bounds.points.some((point) => flowchartVisualPointInRect(point, rect))
        );
      })
      .map((edge) => edge.id);
    return { nodes, edges };
  }

  function flowchartVisualHandlePosition(node) {
    const direction = normaliseFlowchartDirection(
      flowchartVisualEnsureState().direction,
    );
    if (direction === "TD") return { x: node.width / 2, y: node.height };
    if (direction === "BT") return { x: node.width / 2, y: 0 };
    if (direction === "RL") return { x: 0, y: node.height / 2 };
    return { x: node.width, y: node.height / 2 };
  }

  function flowchartVisualHandleAbsolutePosition(node) {
    const handle = flowchartVisualHandlePosition(node);
    return { x: node.x + handle.x, y: node.y + handle.y };
  }

  function flowchartVisualPreviewPath(fromNode, point) {
    const start = flowchartVisualHandleAbsolutePosition(fromNode);
    const dx = point.x - start.x;
    const dy = point.y - start.y;
    if (Math.abs(dx) >= Math.abs(dy)) {
      const c = Math.max(36, Math.abs(dx) * 0.45);
      return `M ${start.x} ${start.y} C ${start.x + Math.sign(dx || 1) * c} ${start.y}, ${point.x - Math.sign(dx || 1) * c} ${point.y}, ${point.x} ${point.y}`;
    }
    const c = Math.max(36, Math.abs(dy) * 0.45);
    return `M ${start.x} ${start.y} C ${start.x} ${start.y + Math.sign(dy || 1) * c}, ${point.x} ${point.y - Math.sign(dy || 1) * c}, ${point.x} ${point.y}`;
  }

  function stopFlowchartVisualConnectMode() {
    flowchartVisualConnectMode = false;
    flowchartVisualConnectFrom = null;
    $("#flowchartConnectBtn")?.classList.remove("active");
    $("#flowchartConnectBtn")?.setAttribute("aria-pressed", "false");
  }

  function addFlowchartVisualEdge(
    fromId,
    toId,
    { style = "arrow", label = "", select = true } = {},
  ) {
    const state = flowchartVisualEnsureState();
    if (!fromId || !toId || fromId === toId) return null;
    const edge = {
      id: `E${state.nextEdgeNumber++}`,
      from: fromId,
      to: toId,
      label,
      style,
    };
    state.edges.push(edge);
    if (select)
      flowchartVisualSetSelection(
        { nodes: [], edges: [edge.id] },
        { primaryKind: "edge", primaryId: edge.id },
      );
    syncFlowchartVisualToSource();
    return edge;
  }

  function flowchartVisualWrapText(text, maxChars = 18, maxLines = 4) {
    const lines = String(text || "")
      .split(/\r?\n/)
      .flatMap((line) => wrapSvgTextLine(line, maxChars));
    return (lines.length ? lines : [""]).slice(0, maxLines);
  }

  function flowchartVisualNodeCenter(node) {
    return { x: node.x + node.width / 2, y: node.y + node.height / 2 };
  }

  function flowchartVisualEndpoint(from, to) {
    const a = flowchartVisualNodeCenter(from);
    const b = flowchartVisualNodeCenter(to);
    const dx = b.x - a.x;
    const dy = b.y - a.y;
    if (Math.abs(dx) < 0.001 && Math.abs(dy) < 0.001)
      return { start: a, end: b };
    const startScale = Math.min(
      Math.abs(dx) ? from.width / 2 / Math.abs(dx) : Infinity,
      Math.abs(dy) ? from.height / 2 / Math.abs(dy) : Infinity,
    );
    const endScale = Math.min(
      Math.abs(dx) ? to.width / 2 / Math.abs(dx) : Infinity,
      Math.abs(dy) ? to.height / 2 / Math.abs(dy) : Infinity,
    );
    return {
      start: { x: a.x + dx * startScale, y: a.y + dy * startScale },
      end: { x: b.x - dx * endScale, y: b.y - dy * endScale },
    };
  }

  function flowchartVisualEdgePath(from, to) {
    const { start, end } = flowchartVisualEndpoint(from, to);
    const dx = end.x - start.x;
    const dy = end.y - start.y;
    if (Math.abs(dx) >= Math.abs(dy)) {
      const c = Math.max(36, Math.abs(dx) * 0.45);
      return {
        d: `M ${start.x} ${start.y} C ${start.x + Math.sign(dx || 1) * c} ${start.y}, ${end.x - Math.sign(dx || 1) * c} ${end.y}, ${end.x} ${end.y}`,
        mid: { x: (start.x + end.x) / 2, y: (start.y + end.y) / 2 - 8 },
      };
    }
    const c = Math.max(36, Math.abs(dy) * 0.45);
    return {
      d: `M ${start.x} ${start.y} C ${start.x} ${start.y + Math.sign(dy || 1) * c}, ${end.x} ${end.y - Math.sign(dy || 1) * c}, ${end.x} ${end.y}`,
      mid: { x: (start.x + end.x) / 2, y: (start.y + end.y) / 2 - 8 },
    };
  }

  function svgNode(name, attrs = {}) {
    const node = document.createElementNS("http://www.w3.org/2000/svg", name);
    Object.entries(attrs).forEach(([key, value]) => {
      if (value === undefined || value === null) return;
      node.setAttribute(key, String(value));
    });
    return node;
  }

  function renderFlowchartVisualNodeShape(group, node) {
    const w = node.width;
    const h = node.height;
    if (node.shape === "decision") {
      group.appendChild(
        svgNode("polygon", {
          class: "flowchart-visual-node-shape",
          points: `${w / 2},0 ${w},${h / 2} ${w / 2},${h} 0,${h / 2}`,
        }),
      );
      return;
    }
    if (node.shape === "circle") {
      group.appendChild(
        svgNode("ellipse", {
          class: "flowchart-visual-node-shape",
          cx: w / 2,
          cy: h / 2,
          rx: w / 2,
          ry: h / 2,
        }),
      );
      return;
    }
    if (node.shape === "database") {
      const path = `M 0 14 C 0 4, ${w} 4, ${w} 14 L ${w} ${h - 14} C ${w} ${h - 4}, 0 ${h - 4}, 0 ${h - 14} Z M 0 14 C 0 24, ${w} 24, ${w} 14`;
      group.appendChild(
        svgNode("path", { class: "flowchart-visual-node-shape", d: path }),
      );
      return;
    }
    group.appendChild(
      svgNode("rect", {
        class: "flowchart-visual-node-shape",
        x: 0,
        y: 0,
        width: w,
        height: h,
        rx: node.shape === "terminator" ? h / 2 : 10,
        ry: node.shape === "terminator" ? h / 2 : 10,
      }),
    );
  }

  function renderFlowchartVisualProperties() {
    const empty = $("#flowchartVisualPropertiesEmpty");
    const nodePanel = $("#flowchartNodeProperties");
    const edgePanel = $("#flowchartEdgeProperties");
    if (!empty || !nodePanel || !edgePanel) return;
    const state = flowchartVisualEnsureState();
    const selection = flowchartVisualNormaliseSelection(state);
    const singleNode =
      selection.total === 1 && selection.nodes.length === 1
        ? flowchartVisualNodeById(selection.nodes[0])
        : null;
    const singleEdge =
      selection.total === 1 && selection.edges.length === 1
        ? flowchartVisualEdgeById(selection.edges[0])
        : null;
    empty.classList.toggle("d-none", Boolean(singleNode || singleEdge));
    nodePanel.classList.toggle("d-none", !singleNode);
    edgePanel.classList.toggle("d-none", !singleEdge);
    if (selection.total > 1) {
      const parts = [];
      if (selection.nodes.length)
        parts.push(
          `${selection.nodes.length} node${selection.nodes.length === 1 ? "" : "s"}`,
        );
      if (selection.edges.length)
        parts.push(
          `${selection.edges.length} connector${selection.edges.length === 1 ? "" : "s"}`,
        );
      empty.textContent = `${parts.join(" and ")} selected. Drag one of the selected boxes to move the selected boxes together, or press Delete to remove the selection.`;
    } else {
      empty.textContent =
        "Select a node or connector to edit it. Drag on empty canvas to box-select several items.";
    }
    if (singleNode) {
      $("#flowchartNodeLabelInput").value = singleNode.label || "";
      $("#flowchartNodeShapeInput").value = FLOWCHART_VISUAL_SHAPES.has(
        singleNode.shape,
      )
        ? singleNode.shape
        : "process";
      $("#flowchartNodeIdInput").value = singleNode.id || "";
    }
    if (singleEdge) {
      $("#flowchartEdgeLabelInput").value = singleEdge.label || "";
      $("#flowchartEdgeStyleInput").value = singleEdge.style || "arrow";
    }
  }

  function selectFlowchartVisual(kind, id) {
    if (kind === "node" && id) {
      flowchartVisualSetSelection(
        { nodes: [id], edges: [] },
        { primaryKind: "node", primaryId: id },
      );
    } else if (kind === "edge" && id) {
      flowchartVisualSetSelection(
        { nodes: [], edges: [id] },
        { primaryKind: "edge", primaryId: id },
      );
    } else {
      flowchartVisualSetSelection({ nodes: [], edges: [] });
    }
    renderFlowchartVisualEditor();
  }

  function setFlowchartVisualStatus(message, level = "secondary") {
    const status = $("#flowchartVisualStatus");
    if (!status) return;
    status.className = `flowchart-visual-status small text-${level} mb-2`;
    status.textContent = message;
  }

  function syncFlowchartVisualToSource({ preview = true } = {}) {
    if (!flowchartVisualState || flowchartVisualSyncing) return;
    const textarea = $("#flowchartSource");
    if (!textarea) return;
    flowchartVisualSyncing = true;
    textarea.value = flowchartVisualToMermaid(flowchartVisualState);
    autoSizeFlowchartSource();
    clearValidation("flowchart");
    flowchartVisualSyncing = false;
    if (preview) scheduleFlowchartPreview();
  }

  function renderFlowchartVisualEditor() {
    if (!flowchartVisualVisible) return;
    const svg = $("#flowchartVisualCanvas");
    const wrap = $("#flowchartVisualCanvasWrap");
    const direction = $("#flowchartDirectionInput");
    if (!svg || !wrap) return;
    const state = flowchartVisualEnsureState();
    if (direction)
      direction.value = normaliseFlowchartDirection(state.direction);
    const connectPoint = flowchartVisualConnectDrag?.current || null;
    const maxX = Math.max(
      900,
      connectPoint ? connectPoint.x + FLOWCHART_VISUAL_MARGIN : 0,
      ...state.nodes.map(
        (node) => node.x + node.width + FLOWCHART_VISUAL_MARGIN,
      ),
    );
    const maxY = Math.max(
      520,
      connectPoint ? connectPoint.y + FLOWCHART_VISUAL_MARGIN : 0,
      ...state.nodes.map(
        (node) => node.y + node.height + FLOWCHART_VISUAL_MARGIN,
      ),
    );
    svg.setAttribute("viewBox", `0 0 ${maxX} ${maxY}`);
    svg.setAttribute("height", String(maxY));
    svg.innerHTML = "";
    const defs = svgNode("defs");
    const marker = svgNode("marker", {
      id: "flowchartVisualArrow",
      viewBox: "0 0 10 10",
      refX: 9,
      refY: 5,
      markerWidth: 7,
      markerHeight: 7,
      orient: "auto-start-reverse",
    });
    marker.appendChild(
      svgNode("path", {
        d: "M 0 0 L 10 5 L 0 10 z",
        fill: "var(--midena-diagram-connector, #64748b)",
      }),
    );
    defs.appendChild(marker);
    const hatch = svgNode("pattern", {
      id: "flowchartVisualMarqueeHatch",
      width: 8,
      height: 8,
      patternUnits: "userSpaceOnUse",
      patternTransform: "rotate(45)",
    });
    hatch.appendChild(
      svgNode("line", {
        x1: 0,
        y1: 0,
        x2: 0,
        y2: 8,
        class: "flowchart-visual-marquee-hatch-line",
      }),
    );
    defs.appendChild(hatch);
    svg.appendChild(defs);
    const edgeLayer = svgNode("g", { class: "flowchart-visual-edges" });
    const nodeLayer = svgNode("g", { class: "flowchart-visual-nodes" });
    const overlayLayer = svgNode("g", { class: "flowchart-visual-overlays" });
    svg.appendChild(edgeLayer);
    svg.appendChild(nodeLayer);
    svg.appendChild(overlayLayer);
    state.edges.forEach((edge) => {
      const from = flowchartVisualNodeById(edge.from);
      const to = flowchartVisualNodeById(edge.to);
      if (!from || !to) return;
      const pathInfo = flowchartVisualEdgePath(from, to);
      const group = svgNode("g", {
        class: `flowchart-visual-edge ${flowchartVisualIsSelected("edge", edge.id) ? "selected" : ""}`,
        "data-edge-id": edge.id,
      });
      const hitPath = svgNode("path", {
        class: "flowchart-visual-edge-hit",
        d: pathInfo.d,
      });
      const path = svgNode("path", {
        d: pathInfo.d,
        "marker-end": edge.style === "line" ? "" : "url(#flowchartVisualArrow)",
      });
      if (edge.style === "dotted") path.setAttribute("stroke-dasharray", "6 5");
      group.appendChild(hitPath);
      group.appendChild(path);
      if (edge.label) {
        const text = svgNode("text", {
          x: pathInfo.mid.x,
          y: pathInfo.mid.y,
          "text-anchor": "middle",
        });
        text.textContent = edge.label;
        group.appendChild(text);
      }
      group.addEventListener("click", (ev) => {
        ev.stopPropagation();
        flowchartVisualConnectFrom = null;
        selectFlowchartVisual("edge", edge.id);
      });
      edgeLayer.appendChild(group);
    });
    if (flowchartVisualConnectDrag) {
      const from = flowchartVisualNodeById(flowchartVisualConnectDrag.from);
      const target = flowchartVisualConnectDrag.target
        ? flowchartVisualNodeById(flowchartVisualConnectDrag.target)
        : null;
      const point =
        from && target
          ? flowchartVisualEndpoint(from, target).end
          : flowchartVisualConnectDrag.current;
      if (from && point) {
        const preview = svgNode("g", {
          class: "flowchart-visual-connection-preview",
        });
        preview.appendChild(
          svgNode("path", {
            d: flowchartVisualPreviewPath(from, point),
            "marker-end": "url(#flowchartVisualArrow)",
          }),
        );
        edgeLayer.appendChild(preview);
      }
    }
    state.nodes.forEach((node) => {
      const selectedClass = flowchartVisualIsSelected("node", node.id)
        ? "selected"
        : "";
      const pendingClass =
        flowchartVisualConnectFrom === node.id ? "pending-connect" : "";
      const targetClass =
        flowchartVisualConnectDrag?.target === node.id ? "connect-target" : "";
      const draggingClass =
        flowchartVisualDrag?.ids?.includes(node.id) ||
        flowchartVisualDrag?.id === node.id
          ? "dragging"
          : "";
      const group = svgNode("g", {
        class: `flowchart-visual-node ${selectedClass} ${pendingClass} ${targetClass} ${draggingClass}`,
        transform: `translate(${node.x}, ${node.y})`,
        tabindex: "0",
        role: "button",
        "data-node-id": node.id,
      });
      renderFlowchartVisualNodeShape(group, node);
      const lines = flowchartVisualWrapText(
        node.label || node.id,
        node.shape === "decision" ? 14 : 19,
        4,
      );
      const text = svgNode("text", {
        x: node.width / 2,
        y: node.height / 2 - ((lines.length - 1) * 16) / 2,
        "text-anchor": "middle",
        "dominant-baseline": "middle",
      });
      lines.forEach((line, idx) => {
        const tspan = svgNode("tspan", { x: node.width / 2, dy: idx ? 16 : 0 });
        tspan.textContent = line;
        text.appendChild(tspan);
      });
      group.appendChild(text);
      const handlePosition = flowchartVisualHandlePosition(node);
      const handle = svgNode("circle", {
        class: "flowchart-visual-connect-handle",
        cx: handlePosition.x,
        cy: handlePosition.y,
        r: 7,
        tabindex: "0",
        role: "button",
        "aria-label": `Drag from ${node.label || node.id} to another node to connect`,
      });
      handle.appendChild(svgNode("title"));
      handle.querySelector("title").textContent =
        "Drag to another box to add a connector";
      handle.addEventListener("click", (ev) => ev.stopPropagation());
      handle.addEventListener("pointerdown", (ev) => {
        if (ev.button !== 0) return;
        ev.preventDefault();
        ev.stopPropagation();
        stopFlowchartVisualConnectMode();
        selectFlowchartVisual("node", node.id);
        flowchartVisualConnectDrag = {
          from: node.id,
          pointerId: ev.pointerId,
          current: flowchartVisualPointFromEvent(ev),
          target: null,
        };
        setFlowchartVisualStatus(
          `Drag from ${node.label || node.id} to another box to add a connector.`,
          "success",
        );
        renderFlowchartVisualEditor();
      });
      group.appendChild(handle);
      group.addEventListener("click", (ev) => {
        ev.stopPropagation();
        if (flowchartVisualSuppressNextClick) {
          flowchartVisualSuppressNextClick = false;
          return;
        }
        if (flowchartVisualConnectMode) {
          if (!flowchartVisualConnectFrom) {
            flowchartVisualConnectFrom = node.id;
            selectFlowchartVisual("node", node.id);
            setFlowchartVisualStatus(
              `Connecting from ${node.label || node.id}. Click another box to finish, or drag the small handle instead.`,
              "success",
            );
          } else if (flowchartVisualConnectFrom !== node.id) {
            addFlowchartVisualEdge(flowchartVisualConnectFrom, node.id, {
              select: true,
            });
            stopFlowchartVisualConnectMode();
            setFlowchartVisualStatus(
              "Connector added. You can also drag a node handle to connect boxes.",
              "secondary",
            );
            renderFlowchartVisualEditor();
          }
          return;
        }
        selectFlowchartVisual("node", node.id);
      });
      group.addEventListener("pointerdown", (ev) => {
        if (
          flowchartVisualConnectMode ||
          flowchartVisualConnectDrag ||
          ev.button !== 0
        )
          return;
        ev.preventDefault();
        ev.stopPropagation();
        const selection = flowchartVisualNormaliseSelection(
          flowchartVisualEnsureState(),
        );
        const draggingSelection =
          selection.nodes.includes(node.id) && selection.nodes.length > 1;
        if (!draggingSelection) selectFlowchartVisual("node", node.id);
        const dragIds = draggingSelection ? [...selection.nodes] : [node.id];
        flowchartVisualDrag = {
          id: node.id,
          ids: dragIds,
          pointerId: ev.pointerId,
          startX: ev.clientX,
          startY: ev.clientY,
          positions: Object.fromEntries(
            dragIds.map((id) => {
              const item = flowchartVisualNodeById(id);
              return [id, { x: item?.x || 0, y: item?.y || 0 }];
            }),
          ),
          nodeX: node.x,
          nodeY: node.y,
          moved: false,
        };
      });
      nodeLayer.appendChild(group);
    });
    if (flowchartVisualMarquee?.current) {
      const rect = flowchartVisualRectFromPoints(
        flowchartVisualMarquee.start,
        flowchartVisualMarquee.current,
      );
      if (rect.width > 2 || rect.height > 2) {
        overlayLayer.appendChild(
          svgNode("rect", {
            class: "flowchart-visual-marquee",
            x: rect.x,
            y: rect.y,
            width: rect.width,
            height: rect.height,
          }),
        );
      }
    }
    svg.onpointerdown = (ev) => {
      if (
        ev.button !== 0 ||
        flowchartVisualConnectMode ||
        flowchartVisualConnectDrag ||
        flowchartVisualDrag
      )
        return;
      if (ev.target.closest?.(".flowchart-visual-node, .flowchart-visual-edge"))
        return;
      ev.preventDefault();
      const point = flowchartVisualPointFromEvent(ev);
      flowchartVisualMarquee = {
        pointerId: ev.pointerId,
        start: point,
        current: point,
        clientX: ev.clientX,
        clientY: ev.clientY,
        moved: false,
      };
      flowchartVisualSetSelection({ nodes: [], edges: [] });
      setFlowchartVisualStatus(
        "Drag to select every box or connector touched by the hatched region.",
        "secondary",
      );
      renderFlowchartVisualEditor();
    };
    svg.onclick = () => {
      if (flowchartVisualSuppressNextClick) {
        flowchartVisualSuppressNextClick = false;
        return;
      }
      if (flowchartVisualConnectMode && flowchartVisualConnectFrom) {
        flowchartVisualConnectFrom = null;
        setFlowchartVisualStatus(
          "Connect mode is active. Click the first box to connect.",
          "secondary",
        );
        renderFlowchartVisualEditor();
        return;
      }
      selectFlowchartVisual(null, null);
    };
    renderFlowchartVisualProperties();
  }

  function loadFlowchartVisualFromSource() {
    flowchartVisualState = parseFlowchartVisualSource(
      $("#flowchartSource")?.value || DEFAULT_FLOWCHART_SOURCE,
    );
    flowchartVisualConnectFrom = null;
    flowchartVisualConnectDrag = null;
    flowchartVisualMarquee = null;
    flowchartVisualConnectMode = false;
    $("#flowchartConnectBtn")?.classList.remove("active");
    $("#flowchartConnectBtn")?.setAttribute("aria-pressed", "false");
    setFlowchartVisualStatus(
      "Loaded the current Mermaid source into the visual editor.",
      "secondary",
    );
    renderFlowchartVisualEditor();
  }

  function setFlowchartVisualVisible(visible) {
    flowchartVisualVisible = Boolean(visible);
    $("#flowchartVisualBuilder")?.classList.toggle(
      "d-none",
      !flowchartVisualVisible,
    );
    const btn = $("#toggleFlowchartVisualBtn");
    if (btn) {
      btn.classList.toggle("active", flowchartVisualVisible);
      btn.setAttribute(
        "aria-expanded",
        flowchartVisualVisible ? "true" : "false",
      );
      btn.innerHTML = flowchartVisualVisible
        ? '<i class="bi bi-diagram-3 me-1"></i>Hide visual editor'
        : '<i class="bi bi-diagram-3 me-1"></i>Visual editor';
    }
    if (flowchartVisualVisible) {
      flowchartVisualEnsureState({ force: !flowchartVisualState });
      renderFlowchartVisualEditor();
    }
  }

  function addFlowchartVisualNode(shape = "process") {
    const state = flowchartVisualEnsureState();
    const cleanShape = FLOWCHART_VISUAL_SHAPES.has(shape) ? shape : "process";
    const id = uniqueFlowchartId(`N${state.nextNodeNumber++}`, state.nodes);
    const label =
      cleanShape === "decision"
        ? "Decision?"
        : cleanShape === "terminator"
          ? "Start/end"
          : cleanShape === "database"
            ? "Data store"
            : "Process";
    const wrap = $("#flowchartVisualCanvasWrap");
    const offset = state.nodes.length * FLOWCHART_VISUAL_GRID;
    const node = {
      id,
      label,
      shape: cleanShape,
      x: 96 + offset,
      y: 96 + offset,
      width: FLOWCHART_VISUAL_NODE_WIDTH,
      height: FLOWCHART_VISUAL_NODE_HEIGHT,
    };
    snapFlowchartVisualNode(node);
    state.nodes.push(node);
    selectFlowchartVisual("node", id);
    syncFlowchartVisualToSource();
    renderFlowchartVisualEditor();
    wrap?.scrollTo?.({
      left: Math.max(0, node.x - 80),
      top: Math.max(0, node.y - 80),
      behavior: "smooth",
    });
  }

  function deleteSelectedFlowchartVisualItem({ silent = false } = {}) {
    const state = flowchartVisualEnsureState();
    const selection = flowchartVisualNormaliseSelection(state);
    if (!selection.total) {
      if (!silent) toast("Select a node or connector first.", "warning");
      return false;
    }
    const selectedNodeIds = new Set(selection.nodes);
    const selectedEdgeIds = new Set(selection.edges);
    state.nodes = state.nodes.filter((node) => !selectedNodeIds.has(node.id));
    state.edges = state.edges.filter(
      (edge) =>
        !selectedEdgeIds.has(edge.id) &&
        !selectedNodeIds.has(edge.from) &&
        !selectedNodeIds.has(edge.to),
    );
    state.selectedKind = null;
    state.selectedId = null;
    state.selectedNodes = [];
    state.selectedEdges = [];
    selectedElementId = null;
    selectedElement = null;
    renderSelection();
    syncFlowchartVisualToSource();
    renderFlowchartVisualEditor();
    return true;
  }

  function flowchartVisualKeydownTargetIsEditable(target) {
    return Boolean(
      target?.closest?.(
        'input, textarea, select, button, [contenteditable="true"]',
      ),
    );
  }

  function handleFlowchartVisualKeydown(ev) {
    if (!flowchartVisualVisible || !isFlowchart()) return;
    if (!["Delete", "Backspace"].includes(ev.key)) return;
    if (ev.altKey || ev.ctrlKey || ev.metaKey || ev.shiftKey) return;
    if (flowchartVisualKeydownTargetIsEditable(ev.target)) return;
    const state = flowchartVisualState;
    if (!state || !flowchartVisualNormaliseSelection(state).total) return;
    ev.preventDefault();
    deleteSelectedFlowchartVisualItem({ silent: true });
  }

  function updateFlowchartVisualSelectionFromInputs() {
    const state = flowchartVisualEnsureState();
    if (state.selectedKind === "node") {
      const node = flowchartVisualNodeById(state.selectedId);
      if (!node) return;
      node.label = $("#flowchartNodeLabelInput")?.value || node.id;
      node.shape = FLOWCHART_VISUAL_SHAPES.has(
        $("#flowchartNodeShapeInput")?.value,
      )
        ? $("#flowchartNodeShapeInput").value
        : "process";
      const requested = safeFlowchartId(
        $("#flowchartNodeIdInput")?.value || node.id,
        node.id,
      );
      const newId = uniqueFlowchartId(requested, state.nodes, node.id);
      if (newId !== node.id) {
        state.edges.forEach((edge) => {
          if (edge.from === node.id) edge.from = newId;
          if (edge.to === node.id) edge.to = newId;
        });
        node.id = newId;
        state.selectedId = newId;
        state.selectedNodes = [newId];
        selectedElementId = flowchartElementIdForNode(newId);
      }
    } else if (state.selectedKind === "edge") {
      const edge = flowchartVisualEdgeById(state.selectedId);
      if (!edge) return;
      edge.label = $("#flowchartEdgeLabelInput")?.value || "";
      edge.style = ["arrow", "line", "dotted"].includes(
        $("#flowchartEdgeStyleInput")?.value,
      )
        ? $("#flowchartEdgeStyleInput").value
        : "arrow";
    }
    syncFlowchartVisualToSource();
    renderSelection();
    renderFlowchartVisualEditor();
  }

  function bindFlowchartVisualEditor() {
    $("#toggleFlowchartVisualBtn")?.addEventListener("click", () =>
      setFlowchartVisualVisible(!flowchartVisualVisible),
    );
    document.querySelectorAll("[data-flowchart-add-node]").forEach((btn) => {
      btn.addEventListener("click", () => {
        if (!flowchartVisualVisible) setFlowchartVisualVisible(true);
        addFlowchartVisualNode(btn.dataset.flowchartAddNode || "process");
      });
    });
    $("#flowchartConnectBtn")?.addEventListener("click", () => {
      if (!flowchartVisualVisible) setFlowchartVisualVisible(true);
      flowchartVisualConnectMode = !flowchartVisualConnectMode;
      flowchartVisualConnectFrom = null;
      flowchartVisualConnectDrag = null;
      $("#flowchartConnectBtn")?.classList.toggle(
        "active",
        flowchartVisualConnectMode,
      );
      $("#flowchartConnectBtn")?.setAttribute(
        "aria-pressed",
        flowchartVisualConnectMode ? "true" : "false",
      );
      setFlowchartVisualStatus(
        flowchartVisualConnectMode
          ? "Click-connect is active. Click the first box, then the destination box. You can also drag a node handle."
          : "Connect mode off. Drag boxes or drag a node handle to connect items.",
        flowchartVisualConnectMode ? "success" : "secondary",
      );
      renderFlowchartVisualEditor();
    });
    $("#flowchartDeleteSelectedBtn")?.addEventListener("click", () =>
      deleteSelectedFlowchartVisualItem(),
    );
    document.addEventListener("keydown", handleFlowchartVisualKeydown);
    $("#flowchartLoadSourceBtn")?.addEventListener(
      "click",
      loadFlowchartVisualFromSource,
    );
    $("#flowchartAutoLayoutBtn")?.addEventListener("click", () => {
      autoLayoutFlowchartVisual(flowchartVisualEnsureState());
      syncFlowchartVisualToSource();
      renderFlowchartVisualEditor();
    });
    $("#flowchartDirectionInput")?.addEventListener("change", () => {
      const state = flowchartVisualEnsureState();
      state.direction = normaliseFlowchartDirection(
        $("#flowchartDirectionInput").value,
      );
      setFlowchartVisualStatus(
        "Direction updated. Existing positions were preserved; use Auto-layout if you want MIDENA to rearrange the diagram.",
        "secondary",
      );
      syncFlowchartVisualToSource();
      renderFlowchartVisualEditor();
    });
    [
      "flowchartNodeLabelInput",
      "flowchartNodeShapeInput",
      "flowchartNodeIdInput",
      "flowchartEdgeLabelInput",
      "flowchartEdgeStyleInput",
    ].forEach((id) => {
      $(`#${id}`)?.addEventListener(
        id.endsWith("IdInput") ? "change" : "input",
        updateFlowchartVisualSelectionFromInputs,
      );
    });
    document.addEventListener("pointermove", (ev) => {
      if (flowchartVisualMarquee && flowchartVisualState) {
        const point = flowchartVisualPointFromEvent(ev);
        const dx = ev.clientX - (flowchartVisualMarquee.clientX ?? ev.clientX);
        const dy = ev.clientY - (flowchartVisualMarquee.clientY ?? ev.clientY);
        flowchartVisualMarquee.current = point;
        flowchartVisualMarquee.moved =
          flowchartVisualMarquee.moved || Math.abs(dx) + Math.abs(dy) > 3;
        renderFlowchartVisualEditor();
        return;
      }
      if (flowchartVisualConnectDrag && flowchartVisualState) {
        const point = flowchartVisualPointFromEvent(ev);
        const target = flowchartVisualNodeAtPoint(point, {
          exceptId: flowchartVisualConnectDrag.from,
        });
        flowchartVisualConnectDrag.current = point;
        flowchartVisualConnectDrag.target = target?.id || null;
        renderFlowchartVisualEditor();
        return;
      }
      if (!flowchartVisualDrag || !flowchartVisualState) return;
      const dx = ev.clientX - flowchartVisualDrag.startX;
      const dy = ev.clientY - flowchartVisualDrag.startY;
      (flowchartVisualDrag.ids || [flowchartVisualDrag.id]).forEach((id) => {
        const node = flowchartVisualNodeById(id);
        const start = flowchartVisualDrag.positions?.[id] || {
          x: flowchartVisualDrag.nodeX,
          y: flowchartVisualDrag.nodeY,
        };
        if (!node) return;
        node.x = snapFlowchartVisualCoordinate(start.x + dx);
        node.y = snapFlowchartVisualCoordinate(start.y + dy);
      });
      flowchartVisualDrag.moved =
        flowchartVisualDrag.moved || Math.abs(dx) + Math.abs(dy) > 3;
      renderFlowchartVisualEditor();
    });
    document.addEventListener("pointerup", (ev) => {
      if (flowchartVisualMarquee && flowchartVisualState) {
        const point = flowchartVisualPointFromEvent(ev);
        const rect = flowchartVisualRectFromPoints(
          flowchartVisualMarquee.start,
          point,
        );
        const moved =
          flowchartVisualMarquee.moved || rect.width > 3 || rect.height > 3;
        flowchartVisualMarquee = null;
        flowchartVisualSuppressNextClick = true;
        if (moved) {
          const selection = flowchartVisualItemsInRect(rect);
          const result = flowchartVisualSetSelection(selection);
          const parts = [];
          if (result.nodes.length)
            parts.push(
              `${result.nodes.length} node${result.nodes.length === 1 ? "" : "s"}`,
            );
          if (result.edges.length)
            parts.push(
              `${result.edges.length} connector${result.edges.length === 1 ? "" : "s"}`,
            );
          setFlowchartVisualStatus(
            parts.length
              ? `Selected ${parts.join(" and ")}. Press Delete to remove them, or drag a selected box to move the selected boxes.`
              : "No items were inside the selected region.",
            parts.length ? "secondary" : "warning",
          );
        } else {
          flowchartVisualSetSelection({ nodes: [], edges: [] });
        }
        renderFlowchartVisualEditor();
        return;
      }
      if (flowchartVisualConnectDrag && flowchartVisualState) {
        const point = flowchartVisualPointFromEvent(ev);
        const target = flowchartVisualNodeAtPoint(point, {
          exceptId: flowchartVisualConnectDrag.from,
        });
        const from = flowchartVisualConnectDrag.from;
        flowchartVisualConnectDrag = null;
        flowchartVisualSuppressNextClick = true;
        if (target) {
          const edge = addFlowchartVisualEdge(from, target.id, {
            select: true,
          });
          setFlowchartVisualStatus(
            edge
              ? "Connector added by dragging. Select it to edit the label or style."
              : "Could not add that connector.",
            edge ? "secondary" : "warning",
          );
        } else {
          setFlowchartVisualStatus(
            "Connector cancelled. Drag the small handle onto another box to connect it.",
            "secondary",
          );
        }
        renderFlowchartVisualEditor();
        return;
      }
      if (!flowchartVisualDrag) return;
      const moved = flowchartVisualDrag.moved;
      (flowchartVisualDrag.ids || [flowchartVisualDrag.id]).forEach((id) => {
        const node = flowchartVisualNodeById(id);
        if (node) snapFlowchartVisualNode(node);
      });
      flowchartVisualDrag = null;
      if (moved) syncFlowchartVisualToSource();
      renderFlowchartVisualEditor();
    });
  }

  function initMermaidSequence() {
    const t = themeFor("sequence");
    window.mermaid.initialize({
      startOnLoad: false,
      securityLevel: "strict",
      theme: "base",
      themeVariables: {
        fontFamily: t.font_family,
        fontSize: `${t.font_size}px`,
        actorBkg: t.fill_color,
        actorBorder: t.stroke_color,
        actorTextColor: t.text_color,
        labelBoxBkgColor: t.fill_color,
        labelBoxBorderColor: t.stroke_color,
        labelTextColor: t.text_color,
        signalColor: t.connector_color,
        signalTextColor: t.text_color,
        noteBkgColor: t.fill_color,
        noteBorderColor: t.stroke_color,
        noteTextColor: t.text_color,
      },
    });
  }

  function mermaidFlowchartConfig({ htmlLabels = false } = {}) {
    const t = themeFor("flowchart");
    return {
      startOnLoad: false,
      securityLevel: "strict",
      theme: "base",
      flowchart: {
        htmlLabels,
        nodeSpacing: 70,
        rankSpacing: 90,
        padding: 18,
        wrappingWidth: 240,
      },
      htmlLabels,
      themeVariables: {
        primaryColor: t.fill_color,
        primaryTextColor: t.text_color,
        primaryBorderColor: t.stroke_color,
        lineColor: t.connector_color,
        fontFamily: t.font_family,
        fontSize: `${t.font_size}px`,
      },
    };
  }

  function initMermaidFlowchart(options = {}) {
    // The normal preview uses SVG-native labels so the editor itself does not
    // embed foreignObject HTML. The export path can temporarily ask Mermaid to
    // lay out HTML labels, then converts those labels back to pure SVG text
    // before serialising/rasterising. That preserves Mermaid's useful wrapping
    // without reintroducing tainted canvases.
    window.mermaid.initialize(mermaidFlowchartConfig(options));
  }

  function parseSvgLength(value) {
    const match = String(value ?? "").match(/-?\d+(?:\.\d+)?/);
    return match ? Number(match[0]) : 0;
  }

  function svgDimensions(svg) {
    const viewBox = svg?.viewBox?.baseVal;
    let x = Number.isFinite(viewBox?.x) ? viewBox.x : 0;
    let y = Number.isFinite(viewBox?.y) ? viewBox.y : 0;
    let width = Number.isFinite(viewBox?.width) ? viewBox.width : 0;
    let height = Number.isFinite(viewBox?.height) ? viewBox.height : 0;
    if (!width) width = parseSvgLength(svg?.getAttribute("width"));
    if (!height) height = parseSvgLength(svg?.getAttribute("height"));
    try {
      const box = svg?.getBBox?.();
      if (box) {
        width = Math.max(width, box.width || 0);
        height = Math.max(height, box.height || 0);
        if (!Number.isFinite(viewBox?.width) || !viewBox?.width) {
          x = Math.min(x, box.x || 0);
          y = Math.min(y, box.y || 0);
        }
      }
    } catch (_) {
      /* getBBox can fail before layout */
    }
    return {
      x: Number.isFinite(x) ? x : 0,
      y: Number.isFinite(y) ? y : 0,
      width: width > 0 ? width : 1200,
      height: height > 0 ? height : 800,
    };
  }

  function ensureWhiteSvgBackground(svg) {
    if (!svg) return;
    const { x, y, width, height } = svgDimensions(svg);
    const ns = "http://www.w3.org/2000/svg";
    const ownerDocument = svg.ownerDocument || document;
    let bg = svg.querySelector(':scope > rect[data-midena-svg-bg="1"]');
    if (!bg) {
      bg = ownerDocument.createElementNS(ns, "rect");
      bg.setAttribute("data-midena-svg-bg", "1");
      svg.insertBefore(bg, svg.firstChild);
    }
    bg.setAttribute("x", String(x));
    bg.setAttribute("y", String(y));
    bg.setAttribute("width", String(width));
    bg.setAttribute("height", String(height));
    bg.setAttribute("fill", "#ffffff");
    bg.setAttribute("stroke", "none");
    bg.setAttribute("pointer-events", "none");
  }

  function forceSequenceConnectorVisibility(svg) {
    if (!svg) return;
    const connectorSelector = [
      'line[class*="messageLine"]',
      'path[class*="messageLine"]',
      'polyline[class*="messageLine"]',
      'line[class*="loopLine"]',
      'path[class*="loopLine"]',
      'polyline[class*="loopLine"]',
    ].join(",");
    svg.querySelectorAll(connectorSelector).forEach((node) => {
      node.setAttribute("stroke", "#212529");
      node.setAttribute(
        "stroke-width",
        node.getAttribute("stroke-width") || "1.5",
      );
      node.setAttribute("fill", "none");
      node.style.stroke = "#212529";
      node.style.strokeWidth = node.getAttribute("stroke-width") || "1.5";
      node.style.fill = "none";
    });
    svg.querySelectorAll("marker path, marker polygon").forEach((node) => {
      node.setAttribute("fill", "#212529");
      node.setAttribute("stroke", "#212529");
      node.style.fill = "#212529";
      node.style.stroke = "#212529";
    });
  }

  function applySequenceLabelBadges(svg) {
    if (!svg) return;
    const ns = "http://www.w3.org/2000/svg";
    svg
      .querySelectorAll('rect[data-midena-label-badge="1"]')
      .forEach((node) => node.remove());
    const textNodes = [...svg.querySelectorAll("text")].filter((text) => {
      const classText = `${text.getAttribute("class") || ""} ${text.parentElement?.getAttribute("class") || ""}`;
      return (
        /(messageText|noteText|loopText)/i.test(classText) &&
        String(text.textContent || "").trim()
      );
    });
    const candidates = textNodes
      .map((text) => {
        let bbox = null;
        const tspans = [...text.querySelectorAll("tspan")];
        if (tspans.length > 1) {
          tspans.forEach((tspan) => {
            try {
              const box = tspan.getBBox();
              if (
                !box ||
                !Number.isFinite(box.width) ||
                !Number.isFinite(box.height) ||
                box.width <= 0 ||
                box.height <= 0
              )
                return;
              if (!bbox)
                bbox = {
                  x: box.x,
                  y: box.y,
                  width: box.width,
                  height: box.height,
                };
              else {
                const x1 = Math.min(bbox.x, box.x);
                const y1 = Math.min(bbox.y, box.y);
                const x2 = Math.max(bbox.x + bbox.width, box.x + box.width);
                const y2 = Math.max(bbox.y + bbox.height, box.y + box.height);
                bbox = { x: x1, y: y1, width: x2 - x1, height: y2 - y1 };
              }
            } catch (_) {
              /* ignore */
            }
          });
        }
        if (!bbox) {
          try {
            const box = text.getBBox();
            if (box && box.width > 0 && box.height > 0)
              bbox = {
                x: box.x,
                y: box.y,
                width: box.width,
                height: box.height,
              };
          } catch (_) {
            /* ignore */
          }
        }
        return bbox ? { text, parent: text.parentElement || svg, bbox } : null;
      })
      .filter(Boolean);

    const byParent = new Map();
    candidates.forEach((item) => {
      if (!byParent.has(item.parent)) byParent.set(item.parent, []);
      byParent.get(item.parent).push(item);
    });

    function boxesOverlapX(a, b) {
      const left = Math.max(a.x, b.x);
      const right = Math.min(a.x + a.width, b.x + b.width);
      return right >= left - 16;
    }

    function mergeBoxes(items) {
      const x1 = Math.min(...items.map((item) => item.bbox.x));
      const y1 = Math.min(...items.map((item) => item.bbox.y));
      const x2 = Math.max(
        ...items.map((item) => item.bbox.x + item.bbox.width),
      );
      const y2 = Math.max(
        ...items.map((item) => item.bbox.y + item.bbox.height),
      );
      return { x: x1, y: y1, width: x2 - x1, height: y2 - y1 };
    }

    byParent.forEach((items, parent) => {
      const sorted = items
        .slice()
        .sort((a, b) => a.bbox.y - b.bbox.y || a.bbox.x - b.bbox.x);
      const clusters = [];
      sorted.forEach((item) => {
        const previousCluster = clusters[clusters.length - 1];
        const previousBox = previousCluster
          ? mergeBoxes(previousCluster)
          : null;
        const gap = previousBox
          ? item.bbox.y - (previousBox.y + previousBox.height)
          : Infinity;
        if (
          previousCluster &&
          gap <= 14 &&
          boxesOverlapX(previousBox, item.bbox)
        )
          previousCluster.push(item);
        else clusters.push([item]);
      });

      clusters.forEach((cluster) => {
        const bbox = mergeBoxes(cluster);
        const padX = 10;
        const padY = 6;
        const rect = document.createElementNS(ns, "rect");
        rect.setAttribute("data-midena-label-badge", "1");
        rect.setAttribute("x", String(bbox.x - padX));
        rect.setAttribute("y", String(bbox.y - padY));
        rect.setAttribute("width", String(bbox.width + padX * 2));
        rect.setAttribute("height", String(bbox.height + padY * 2));
        rect.setAttribute("rx", "8");
        rect.setAttribute("ry", "8");
        rect.setAttribute("fill", "#ffffff");
        rect.setAttribute("stroke", "#d7c4f6");
        rect.setAttribute("stroke-width", "1");
        rect.setAttribute("pointer-events", "none");
        parent.insertBefore(rect, cluster[0].text);
      });
    });
  }

  function textLinesFromHtmlLabel(node) {
    const lines = [];
    let current = "";
    function flush() {
      const clean = current.replace(/\s+/g, " ").trim();
      if (clean) lines.push(clean);
      current = "";
    }
    function walk(item) {
      if (!item) return;
      if (item.nodeType === Node.TEXT_NODE) {
        current += ` ${item.nodeValue || ""}`;
        return;
      }
      if (item.nodeType !== Node.ELEMENT_NODE) return;
      const name = item.nodeName.toLowerCase();
      if (name === "br") {
        flush();
        return;
      }
      const before = ["div", "p", "li", "tr", "section"].includes(name);
      if (before) flush();
      [...item.childNodes].forEach(walk);
      if (before) flush();
    }
    walk(node);
    flush();
    return lines.length
      ? lines
      : [
          String(node?.textContent || "")
            .replace(/\s+/g, " ")
            .trim(),
        ].filter(Boolean);
  }

  function splitLongWrapToken(token, maxChars) {
    const text = String(token || "");
    if (text.length <= maxChars) return [text];
    const parts = [];
    let current = "";
    [...text].forEach((char) => {
      current += char;
      if (
        current.length >= maxChars ||
        (current.length >= Math.floor(maxChars * 0.55) &&
          /[\/._,;:-]/.test(char))
      ) {
        parts.push(current);
        current = "";
      }
    });
    if (current) parts.push(current);
    return parts.filter(Boolean);
  }

  function wrapSvgTextLine(line, maxChars) {
    const text = String(line || "")
      .replace(/\s+/g, " ")
      .trim();
    if (!text || text.length <= maxChars) return text ? [text] : [];
    const out = [];
    let current = "";
    text
      .split(/\s+/)
      .filter(Boolean)
      .forEach((word) => {
        splitLongWrapToken(word, maxChars).forEach((part, idx) => {
          const separator = idx === 0 && current ? " " : "";
          const candidate = `${current}${separator}${part}`;
          if (!current || candidate.length <= maxChars) {
            current = candidate;
          } else {
            out.push(current.trim());
            current = part;
          }
        });
      });
    if (current) out.push(current.trim());
    return out.length ? out : [text];
  }

  function replaceFlowchartForeignObjects(svg) {
    if (!svg) return;
    const ns = "http://www.w3.org/2000/svg";
    const ownerDocument = svg.ownerDocument || document;
    [...svg.querySelectorAll("foreignObject")].forEach((foreignObject) => {
      const width = parseSvgLength(foreignObject.getAttribute("width")) || 160;
      const height = parseSvgLength(foreignObject.getAttribute("height")) || 40;
      const x = parseSvgLength(foreignObject.getAttribute("x")) || 0;
      const y = parseSvgLength(foreignObject.getAttribute("y")) || 0;
      const fontSize = 14;
      const lineHeight = 17;
      const maxChars = Math.max(8, Math.floor((width - 16) / 7.2));
      const rawLines = textLinesFromHtmlLabel(foreignObject);
      const lines = rawLines
        .flatMap((line) => wrapSvgTextLine(line, maxChars))
        .slice(0, 12);
      const text = ownerDocument.createElementNS(ns, "text");
      text.setAttribute("x", String(x + width / 2));
      text.setAttribute(
        "y",
        String(y + height / 2 - ((lines.length - 1) * lineHeight) / 2),
      );
      text.setAttribute("text-anchor", "middle");
      text.setAttribute("dominant-baseline", "middle");
      text.setAttribute("font-family", "Arial, sans-serif");
      text.setAttribute("font-size", String(fontSize));
      text.setAttribute("fill", "#333333");
      text.setAttribute("data-midena-converted-label", "1");
      lines.forEach((line, idx) => {
        const tspan = ownerDocument.createElementNS(ns, "tspan");
        tspan.setAttribute("x", String(x + width / 2));
        if (idx > 0) tspan.setAttribute("dy", String(lineHeight));
        tspan.textContent = line;
        text.appendChild(tspan);
      });
      foreignObject.replaceWith(text);
    });
  }

  function styleFlowchartSvgForExport(svg) {
    if (!svg) return;
    applyDiagramThemeToRenderedSvg(svg, "flowchart");
  }

  async function renderFlowchartSvgForExport() {
    const source =
      $("#flowchartSource")?.value ||
      diagram?.flowchart_text ||
      diagram?.source_text ||
      "";
    const mermaidSource = normaliseFlowchartSourceForMermaid(source);
    if (!window.mermaid) return lastFlowchartSvg || "";
    initMermaidFlowchart({ htmlLabels: true });
    const renderId = `midena-flowchart-export-${Date.now()}-${Math.floor(Math.random() * 100000)}`;
    const result = await window.mermaid.render(renderId, mermaidSource);
    const parsed = new DOMParser().parseFromString(result.svg, "image/svg+xml");
    const svg = parsed.documentElement;
    if (!svg || svg.nodeName.toLowerCase() !== "svg") return result.svg;
    // Mermaid's HTML labels give the best node sizing/wrapping for flowcharts,
    // but foreignObject taints canvases. Convert them to SVG text before the
    // normal MIDENA export chrome/rasterisation pipeline sees the SVG.
    replaceFlowchartForeignObjects(svg);
    ensureWhiteSvgBackground(svg);
    styleFlowchartSvgForExport(svg);
    return serialiseSvg(svg);
  }

  function serialiseSvg(svg) {
    return new XMLSerializer().serializeToString(svg);
  }

  function fitMermaidPreviewToSvg(selector) {
    const preview = $(selector);
    const svg = preview?.querySelector("svg");
    if (!preview || !svg) return;
    const { width, height } = svgDimensions(svg);
    if (height > 0) preview.style.minHeight = `${Math.ceil(height) + 96}px`;
    if (width > 0) svg.style.minWidth = `${Math.ceil(width) + 40}px`;
  }

  function fitSequencePreviewToSvg() {
    fitMermaidPreviewToSvg("#sequencePreview");
  }

  function fitFlowchartPreviewToSvg() {
    fitMermaidPreviewToSvg("#flowchartPreview");
  }

  function validationPanel(type) {
    return type === "flowchart"
      ? $("#flowchartValidation")
      : $("#sequenceValidation");
  }

  function clearValidation(type) {
    const panel = validationPanel(type);
    if (!panel) return;
    panel.innerHTML = "";
    panel.classList.add("d-none");
  }

  function validationErrorDetail(err) {
    const raw = err?.str || err?.message || String(err || "Syntax error");
    return String(raw).trim() || "Syntax error";
  }

  function showValidation(type, level, title, detail) {
    const panel = validationPanel(type);
    if (!panel) return;
    const alertClass = level === "success" ? "alert-success" : "alert-danger";
    const icon =
      level === "success" ? "bi-check2-circle" : "bi-exclamation-triangle";
    panel.classList.remove("d-none");
    panel.innerHTML = `
      <div class="alert ${alertClass} mb-0 d-flex align-items-start justify-content-between gap-3">
        <div>
          <div class="fw-semibold"><i class="bi ${icon} me-1"></i>${escapeHtml(title)}</div>
          ${detail ? `<pre class="small mb-0 mt-2 text-wrap">${escapeHtml(detail)}</pre>` : ""}
        </div>
        <button class="btn btn-sm btn-outline-secondary flex-shrink-0" type="button" data-clear-validation="${escapeHtml(type)}">Clear</button>
      </div>`;
  }

  function validationTitle(type) {
    return type === "flowchart"
      ? "Flowchart validation failed"
      : "Sequence diagram validation failed";
  }

  function validationSuccessTitle(type) {
    return type === "flowchart"
      ? "Flowchart syntax is valid"
      : "Sequence diagram syntax is valid";
  }

  function cachedRenderedSvgIsUsable(type) {
    return (
      (diagram?.diagram_type || "bpmn") === type &&
      String(diagram?.svg_xml || "").includes("<svg")
    );
  }

  function showCachedSequenceSvg() {
    const preview = $("#sequencePreview");
    if (!preview || !cachedRenderedSvgIsUsable("sequence")) return false;
    placeSvg(preview, diagram.svg_xml);
    const svg = preview.querySelector("svg");
    if (!svg) return false;
    ensureWhiteSvgBackground(svg);
    forceSequenceConnectorVisibility(svg);
    applySequenceLabelBadges(svg);
    applyDiagramThemeToRenderedSvg(svg, "sequence");
    fitSequencePreviewToSvg();
    lastSequenceSvg = serialiseSvg(svg);
    applyRenderedDiagramDecorations();
    return true;
  }

  function showCachedFlowchartSvg() {
    const preview = $("#flowchartPreview");
    if (!preview || !cachedRenderedSvgIsUsable("flowchart")) return false;
    placeSvg(preview, diagram.svg_xml);
    const svg = preview.querySelector("svg");
    if (!svg) return false;
    ensureWhiteSvgBackground(svg);
    applyDiagramThemeToRenderedSvg(svg, "flowchart");
    fitFlowchartPreviewToSvg();
    lastFlowchartSvg = serialiseSvg(svg);
    applyRenderedDiagramDecorations();
    return true;
  }

  async function renderSequence(options = {}) {
    autoSizeSequenceSource();
    const source =
      $("#sequenceSource").value ||
      diagram?.sequence_text ||
      diagram?.source_text ||
      "";
    const preview = $("#sequencePreview");
    if (!preview) return "";
    const mermaidSource = normaliseSequenceSourceForMermaid(source);
    if (options.preferCached && showCachedSequenceSvg()) return lastSequenceSvg;
    try {
      await ensureMermaid();
      initMermaidSequence();
      const renderId = `midena-sequence-${Date.now()}-${Math.floor(Math.random() * 100000)}`;
      const result = await window.mermaid.render(renderId, mermaidSource);
      placeSvg(preview, result.svg);
      const svg = preview.querySelector("svg");
      ensureWhiteSvgBackground(svg);
      forceSequenceConnectorVisibility(svg);
      applySequenceLabelBadges(svg);
      applyDiagramThemeToRenderedSvg(svg, "sequence");
      fitSequencePreviewToSvg();
      lastSequenceSvg = svg ? serialiseSvg(svg) : result.svg;
      applyRenderedDiagramDecorations();
      return lastSequenceSvg;
    } catch (err) {
      lastSequenceSvg = "";
      renderedDiagramTargets = new Map();
      if (options.showErrors) {
        showValidation(
          "sequence",
          "danger",
          validationTitle("sequence"),
          validationErrorDetail(err),
        );
      }
      throw err;
    }
  }

  async function renderFlowchart(options = {}) {
    autoSizeFlowchartSource();
    const source =
      $("#flowchartSource").value ||
      diagram?.flowchart_text ||
      diagram?.source_text ||
      "";
    const preview = $("#flowchartPreview");
    if (!preview) return "";
    const mermaidSource = normaliseFlowchartSourceForMermaid(source);
    if (options.preferCached && showCachedFlowchartSvg())
      return lastFlowchartSvg;
    try {
      await ensureMermaid();
      initMermaidFlowchart();
      const renderId = `midena-flowchart-${Date.now()}-${Math.floor(Math.random() * 100000)}`;
      const result = await window.mermaid.render(renderId, mermaidSource);
      placeSvg(preview, result.svg);
      const svg = preview.querySelector("svg");
      ensureWhiteSvgBackground(svg);
      applyDiagramThemeToRenderedSvg(svg, "flowchart");
      fitFlowchartPreviewToSvg();
      lastFlowchartSvg = svg ? serialiseSvg(svg) : result.svg;
      applyRenderedDiagramDecorations();
      return lastFlowchartSvg;
    } catch (err) {
      lastFlowchartSvg = "";
      renderedDiagramTargets = new Map();
      if (options.showErrors) {
        showValidation(
          "flowchart",
          "danger",
          validationTitle("flowchart"),
          validationErrorDetail(err),
        );
      }
      throw err;
    }
  }

  async function validateSequenceSource(options = {}) {
    try {
      const svg = await renderSequence();
      if (options.showSuccess) {
        showValidation(
          "sequence",
          "success",
          validationSuccessTitle("sequence"),
          "No syntax errors were found.",
        );
      } else {
        clearValidation("sequence");
      }
      return svg;
    } catch (err) {
      showValidation(
        "sequence",
        "danger",
        validationTitle("sequence"),
        validationErrorDetail(err),
      );
      return null;
    }
  }

  async function validateFlowchartSource(options = {}) {
    try {
      const svg = await renderFlowchart();
      if (options.showSuccess) {
        showValidation(
          "flowchart",
          "success",
          validationSuccessTitle("flowchart"),
          "No syntax errors were found.",
        );
      } else {
        clearValidation("flowchart");
      }
      return svg;
    } catch (err) {
      showValidation(
        "flowchart",
        "danger",
        validationTitle("flowchart"),
        validationErrorDetail(err),
      );
      return null;
    }
  }

  async function previewSequence() {
    clearValidation("sequence");
    try {
      await renderSequence();
    } catch (_) {
      toast(
        "Preview could not be updated. Use Validate to see syntax details.",
        "warning",
      );
    }
  }

  async function previewFlowchart() {
    clearValidation("flowchart");
    try {
      await renderFlowchart();
    } catch (_) {
      toast(
        "Preview could not be updated. Use Validate to see syntax details.",
        "warning",
      );
    }
  }

  function scheduleSequencePreview() {
    window.clearTimeout(scheduleSequencePreview.timer);
    autoSizeSequenceSource();
    clearValidation("sequence");
    scheduleSequencePreview.timer = window.setTimeout(() => {
      if (isSequence()) renderSequence().catch(() => {});
    }, 300);
  }

  function scheduleFlowchartPreview() {
    window.clearTimeout(scheduleFlowchartPreview.timer);
    autoSizeFlowchartSource();
    clearValidation("flowchart");
    scheduleFlowchartPreview.timer = window.setTimeout(() => {
      if (isFlowchart()) renderFlowchart().catch(() => {});
    }, 300);
  }

  function aiState(type = activeAiType) {
    return aiChatByType[type] || null;
  }

  function aiTypeLabel(type = activeAiType) {
    return type === "flowchart" ? "flowchart" : "web sequence diagram";
  }

  function currentSourceForType(type) {
    if (type === "flowchart") return $("#flowchartSource")?.value || "";
    if (type === "sequence") return $("#sequenceSource")?.value || "";
    return "";
  }

  async function applyAiCodeToEditor(type, code) {
    const source = String(code || "").trim();
    if (!source) return;
    if (type === "flowchart") {
      destroyModeler();
      setEditorMode("flowchart");
      $("#flowchartSource").value = source;
      autoSizeFlowchartSource();
      flowchartVisualState = null;
      if (flowchartVisualVisible) loadFlowchartVisualFromSource();
      try {
        await renderFlowchart();
      } catch (_) {
        /* Validate shows details if needed */
      }
      return;
    }
    if (type === "sequence") {
      destroyModeler();
      setEditorMode("sequence");
      $("#sequenceSource").value = source;
      autoSizeSequenceSource();
      try {
        await renderSequence();
      } catch (_) {
        /* Validate shows details if needed */
      }
    }
  }

  function renderAiChat() {
    const log = $("#aiChatMessages");
    if (!log) return;
    const state = aiState();
    const items = state?.messages || [];
    if (!items.length) {
      log.innerHTML = `<div class="text-secondary small p-2">Describe the ${escapeHtml(aiTypeLabel())} you want. Follow up after each response to refine the code.</div>`;
    } else {
      log.innerHTML = items
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
    $("#useAiCodeBtn").disabled = !state?.lastCode;
  }

  async function loadAiStatus() {
    if (aiStatus) return aiStatus;
    try {
      aiStatus = await api("/api/v1/diagram-ai/status");
    } catch (err) {
      aiStatus = { enabled: false, error: err.message || String(err) };
    }
    return aiStatus;
  }

  async function openAiDialog(type) {
    if (!["sequence", "flowchart"].includes(type)) {
      toast(
        "AI generation is available for web sequence diagrams and flowcharts.",
        "warning",
      );
      return;
    }
    activeAiType = type;
    $("#aiModalTitle").textContent = `Ask AI for ${aiTypeLabel(type)} code`;
    $("#aiModalHelp").textContent =
      `Describe the ${aiTypeLabel(type)} in plain language. MIDENA sends your prompt and current source to the configured OpenAI-compatible provider, then inserts the returned code into the editor for preview. Save a new version when you are happy with it.`;
    $("#aiPrompt").value = "";
    $("#aiPrompt").placeholder =
      type === "flowchart"
        ? "Example: Create an onboarding flow with account creation, email verification, payment setup, and an exception path."
        : "Example: Show a user, MIDENA, API, and database sequence for creating and previewing a diagram.";
    const status = await loadAiStatus();
    const warning = $("#aiConfigWarning");
    const canUse = Boolean(status?.enabled);
    warning.classList.toggle("d-none", canUse);
    warning.textContent = canUse
      ? ""
      : status?.error ||
        "AI diagram generation is not configured. Set MIDENA_AI_API_KEY and MIDENA_AI_MODEL in the API environment.";
    $("#sendAiPromptBtn").disabled = !canUse;
    renderAiChat();
    bootstrap.Modal.getOrCreateInstance($("#aiModal")).show();
    window.setTimeout(() => $("#aiPrompt")?.focus(), 180);
  }

  async function sendAiPrompt() {
    const type = activeAiType;
    const state = aiState(type);
    if (!state) return;
    const promptText = String($("#aiPrompt")?.value || "").trim();
    if (!promptText) {
      toast("Describe what you want the diagram to show.", "warning");
      return;
    }
    state.messages.push({ role: "user", content: promptText });
    $("#aiPrompt").value = "";
    renderAiChat();
    const sendBtn = $("#sendAiPromptBtn");
    const useBtn = $("#useAiCodeBtn");
    sendBtn.disabled = true;
    useBtn.disabled = true;
    const oldSendText = sendBtn.innerHTML;
    sendBtn.innerHTML =
      '<span class="spinner-border spinner-border-sm me-1" aria-hidden="true"></span>Asking…';
    try {
      const data = await api(
        `/api/v1/diagrams/${encodeURIComponent(id)}/ai/generate`,
        {
          method: "POST",
          body: {
            diagram_type: type,
            messages: state.messages,
            current_source: currentSourceForType(type),
          },
        },
      );
      const code = String(data?.code || "").trim();
      if (!code)
        throw new Error("The AI provider returned empty diagram code.");
      state.lastCode = code;
      state.messages.push({ role: "assistant", content: code });
      renderAiChat();
      await applyAiCodeToEditor(type, code);
      toast(
        "AI code inserted into the editor. Save a new version to persist it.",
        "success",
      );
    } catch (err) {
      // Keep the user's prompt in the chat so they can adjust and retry.
      toast(err.message || String(err), "error");
    } finally {
      const status = await loadAiStatus();
      sendBtn.disabled = !status?.enabled;
      sendBtn.innerHTML = oldSendText;
      $("#useAiCodeBtn").disabled = !state.lastCode;
    }
  }

  function clearAiChat() {
    const state = aiState();
    if (!state) return;
    state.messages = [];
    state.lastCode = "";
    renderAiChat();
    $("#aiPrompt")?.focus();
  }

  async function useLatestAiCode() {
    const state = aiState();
    if (!state?.lastCode || !activeAiType) return;
    await applyAiCodeToEditor(activeAiType, state.lastCode);
    toast(
      "Latest AI code inserted into the editor. Save a new version to persist it.",
      "success",
    );
  }

  async function loadDiagram() {
    diagram = await api(`/api/v1/diagrams/${encodeURIComponent(id)}`);
    renderDetails();
    setEditorMode(diagram.diagram_type || "bpmn");
    if (isSequence()) {
      destroyModeler();
      $("#sequenceSource").value =
        diagram.sequence_text || diagram.source_text || diagram.bpmn_xml || "";
      autoSizeSequenceSource();
      try {
        await renderSequence({ preferCached: true });
      } catch (_) {
        /* already shown */
      }
    } else if (isFlowchart()) {
      destroyModeler();
      $("#flowchartSource").value =
        diagram.flowchart_text || diagram.source_text || diagram.bpmn_xml || "";
      autoSizeFlowchartSource();
      flowchartVisualState = null;
      if (flowchartVisualVisible) loadFlowchartVisualFromSource();
      try {
        await renderFlowchart({ preferCached: true });
      } catch (_) {
        /* already shown */
      }
    } else {
      await ensureModeler(diagram.bpmn_xml);
    }
    links = diagram.entity_links || [];
    metadataLinks = diagram.metadata_links || [];
    renderSelection();
    renderMetadataLinks();
    applyAllDecorations();
  }

  async function loadVersions() {
    const data = await api(
      `/api/v1/diagrams/${encodeURIComponent(id)}/versions`,
    );
    renderVersions(data.items || []);
  }

  async function loadLinks() {
    const data = await api(
      `/api/v1/diagrams/${encodeURIComponent(id)}/entity-links`,
    );
    links = data.items || [];
    renderSelection();
    applyEntityLinkDecorations();
  }

  async function loadComments() {
    const data = await api(
      `/api/v1/diagrams/${encodeURIComponent(id)}/comments`,
    );
    comments = data.items || [];
    renderComments();
    applyCommentDecorations();
  }

  async function loadMetadataLinks() {
    const data = await api(
      `/api/v1/diagrams/${encodeURIComponent(id)}/metadata-links`,
    );
    metadataLinks = data.items || [];
    renderMetadataLinks();
  }

  async function loadShares() {
    const data = await api(`/api/v1/diagrams/${encodeURIComponent(id)}/shares`);
    shares = data.items || [];
    canManageShares = Boolean(data.can_manage);
    renderShares();
  }

  async function saveVersion() {
    let payload;
    if (isSequence()) {
      const svg = await validateSequenceSource();
      if (!svg) return;
      payload = {
        diagram_type: "sequence",
        sequence_text: $("#sequenceSource").value,
        source_text: $("#sequenceSource").value,
        svg_xml: svg,
      };
    } else if (isFlowchart()) {
      const svg = await validateFlowchartSource();
      if (!svg) return;
      payload = {
        diagram_type: "flowchart",
        flowchart_text: $("#flowchartSource").value,
        source_text: $("#flowchartSource").value,
        svg_xml: svg,
      };
    } else {
      const { xml } = await modeler.saveXML({ format: true });
      const { svg } = await modeler.saveSVG();
      payload = {
        diagram_type: "bpmn",
        bpmn_xml: xml,
        source_text: xml,
        svg_xml: applyDiagramThemeToSvgMarkup(svg, "bpmn"),
      };
    }
    payload.change_summary =
      prompt("Change summary for this version:", "Updated diagram") || "";
    const ver = await api(`/api/v1/diagrams/${encodeURIComponent(id)}/save`, {
      method: "POST",
      body: payload,
    });
    toast(`Saved version ${ver.version_number}`, "success");
    await loadDiagram();
    await loadVersions();
  }

  function svgStringWithWhiteBackground(svgMarkup) {
    const parsed = new DOMParser().parseFromString(
      String(svgMarkup || ""),
      "image/svg+xml",
    );
    const svg = parsed.documentElement;
    if (!svg || svg.nodeName.toLowerCase() !== "svg")
      return String(svgMarkup || "");
    ensureWhiteSvgBackground(svg);
    return serialiseSvg(svg);
  }

  function svgStringWithRenderedTargetLinks(svgMarkup, type) {
    if (!window.MIDENA_RENDERED?.applySvgInteractions)
      return String(svgMarkup || "");
    const host = document.createElement("div");
    host.setAttribute("aria-hidden", "true");
    host.style.position = "absolute";
    host.style.left = "-100000px";
    host.style.top = "-100000px";
    host.style.width = "1px";
    host.style.height = "1px";
    host.style.overflow = "hidden";
    host.style.visibility = "hidden";
    host.style.pointerEvents = "none";
    placeSvg(host, String(svgMarkup || ""));
    document.body.appendChild(host);
    try {
      const svg = host.querySelector("svg");
      if (!svg) return String(svgMarkup || "");
      window.MIDENA_RENDERED.applySvgInteractions({
        svg,
        diagramType: type,
        links,
        comments: [],
        selectable: false,
        openTargetLinks: true,
        inlineStyles: true,
        showLinkPills: false,
      });
      return serialiseSvg(svg);
    } finally {
      host.remove();
    }
  }

  function escapeSvgText(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&apos;");
  }

  function escapeSvgAttribute(value) {
    return escapeSvgText(value);
  }

  function exportSvgRootAttributes(sourceSvg) {
    // Mermaid scopes its generated CSS to the root SVG id, for example:
    // `#midena-flowchart-... .node rect { ... }`. Export chrome creates a
    // new outer SVG so that MIDENA headers/footers can be added. If that new
    // root drops the original id, the scoped Mermaid CSS no longer matches and
    // browser rasterisation falls back to black fills/strokes. Preserve the
    // non-layout identity/presentation attributes that Mermaid and assistive
    // technologies may rely on, while still replacing width/height/viewBox for
    // the export page size.
    const copied = [];
    const skip = new Set([
      "width",
      "height",
      "viewBox",
      "xmlns",
      "xmlns:xlink",
      "x",
      "y",
    ]);
    [...(sourceSvg?.attributes || [])].forEach((attr) => {
      if (!attr?.name || skip.has(attr.name)) return;
      copied.push(`${attr.name}="${escapeSvgAttribute(attr.value)}"`);
    });
    return copied.length ? ` ${copied.join(" ")}` : "";
  }

  function svgTextBlock(lines, yStart, width) {
    if (!lines.length) return "";
    const tspans = lines
      .map(
        (line, idx) =>
          `<tspan x="${width / 2}" dy="${idx === 0 ? 0 : 18}">${escapeSvgText(line)}</tspan>`,
      )
      .join("");
    return `<text x="${width / 2}" y="${yStart}" text-anchor="middle" font-family="Arial, sans-serif" font-size="13" fill="#495057">${tspans}</text>`;
  }

  function svgExportSupportNode(node) {
    if (!node || node.nodeType !== Node.ELEMENT_NODE) return false;
    const name = node.nodeName.toLowerCase();
    return ["defs", "style", "metadata", "title", "desc"].includes(name);
  }

  function svgStringWithExportChrome(svgMarkup) {
    const parsed = new DOMParser().parseFromString(
      svgStringWithWhiteBackground(svgMarkup),
      "image/svg+xml",
    );
    const svg = parsed.documentElement;
    if (!svg || svg.nodeName.toLowerCase() !== "svg")
      return String(svgMarkup || "");
    if (isSequence()) forceSequenceConnectorVisibility(svg);
    const { x, y, width, height } = svgDimensions(svg);
    const headerLines = String(diagram?.header_text || "")
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter(Boolean);
    const footerLines = String(diagram?.footer_text || "")
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter(Boolean);
    const headerHeight = headerLines.length ? headerLines.length * 18 + 20 : 0;
    const footerHeight = footerLines.length ? footerLines.length * 18 + 20 : 0;
    const children = [...svg.childNodes];
    const support = children
      .filter(svgExportSupportNode)
      .map((node) => serialiseSvg(node))
      .join("");
    const content = children
      .filter((node) => !svgExportSupportNode(node))
      .map((node) => serialiseSvg(node))
      .join("");
    const totalHeight = height + headerHeight + footerHeight;
    const headerText = svgTextBlock(headerLines, 18, width);
    const footerText = svgTextBlock(
      footerLines,
      headerHeight + height + 18,
      width,
    );
    const rootAttributes = exportSvgRootAttributes(svg);
    return `<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink"${rootAttributes} width="${width}" height="${totalHeight}" viewBox="0 0 ${width} ${totalHeight}">${support}<rect x="0" y="0" width="${width}" height="${totalHeight}" fill="#ffffff"/>${headerText}<g transform="translate(${-x}, ${headerHeight - y})">${content}</g>${footerText}</svg>`;
  }

  async function exportSvgString() {
    if (isSequence()) {
      const svg = svgStringWithRenderedTargetLinks(
        lastSequenceSvg || (await renderSequence()),
        "sequence",
      );
      return svgStringWithExportChrome(svg);
    }
    if (isFlowchart()) {
      const svg = svgStringWithRenderedTargetLinks(
        await renderFlowchartSvgForExport(),
        "flowchart",
      );
      return svgStringWithExportChrome(svg);
    }
    const { svg } = await modeler.saveSVG();
    return svgStringWithExportChrome(applyDiagramThemeToSvgMarkup(svg, "bpmn"));
  }

  function diagramContentBounds() {
    if (!modeler) return { x: 0, y: 0, width: 1200, height: 800 };
    const registry = modeler.get("elementRegistry");
    let minX = Infinity;
    let minY = Infinity;
    let maxX = -Infinity;
    let maxY = -Infinity;
    const includePoint = (point) => {
      if (!point || !Number.isFinite(point.x) || !Number.isFinite(point.y))
        return;
      minX = Math.min(minX, point.x);
      minY = Math.min(minY, point.y);
      maxX = Math.max(maxX, point.x);
      maxY = Math.max(maxY, point.y);
    };
    const includeBox = (element) => {
      if (!Number.isFinite(element.x) || !Number.isFinite(element.y)) return;
      const width = Number.isFinite(element.width) ? element.width : 0;
      const height = Number.isFinite(element.height) ? element.height : 0;
      includePoint({ x: element.x, y: element.y });
      includePoint({ x: element.x + width, y: element.y + height });
    };
    registry.getAll().forEach((element) => {
      if (Array.isArray(element.waypoints))
        element.waypoints.forEach(includePoint);
      else includeBox(element);
    });
    if (![minX, minY, maxX, maxY].every(Number.isFinite))
      return { x: 0, y: 0, width: 1200, height: 800 };
    const padding = 160;
    const naturalWidth = Math.ceil(maxX - minX + padding * 2);
    const naturalHeight = Math.ceil(maxY - minY + padding * 2);
    const width = Math.max(900, naturalWidth);
    const height = Math.max(640, naturalHeight);
    return {
      x: Math.floor(minX - padding - Math.max(0, width - naturalWidth) / 2),
      y: Math.floor(minY - padding - Math.max(0, height - naturalHeight) / 2),
      width,
      height,
    };
  }

  function snapshotStyles(element, properties) {
    const snapshot = {};
    properties.forEach((property) => {
      snapshot[property] = element.style[property] || "";
    });
    return snapshot;
  }

  function restoreStyles(element, snapshot) {
    Object.entries(snapshot).forEach(([property, value]) => {
      element.style[property] = value;
    });
  }

  async function canvasFromSvgMarkup(svgMarkup) {
    const markup = svgStringWithWhiteBackground(svgMarkup);
    const parsed = new DOMParser().parseFromString(markup, "image/svg+xml");
    const svg = parsed.documentElement;
    if (!svg || svg.nodeName.toLowerCase() !== "svg")
      throw new Error("Invalid SVG export.");
    const { width, height } = svgDimensions(svg);
    svg.setAttribute("width", String(width));
    svg.setAttribute("height", String(height));
    const finalMarkup = serialiseSvg(svg);
    // Use Blob URL instead of data URL to avoid CORS/tainting issues
    const blob = new Blob([finalMarkup], {
      type: "image/svg+xml;charset=utf-8",
    });
    const url = URL.createObjectURL(blob);
    try {
      const img = await new Promise((resolve, reject) => {
        const image = new Image();
        image.onload = () => resolve(image);
        image.onerror = () =>
          reject(new Error("Failed to rasterise SVG export."));
        image.src = url;
      });
      const scale = Math.max(2, window.devicePixelRatio || 1);
      const canvas = document.createElement("canvas");
      canvas.width = Math.ceil(width * scale);
      canvas.height = Math.ceil(height * scale);
      const ctx = canvas.getContext("2d");
      ctx.fillStyle = "#ffffff";
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.scale(scale, scale);
      ctx.drawImage(img, 0, 0, width, height);
      return canvas;
    } finally {
      URL.revokeObjectURL(url);
    }
  }

  async function renderedDiagramToCanvas() {
    const target = $(".diagram-card");
    const canvasElement = $("#canvas");
    if (!target) throw new Error("Diagram export area not found");
    await ensureHtml2Canvas();

    if (isSequence() || isFlowchart()) {
      return canvasFromSvgMarkup(await exportSvgString());
    }

    const canvas = modeler.get("canvas");
    const originalViewbox = canvas.viewbox();
    const bounds = diagramContentBounds();
    const targetStyles = snapshotStyles(target, [
      "width",
      "height",
      "minHeight",
      "maxWidth",
      "overflow",
    ]);
    const canvasStyles = snapshotStyles(canvasElement, [
      "width",
      "height",
      "minHeight",
    ]);
    try {
      target.style.width = `${bounds.width}px`;
      target.style.height = "auto";
      target.style.minHeight = "0";
      target.style.maxWidth = "none";
      target.style.overflow = "visible";
      canvasElement.style.width = `${bounds.width}px`;
      canvasElement.style.height = `${bounds.height}px`;
      canvasElement.style.minHeight = `${bounds.height}px`;
      canvas.resized?.();
      canvas.viewbox(bounds);
      applyAllDecorations();
      await new Promise((resolve) =>
        window.requestAnimationFrame(() =>
          window.requestAnimationFrame(resolve),
        ),
      );
      return await window.html2canvas(target, {
        backgroundColor: "#ffffff",
        scale: Math.max(2, window.devicePixelRatio || 1),
        useCORS: true,
        logging: false,
        onclone: (doc) => {
          doc
            .querySelectorAll(
              ".djs-palette, .djs-context-pad, .bjs-powered-by, .midena-comment-overlay",
            )
            .forEach((el) => {
              el.style.display = "none";
            });
          doc.querySelectorAll(".midena-commented-element").forEach((el) => {
            el.classList.remove("midena-commented-element");
          });
        },
      });
    } finally {
      restoreStyles(target, targetStyles);
      restoreStyles(canvasElement, canvasStyles);
      canvas.resized?.();
      canvas.viewbox(originalViewbox);
      applyAllDecorations();
    }
  }

  function buildEmbedCode() {
    const url = publicEmbedUrl();
    const title = (diagram.name || "MIDENA diagram")
      .replace(/&/g, "&amp;")
      .replace(/"/g, "&quot;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
    return `<iframe src="${url}" title="${title}" width="100%" height="720" style="border:0; width:100%; min-height:720px;" loading="lazy" referrerpolicy="strict-origin-when-cross-origin"></iframe>`;
  }

  async function copyToClipboard(text) {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return;
    }
    const textarea = $("#embedCode");
    textarea.focus();
    textarea.select();
    document.execCommand("copy");
  }

  function showEmbedCode() {
    if (diagram?.visibility !== "public" || !publicEmbedUrl()) {
      toast(
        "Only public diagrams can be embedded. Set visibility to Public and save the diagram details first.",
        "warning",
      );
      return;
    }
    $("#embedCode").value =
      `${buildEmbedCode()}\n\nDirect public view:\n${publicViewUrl()}`;
    bootstrap.Modal.getOrCreateInstance($("#embedModal")).show();
  }

  async function exportDiagram(fmt) {
    const effectiveFmt = fmt === "source" ? "bpmn" : fmt;
    if (effectiveFmt === "bpmn") {
      if (isSequence())
        downloadText(
          filename(sourceExtension()),
          $("#sequenceSource").value,
          "text/plain",
        );
      else if (isFlowchart())
        downloadText(
          filename(sourceExtension()),
          $("#flowchartSource").value,
          "text/plain",
        );
      else {
        const { xml } = await modeler.saveXML({ format: true });
        downloadText(filename("bpmn"), xml, "application/xml");
      }
      return;
    }
    if (effectiveFmt === "svg") {
      downloadText(filename("svg"), await exportSvgString(), "image/svg+xml");
      return;
    }
    const { canvas, svgMarkup } = await renderedExportCanvasAndSvg();
    if (effectiveFmt === "png" || effectiveFmt === "jpg") {
      const a = document.createElement("a");
      a.download = filename(effectiveFmt);
      a.href = canvas.toDataURL(
        effectiveFmt === "jpg" ? "image/jpeg" : "image/png",
        0.92,
      );
      a.click();
      return;
    }
    if (effectiveFmt === "pdf") {
      await ensureJsPdf();
      const { jsPDF } = window.jspdf;
      const pdf = new jsPDF({
        orientation: canvas.width >= canvas.height ? "landscape" : "portrait",
        unit: "px",
        format: [canvas.width, canvas.height],
      });
      pdf.addImage(
        canvas.toDataURL("image/png"),
        "PNG",
        0,
        0,
        canvas.width,
        canvas.height,
      );
      addRenderedPdfLinks(pdf, svgMarkup, canvas);
      pdf.save(filename("pdf"));
    }
  }

  function dataUrlToBase64(dataUrl) {
    return String(dataUrl || "").split(",", 2)[1] || "";
  }

  function blobToBase64(blob) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(dataUrlToBase64(reader.result));
      reader.onerror = () =>
        reject(reader.error || new Error("Failed to read blob"));
      reader.readAsDataURL(blob);
    });
  }

  function textToBase64(text) {
    return btoa(unescape(encodeURIComponent(text || "")));
  }

  function splitSvgNumbers(value) {
    return String(value || "")
      .trim()
      .split(/[\s,]+/)
      .map(Number)
      .filter(Number.isFinite);
  }

  function transformSvgPoint(point, transform) {
    let next = { x: point.x, y: point.y };
    const commands = String(transform || "").matchAll(
      /(matrix|translate)\(([^)]+)\)/g,
    );
    for (const command of commands) {
      const kind = command[1];
      const values = splitSvgNumbers(command[2]);
      if (kind === "translate") {
        next = { x: next.x + (values[0] || 0), y: next.y + (values[1] || 0) };
      } else if (kind === "matrix" && values.length >= 6) {
        const [a, b, c, d, e, f] = values;
        next = {
          x: a * next.x + c * next.y + e,
          y: b * next.x + d * next.y + f,
        };
      }
    }
    return next;
  }

  function transformSvgBox(box, transform) {
    const points = [
      { x: box.x, y: box.y },
      { x: box.x + box.width, y: box.y },
      { x: box.x, y: box.y + box.height },
      { x: box.x + box.width, y: box.y + box.height },
    ].map((point) => transformSvgPoint(point, transform));
    const xs = points.map((point) => point.x);
    const ys = points.map((point) => point.y);
    const x1 = Math.min(...xs);
    const y1 = Math.min(...ys);
    const x2 = Math.max(...xs);
    const y2 = Math.max(...ys);
    return { x: x1, y: y1, width: x2 - x1, height: y2 - y1 };
  }

  function boxInRootSvgCoordinates(rect, svg) {
    let box = {
      x: parseSvgLength(rect.getAttribute("x")),
      y: parseSvgLength(rect.getAttribute("y")),
      width: parseSvgLength(rect.getAttribute("width")),
      height: parseSvgLength(rect.getAttribute("height")),
    };
    let node = rect.parentElement;
    while (node && node !== svg) {
      box = transformSvgBox(box, node.getAttribute?.("transform") || "");
      node = node.parentElement;
    }
    return box;
  }

  function renderedPdfLinkAnnotations(svgMarkup, canvas) {
    if (!svgMarkup || !canvas) return [];
    const parsed = new DOMParser().parseFromString(
      String(svgMarkup || ""),
      "image/svg+xml",
    );
    const svg = parsed.documentElement;
    if (!svg || svg.nodeName.toLowerCase() !== "svg") return [];
    const width =
      parseSvgLength(svg.getAttribute("width")) ||
      svgDimensions(svg).width ||
      canvas.width;
    const height =
      parseSvgLength(svg.getAttribute("height")) ||
      svgDimensions(svg).height ||
      canvas.height;
    const scaleX = width ? canvas.width / width : 1;
    const scaleY = height ? canvas.height / height : 1;
    return [...svg.querySelectorAll("a[data-midena-rendered-target-link]")]
      .map((anchor) => {
        const url =
          anchor.getAttribute("href") ||
          anchor.getAttributeNS("http://www.w3.org/1999/xlink", "href");
        const rect = anchor.querySelector("rect");
        if (!url || !rect) return null;
        const box = boxInRootSvgCoordinates(rect, svg);
        if (!box.width || !box.height) return null;
        return {
          url,
          x: box.x * scaleX,
          y: box.y * scaleY,
          width: box.width * scaleX,
          height: box.height * scaleY,
        };
      })
      .filter(Boolean);
  }

  function addRenderedPdfLinks(pdf, svgMarkup, canvas) {
    renderedPdfLinkAnnotations(svgMarkup, canvas).forEach((link) => {
      pdf.link(link.x, link.y, link.width, link.height, { url: link.url });
    });
  }

  async function renderedExportCanvasAndSvg() {
    if (!isSequence() && !isFlowchart())
      return { canvas: await renderedDiagramToCanvas(), svgMarkup: "" };
    const svgMarkup = await exportSvgString();
    return { canvas: await canvasFromSvgMarkup(svgMarkup), svgMarkup };
  }

  // Source and SVG are taken from the saved version by the server; only the
  // formats the browser draws carry content.
  async function buildDriveExportPayload(format) {
    if (format === "source" || format === "svg") return { format };
    const { canvas, svgMarkup } = await renderedExportCanvasAndSvg();
    if (format === "png" || format === "jpg") {
      const mime = format === "jpg" ? "image/jpeg" : "image/png";
      return {
        format,
        content_base64: dataUrlToBase64(canvas.toDataURL(mime, 0.92)),
      };
    }
    if (format === "pdf") {
      await ensureJsPdf();
      const { jsPDF } = window.jspdf;
      const pdf = new jsPDF({
        orientation: canvas.width >= canvas.height ? "landscape" : "portrait",
        unit: "px",
        format: [canvas.width, canvas.height],
      });
      pdf.addImage(
        canvas.toDataURL("image/png"),
        "PNG",
        0,
        0,
        canvas.width,
        canvas.height,
      );
      addRenderedPdfLinks(pdf, svgMarkup, canvas);
      return { format, content_base64: await blobToBase64(pdf.output("blob")) };
    }
    throw new Error(`Unsupported Google Drive export format: ${format}`);
  }

  async function exportToDrive() {
    const format = $("#driveFormat").value || "svg";
    const payload = await buildDriveExportPayload(format);
    const result = await api(
      `/api/v1/diagrams/${encodeURIComponent(id)}/export/google-drive`,
      { method: "POST", body: payload },
    );
    const link = safeHref(result.webViewLink);
    toast(
      link
        ? `Exported to Google Drive: ${result.name || ""}`
        : "Exported to Google Drive.",
      "success",
    );
    if (link) window.open(link, "_blank", "noopener,noreferrer");
    bootstrap.Modal.getOrCreateInstance($("#driveModal")).hide();
  }

  async function cloneDiagram() {
    if (
      !window.confirm(
        `Clone ${diagram?.name || "this diagram"} into a new editable diagram?`,
      )
    )
      return;
    const cloned = await api(
      `/api/v1/diagrams/${encodeURIComponent(id)}/clone`,
      {
        method: "POST",
      },
    );
    toast("Diagram cloned.", "success");
    window.location.href = `/diagram.html?id=${encodeURIComponent(cloned.uuid)}`;
  }

  function importLooksLikeBpmn(source) {
    return (
      /<\s*(?:bpmn:)?definitions\b/i.test(source) || /xmlns:bpmn=/i.test(source)
    );
  }

  async function applyImport() {
    const source = $("#importSource").value.trim();
    if (!source) {
      toast(
        "Paste BPMN XML, sequence diagram code, or flowchart code first.",
        "warning",
      );
      return;
    }
    if (importLooksLikeBpmn(source)) {
      setEditorMode("bpmn");
      destroyModeler();
      await ensureModeler(source);
      toast(
        "BPMN XML imported into the editor. Save a new version to persist it.",
        "success",
      );
    } else if (/^[ \t]*(?:flowchart|graph)\b/im.test(source)) {
      destroyModeler();
      setEditorMode("flowchart");
      $("#flowchartSource").value = source;
      autoSizeFlowchartSource();
      flowchartVisualState = null;
      if (flowchartVisualVisible) loadFlowchartVisualFromSource();
      try {
        await renderFlowchart();
      } catch (_) {
        /* already shown */
      }
      toast(
        "Flowchart source imported. Save a new version to persist it.",
        "success",
      );
    } else {
      destroyModeler();
      setEditorMode("sequence");
      $("#sequenceSource").value = source;
      autoSizeSequenceSource();
      try {
        await renderSequence();
      } catch (_) {
        /* already shown */
      }
      toast(
        "Sequence diagram source imported. Save a new version to persist it.",
        "success",
      );
    }
    bootstrap.Modal.getOrCreateInstance($("#importModal")).hide();
  }

  async function updateUserSuggestions(value) {
    const query = String(value || "").trim();
    if (query.length < 2) return;
    try {
      const data = await api(
        `/api/v1/users/search?q=${encodeURIComponent(query)}`,
      );
      $("#userSuggestions").innerHTML = (data.items || [])
        .map(
          (u) =>
            `<option value="${escapeHtml(u.email || u.username)}">${escapeHtml(u.username)}${u.email ? ` · ${escapeHtml(u.email)}` : ""}</option>`,
        )
        .join("");
    } catch (_) {
      /* suggestions are non-critical */
    }
  }

  $("#saveBtn").addEventListener("click", () =>
    saveVersion().catch((err) => toast(err.message, "error")),
  );
  $("#lockBtn").addEventListener("click", async () => {
    try {
      await api(`/api/v1/diagrams/${encodeURIComponent(id)}/lock`, {
        method: "POST",
        body: { ttl_seconds: 1800 },
      });
      toast("Diagram locked for editing.", "success");
      await loadDiagram();
    } catch (err) {
      toast(err.message, "error");
    }
  });
  $("#unlockBtn").addEventListener("click", async () => {
    try {
      await api(`/api/v1/diagrams/${encodeURIComponent(id)}/lock`, {
        method: "DELETE",
      });
      toast("Diagram unlocked.", "success");
      await loadDiagram();
    } catch (err) {
      toast(err.message, "error");
    }
  });
  $("#saveMetaBtn").addEventListener("click", async () => {
    try {
      diagram = await api(`/api/v1/diagrams/${encodeURIComponent(id)}`, {
        method: "PATCH",
        body: {
          name: $("#nameInput").value,
          description: $("#descriptionInput").value,
          tags: $("#tagsInput")
            .value.split(",")
            .map((x) => x.trim())
            .filter(Boolean),
          visibility: $("#visibilityInput").value || "private",
          folder_id: $("#folderInput").value
            ? Number($("#folderInput").value)
            : null,
        },
      });
      await loadTagCatalog();
      renderDetails();
      toast("Diagram details saved.", "success");
    } catch (err) {
      toast(err.message, "error");
    }
  });
  $("#deleteDiagramBtn")?.addEventListener("click", async () => {
    if (!canDeleteDiagram()) {
      toast(
        "Only the diagram owner or an admin can delete this diagram.",
        "warning",
      );
      return;
    }
    const name = diagram?.name || "this diagram";
    if (!window.confirm(`Delete ${name}? This cannot be undone.`)) return;
    try {
      await api(`/api/v1/diagrams/${encodeURIComponent(id)}`, {
        method: "DELETE",
      });
      toast("Diagram deleted.", "success");
      window.location.href = "/index.html";
    } catch (err) {
      toast(err.message, "error");
    }
  });
  document
    .querySelectorAll("[data-export]")
    .forEach((btn) =>
      btn.addEventListener("click", () =>
        exportDiagram(btn.dataset.export).catch((err) =>
          toast(err.message, "error"),
        ),
      ),
    );
  $("#googleDriveBtn")?.addEventListener("click", () =>
    bootstrap.Modal.getOrCreateInstance($("#driveModal")).show(),
  );
  $("#sendDriveExportBtn")?.addEventListener("click", () =>
    exportToDrive().catch((err) => toast(err.message, "error")),
  );
  $("#embedBtn").addEventListener("click", showEmbedCode);
  $("#copyEmbedBtn").addEventListener("click", async () => {
    try {
      await copyToClipboard($("#embedCode").value || buildEmbedCode());
      toast("Embed code copied.", "success");
    } catch (err) {
      toast(`Could not copy embed code: ${err.message || err}`, "error");
    }
  });
  $("#toggleSidebarBtn")?.addEventListener("click", () =>
    setSidebarExpanded($("#diagramSidebar")?.classList.contains("d-none")),
  );
  $("#toggleEditorBtn")?.addEventListener("click", () =>
    setEditorCollapsed(!editorCollapsed),
  );
  $("#cloneBtn")?.addEventListener("click", () =>
    cloneDiagram().catch((err) => toast(err.message, "error")),
  );
  $("#importBtn").addEventListener("click", () => {
    if (isSequence())
      $("#importSource").value = $("#sequenceSource").value || "";
    else if (isFlowchart())
      $("#importSource").value = $("#flowchartSource").value || "";
    else $("#importSource").value = "";
    bootstrap.Modal.getOrCreateInstance($("#importModal")).show();
  });
  $("#applyImportBtn").addEventListener("click", () =>
    applyImport().catch((err) => toast(err.message, "error")),
  );
  $("#renderSequenceBtn")?.addEventListener("click", () => previewSequence());
  $("#renderFlowchartBtn")?.addEventListener("click", () => previewFlowchart());
  $("#validateSequenceBtn")?.addEventListener("click", () =>
    validateSequenceSource({ showSuccess: true }),
  );
  $("#validateFlowchartBtn")?.addEventListener("click", () =>
    validateFlowchartSource({ showSuccess: true }),
  );
  $("#askAiSequenceBtn")?.addEventListener("click", () =>
    openAiDialog("sequence"),
  );
  $("#askAiFlowchartBtn")?.addEventListener("click", () =>
    openAiDialog("flowchart"),
  );
  $("#sendAiPromptBtn")?.addEventListener("click", () => sendAiPrompt());
  $("#aiPromptForm")?.addEventListener("submit", (ev) => {
    ev.preventDefault();
    sendAiPrompt();
  });
  $("#aiPrompt")?.addEventListener("keydown", (ev) => {
    if ((ev.ctrlKey || ev.metaKey) && ev.key === "Enter") {
      ev.preventDefault();
      sendAiPrompt();
    }
  });
  $("#clearAiChatBtn")?.addEventListener("click", clearAiChat);
  $("#useAiCodeBtn")?.addEventListener("click", () =>
    useLatestAiCode().catch((err) => toast(err.message, "error")),
  );
  $("#toggleSequenceSourceBtn")?.addEventListener("click", () =>
    setSourcePanelCollapsed("sequence", !sourcePanelCollapsed.sequence),
  );
  $("#toggleFlowchartSourceBtn")?.addEventListener("click", () =>
    setSourcePanelCollapsed("flowchart", !sourcePanelCollapsed.flowchart),
  );
  document.addEventListener("click", (ev) => {
    const clearBtn = ev.target?.closest?.("[data-clear-validation]");
    if (clearBtn) clearValidation(clearBtn.dataset.clearValidation);
  });
  $("#sequenceSource")?.addEventListener("input", scheduleSequencePreview);
  $("#flowchartSource")?.addEventListener("input", () => {
    scheduleFlowchartPreview();
    if (!flowchartVisualSyncing && flowchartVisualVisible)
      loadFlowchartVisualFromSource();
  });
  bindFlowchartVisualEditor();
  document
    .querySelectorAll("[data-tool]")
    .forEach((btn) =>
      btn.addEventListener("click", (ev) =>
        runModelerTool(btn.dataset.tool, ev),
      ),
    );
  $("#commentForm").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    try {
      await api(`/api/v1/diagrams/${encodeURIComponent(id)}/comments`, {
        method: "POST",
        body: {
          body: $("#commentBody").value,
          element_id: selectedElementId || null,
        },
      });
      $("#commentBody").value = "";
      await loadComments();
      toast("Comment added to the diagram.", "success");
    } catch (err) {
      toast(err.message, "error");
    }
  });
  $("#entityLinkForm").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    if (!selectedElementId) {
      toast("Select a diagram element first.", "warning");
      return;
    }
    try {
      await api(`/api/v1/diagrams/${encodeURIComponent(id)}/entity-links`, {
        method: "POST",
        body: {
          element_id: selectedElementId,
          label: $("#entityLabel").value,
          url: $("#entityUrl").value,
        },
      });
      $("#entityLinkForm").reset();
      await loadLinks();
    } catch (err) {
      toast(err.message, "error");
    }
  });
  $("#metadataLinkForm").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    try {
      await api(`/api/v1/diagrams/${encodeURIComponent(id)}/metadata-links`, {
        method: "POST",
        body: {
          label: $("#metadataLabel").value,
          url: $("#metadataUrl").value,
          notes: $("#metadataNotes").value || null,
        },
      });
      $("#metadataLinkForm").reset();
      await loadMetadataLinks();
      toast("Metadata link added.", "success");
    } catch (err) {
      toast(err.message, "error");
    }
  });
  $("#shareForm").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    try {
      await api(`/api/v1/diagrams/${encodeURIComponent(id)}/shares`, {
        method: "POST",
        body: {
          identifier: $("#shareIdentifier").value,
          role: $("#shareRole").value,
          notify: $("#shareNotify").checked,
        },
      });
      $("#shareForm").reset();
      $("#shareNotify").checked = true;
      await loadShares();
      toast("Sharing permissions updated.", "success");
    } catch (err) {
      toast(err.message, "error");
    }
  });
  $("#shareIdentifier").addEventListener("input", (ev) =>
    updateUserSuggestions(ev.target.value),
  );
  bindTagInput();
  setupSidebarSectionToggles();
  refreshEditorCollapseButton();
  setSidebarExpanded(!sidebarCollapsedByDefault);

  function optionalLoad(label, loader) {
    return loader().catch((err) =>
      toast(`${label}: ${err.message || err}`, "warning"),
    );
  }

  try {
    const foldersPromise = optionalLoad("Could not load folders", loadFolders);
    const tagsPromise = optionalLoad("Could not load tags", async () => {
      await loadTagCatalog();
      if (diagram) renderDetails();
    });
    await loadDiagram();
    void Promise.allSettled([foldersPromise, tagsPromise]);
    void Promise.allSettled([
      optionalLoad("Could not load versions", loadVersions),
      optionalLoad("Could not load comments", loadComments),
      optionalLoad("Could not load sharing permissions", loadShares),
    ]);
  } catch (err) {
    toast(err.message, "error");
  }
})();
