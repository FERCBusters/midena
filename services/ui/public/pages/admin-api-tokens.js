// API tokens on the Administration page: issuing a token for one account,
// showing it once, listing tokens and revoking them (mosp's
// /v1/admin/api-tokens routes).
(() => {
  "use strict";

  function cell(text) {
    const td = document.createElement("td");
    td.textContent = text;
    return td;
  }

  function mountApiTokens() {
    const tab = document.getElementById("tab-api-tokens");
    const form = document.getElementById("apiTokenForm");
    const accounts = document.getElementById("api-token-user");
    const list = document.getElementById("api-token-list");
    const status = document.getElementById("api-token-status");
    const issued = document.getElementById("api-token-issued");
    const value = document.getElementById("api-token-value");
    const copy = document.getElementById("api-token-copy");
    const off = document.getElementById("api-token-off");
    if (
      !tab ||
      !form ||
      !accounts ||
      !list ||
      !status ||
      !issued ||
      !value ||
      !off
    ) {
      return;
    }

    let loaded = false;

    function show(message, kind) {
      status.hidden = false;
      status.className = `small alert alert-${kind} py-2 mb-2`;
      status.textContent = message;
    }

    function renderAccounts(users) {
      const chosen = accounts.value;
      accounts.replaceChildren();
      for (const user of users) {
        if (!user.is_active) continue;
        const option = document.createElement("option");
        option.value = user.id;
        option.textContent = user.username;
        accounts.append(option);
      }
      if (chosen) accounts.value = chosen;
    }

    function renderTokens(items) {
      list.replaceChildren();
      if (!items.length) {
        const empty = document.createElement("p");
        empty.className = "text-muted small mb-0";
        empty.textContent = "No API tokens have been issued.";
        list.append(empty);
        return;
      }
      const wrap = document.createElement("div");
      wrap.className = "table-responsive";
      const table = document.createElement("table");
      table.className = "table table-sm align-middle";
      const head = document.createElement("thead");
      const headRow = document.createElement("tr");
      for (const label of [
        "Name",
        "Account",
        "Ends in",
        "Issued",
        "Expires",
        "Last used",
        "Status",
        "",
      ]) {
        const th = document.createElement("th");
        th.scope = "col";
        th.textContent = label;
        headRow.append(th);
      }
      head.append(headRow);
      const body = document.createElement("tbody");
      for (const item of items) {
        const row = document.createElement("tr");
        row.dataset.tokenId = item.id;
        const issuedBy = item.created_by ? ` by ${item.created_by}` : "";
        row.append(
          cell(item.name),
          cell(item.username || "—"),
          cell(`…${item.hint}`),
          cell(`${MIDENA.formatTimestamp(item.created_at)}${issuedBy}`),
          cell(MIDENA.formatTimestamp(item.expires_at, "Never")),
          cell(MIDENA.formatTimestamp(item.last_used_at, "Never")),
          cell(item.status),
        );
        const actions = document.createElement("td");
        actions.className = "text-end";
        if (item.status === "active") {
          const revoke = document.createElement("button");
          revoke.type = "button";
          revoke.className = "btn btn-sm btn-outline-danger";
          revoke.textContent = "Revoke";
          revoke.addEventListener("click", () => revokeToken(item));
          actions.append(revoke);
        }
        row.append(actions);
        body.append(row);
      }
      table.append(head, body);
      wrap.append(table);
      list.append(wrap);
    }

    async function load() {
      try {
        const [users, tokens] = await Promise.all([
          MIDENA.api("/api/v1/admin/users"),
          MIDENA.api("/api/v1/admin/api-tokens"),
        ]);
        renderAccounts(users.items || []);
        renderTokens(tokens.items || []);
        // Turned off, the deployment issues and accepts no token.
        off.hidden = tokens.enabled;
        for (const control of form.elements) control.disabled = !tokens.enabled;
        loaded = true;
      } catch (error) {
        show(`Could not load API tokens: ${error?.message || error}`, "danger");
      }
    }

    async function revokeToken(item) {
      if (
        !window.confirm(
          `Revoke the API token "${item.name}"? Anything using it stops reading at once.`,
        )
      ) {
        return;
      }
      try {
        await MIDENA.api(
          `/api/v1/admin/api-tokens/${encodeURIComponent(item.id)}/revoke`,
          { method: "POST" },
        );
        show(`Revoked "${item.name}".`, "success");
      } catch (error) {
        show(`Could not revoke: ${error?.message || error}`, "danger");
      }
      await load();
    }

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const data = new FormData(form);
      const days = String(data.get("expires_in_days") || "");
      issued.hidden = true;
      value.value = "";
      try {
        const result = await MIDENA.api("/api/v1/admin/api-tokens", {
          method: "POST",
          body: {
            name: String(data.get("name") || "").trim(),
            user_id: String(data.get("user_id") || ""),
            expires_in_days: days ? Number(days) : null,
          },
        });
        value.value = result.token;
        issued.hidden = false;
        status.hidden = true;
        form.reset();
        await load();
        value.focus();
        value.select();
      } catch (error) {
        show(`Could not issue a token: ${error?.message || error}`, "danger");
      }
    });

    copy?.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(value.value);
        show("Token copied.", "success");
      } catch (_) {
        value.select();
        show("Select the token and copy it.", "info");
      }
    });

    tab.addEventListener("shown.bs.tab", () => {
      if (!loaded) load();
    });
    if (window.location.hash.toLowerCase() === "#api-tokens") load();
  }

  async function start() {
    await MIDENA.ensureInitialized();
    if (!MIDENA.isAdmin()) return;
    mountApiTokens();
  }

  if (typeof window !== "undefined" && window.MIDENA) {
    start().catch((error) => console.error(error));
  }
})();
