// Administration tabs for the diagram workspace: active locks, the global
// header and footer, and the diagram theme. Every value from the API is
// written as text or escaped before it reaches markup.
(() => {
  const DEFAULT_THEME = {
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
  const THEME_TYPES = [
    ["bpmn", "BPMN symbols"],
    ["flowchart", "Flowchart boxes"],
    ["sequence", "Sequence participants and messages"],
  ];
  const THEME_FIELDS = [
    ["fill_color", "Fill colour", "color"],
    ["stroke_color", "Border colour", "color"],
    ["text_color", "Font colour", "color"],
    ["connector_color", "Connector colour", "color"],
    ["border_width", "Border thickness", "number"],
    ["connector_width", "Connector thickness", "number"],
    ["font_family", "Font family", "text"],
    ["font_size", "Font size", "number"],
  ];

  const cloneTheme = (value = DEFAULT_THEME) =>
    JSON.parse(JSON.stringify(value));

  function renderThemeForm(theme) {
    const { escapeHtml } = window.MIDENA;
    const effective = cloneTheme();
    for (const [type, values] of Object.entries(theme || {})) {
      if (effective[type] && values && typeof values === "object") {
        Object.assign(effective[type], values);
      }
    }
    document.getElementById("diagramThemeForm").innerHTML = THEME_TYPES.map(
      ([type, title]) => `
      <div class="col-12 col-xl-4"><div class="border rounded p-3 h-100">
        <div class="fw-semibold mb-2">${escapeHtml(title)}</div>
        <div class="row g-2">${THEME_FIELDS.map(([field, label, inputType]) => {
          const id = `theme_${type}_${field}`;
          const attrs =
            inputType === "number" ? ' min="0.5" max="28" step="0.1"' : "";
          return `<div class="col-12 ${inputType === "color" ? "col-sm-6" : ""}"><label class="form-label small text-muted mb-1" for="${id}">${escapeHtml(label)}</label><input class="form-control form-control-sm" id="${id}" data-theme-type="${type}" data-theme-field="${field}" type="${inputType}" value="${escapeHtml(effective[type][field])}"${attrs}></div>`;
        }).join("")}</div>
      </div></div>`,
    ).join("");
  }

  function readThemeForm() {
    const theme = cloneTheme();
    document
      .querySelectorAll("[data-theme-type][data-theme-field]")
      .forEach((input) => {
        const { themeType: type, themeField: field } = input.dataset;
        if (!theme[type]) return;
        theme[type][field] = [
          "border_width",
          "connector_width",
          "font_size",
        ].includes(field)
          ? Number(input.value)
          : input.value;
      });
    return theme;
  }

  async function loadLocks() {
    const { api, escapeHtml, formatTimestamp, toast } = window.MIDENA;
    const data = await api("/v1/admin/diagram-locks");
    const rows = document.getElementById("lockRows");
    const items = data.items || [];
    rows.innerHTML = items.length
      ? items
          .map(
            (l) =>
              `<tr><td><a href="/diagram.html?id=${encodeURIComponent(l.diagram_uuid)}">${escapeHtml(l.diagram_name)}</a></td><td>${escapeHtml(l.locked_by || "")}</td><td>${escapeHtml(formatTimestamp(l.locked_at))}</td><td>${escapeHtml(formatTimestamp(l.expires_at))}</td><td class="text-end"><button class="btn btn-sm btn-outline-danger" type="button" data-unlock="${Number(l.diagram_id)}">Force unlock</button></td></tr>`,
          )
          .join("")
      : '<tr><td colspan="5" class="text-muted p-4">No active locks.</td></tr>';
    rows.querySelectorAll("[data-unlock]").forEach((btn) =>
      btn.addEventListener("click", async () => {
        try {
          await api(`/v1/admin/diagrams/${Number(btn.dataset.unlock)}/unlock`, {
            method: "POST",
          });
          toast("Diagram unlocked.", "success");
          await loadLocks();
        } catch (err) {
          toast(err.message, "error");
        }
      }),
    );
  }

  async function saveChrome(extra = {}) {
    const chrome = await window.MIDENA.api("/v1/admin/diagram-chrome", {
      method: "PUT",
      body: {
        header_text: document.getElementById("globalHeader").value,
        footer_text: document.getElementById("globalFooter").value,
        ...extra,
      },
    });
    renderThemeForm(chrome.theme_settings || DEFAULT_THEME);
  }

  async function init() {
    if (!window.MIDENA) return;
    const { api, toast } = window.MIDENA;
    const me = await window.MIDENA.ensureInitialized();
    if (!me || !window.MIDENA.isAdmin()) return;
    document
      .getElementById("saveChromeBtn")
      ?.addEventListener("click", async () => {
        try {
          await saveChrome();
          toast("Global header and footer saved.", "success");
        } catch (err) {
          toast(err.message, "error");
        }
      });
    document
      .getElementById("saveThemeBtn")
      ?.addEventListener("click", async () => {
        try {
          await saveChrome({ theme_settings: readThemeForm() });
          toast("Global diagram theme saved.", "success");
        } catch (err) {
          toast(err.message, "error");
        }
      });
    document
      .getElementById("resetThemeBtn")
      ?.addEventListener("click", () => renderThemeForm(DEFAULT_THEME));
    try {
      const chrome = await api("/v1/admin/diagram-chrome");
      document.getElementById("globalHeader").value = chrome.header_text || "";
      document.getElementById("globalFooter").value = chrome.footer_text || "";
      renderThemeForm(chrome.theme_settings || DEFAULT_THEME);
      await loadLocks();
    } catch (err) {
      toast(err.message, "error");
    }
  }

  document.addEventListener("DOMContentLoaded", init);
})();
