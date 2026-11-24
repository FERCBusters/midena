(() => {
  const MIDENA = window.MIDENA;
  if (!MIDENA) {
    console.error("MIDENA global not found. Did /app.js load?");
    return;
  }

  const {
    initAuth,
    getUserPreferences,
    saveUserPreferences,
    ALLOWED_START_PAGES,
    toast,
    api,
    safeHref,
  } = MIDENA;

  // Theme palettes come from the shared design system; the server may narrow
  // them per deployment through available_themes on /api/v1/me.
  const THEMES =
    window.mospUi &&
    Array.isArray(window.mospUi.THEMES) &&
    window.mospUi.THEMES.length
      ? window.mospUi.THEMES
      : [{ id: "ink", name: "Ink" }];

  const state = {
    me: null,
    paletteNodes: [],
    prefs: {},
    shortcuts: [],
  };

  const el = {
    profileUser: document.getElementById("profileUser"),
    profileUsername: document.getElementById("profileUsername"),
    profileRole: document.getElementById("profileRole"),
    profileEmail: document.getElementById("profileEmail"),
    ssoEmailStatus: document.getElementById("ssoEmailStatus"),
    ssoEmailList: document.getElementById("ssoEmailList"),
    ssoEmailForm: document.getElementById("ssoEmailForm"),
    ssoEmail: document.getElementById("ssoEmail"),
    ssoIdentityStatus: document.getElementById("ssoIdentityStatus"),
    ssoIdentityList: document.getElementById("ssoIdentityList"),
    prefTheme: document.getElementById("prefTheme"),
    prefSticky: document.getElementById("prefSticky"),
    prefAutoApply: document.getElementById("prefAutoApply"),
    prefDiagramSourceCollapsed: document.getElementById(
      "prefDiagramSourceCollapsed",
    ),
    prefDiagramSidebarCollapsed: document.getElementById(
      "prefDiagramSidebarCollapsed",
    ),
    defaultStartPage: document.getElementById("defaultStartPage"),
    colorRows: document.getElementById("colorRows"),
    shortcutsList: document.getElementById("shortcutsList"),
    shortcutName: document.getElementById("shortcutName"),
    shortcutUrl: document.getElementById("shortcutUrl"),
    addShortcutBtn: document.getElementById("addShortcutBtn"),
    passwordCard: document.getElementById("passwordCard"),
    passwordUnavailableMsg: document.getElementById("passwordUnavailableMsg"),
    mfaCard: document.getElementById("mfaCard"),
    mailCard: document.getElementById("mailCard"),
    mailSummary: document.getElementById("mailSummary"),
    mailList: document.getElementById("mailList"),
    securitySummary: document.getElementById("securitySummary"),
    securityForm: document.getElementById("securityForm"),
    securityPassword: document.getElementById("securityPassword"),
    manageMfaBtn: document.getElementById("manageMfaBtn"),
    mfaMsg: document.getElementById("mfaMsg"),
    changePasswordForm: document.getElementById("changePasswordForm"),
    currentPassword: document.getElementById("currentPassword"),
    newPassword: document.getElementById("newPassword"),
    confirmPassword: document.getElementById("confirmPassword"),
    passwordMsg: document.getElementById("passwordMsg"),
  };

  // Hash navigation: #profile, #preferences,
  // #shortcuts, #password. A tab hidden for this account is never shown.
  function showTabFromHash() {
    const hash = String(window.location.hash || "")
      .replace("#", "")
      .trim()
      .toLowerCase();
    if (!hash) return;
    const btn = document.querySelector(
      `#accountTabs button[data-hash="${CSS.escape(hash)}"]`,
    );
    if (!btn || btn.closest("[hidden]") || !window.bootstrap?.Tab) return;
    try {
      window.bootstrap.Tab.getOrCreateInstance(btn).show();
    } catch {}
  }

  function initAccountTabs() {
    showTabFromHash();

    document
      .querySelectorAll('#accountTabs button[data-bs-toggle="tab"]')
      .forEach((btn) => {
        btn.addEventListener("shown.bs.tab", (e) => {
          const target = e?.target?.getAttribute?.("data-hash");
          if (!target) return;
          try {
            history.replaceState(null, "", `#${target}`);
          } catch {}
        });
      });
  }

  function esc(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }
  // SSO email addresses, as KEEN's account security page manages them.
  async function loadSsoEmails() {
    if (!el.ssoEmailList) return;
    const data = await api("/api/v1/me/sso-emails");
    if (el.ssoEmailForm) el.ssoEmailForm.hidden = !data.smtp_configured;
    if (el.ssoEmailStatus)
      el.ssoEmailStatus.textContent = data.smtp_configured
        ? "Verify each address you want to use for SSO. Adding or removing an address requires a sign-in within the last five minutes."
        : "Your administrator must configure SMTP before you can verify an SSO email address.";
    el.ssoEmailList.replaceChildren();
    for (const address of data.addresses || []) {
      const item = document.createElement("li");
      item.className =
        "d-flex align-items-center justify-content-between gap-3 py-2";
      const label = document.createElement("span");
      label.textContent = address.email + " - verified";
      const button = document.createElement("button");
      button.type = "button";
      button.className = "btn btn-sm btn-outline-danger";
      button.textContent = "Remove";
      button.addEventListener("click", async () => {
        if (
          !window.confirm(
            "Remove this address from future SSO linking? An identity already linked through it keeps signing in until you remove it under Linked sign-in identities.",
          )
        )
          return;
        button.disabled = true;
        try {
          await api("/api/v1/me/sso-emails/remove", {
            method: "POST",
            body: { email: address.email },
          });
          await loadSsoEmails();
        } catch (error) {
          if (el.ssoEmailStatus)
            el.ssoEmailStatus.textContent = error?.message || String(error);
          button.disabled = false;
        }
      });
      item.append(label, button);
      el.ssoEmailList.append(item);
    }
    if (!(data.addresses || []).length) {
      const item = document.createElement("li");
      item.textContent = "No verified SSO email addresses.";
      el.ssoEmailList.append(item);
    }
  }

  // The SSO identities linked to the account, which its holder can remove.
  async function loadSsoIdentities() {
    if (!el.ssoIdentityList) return;
    const data = await api("/api/v1/me/sso-identities");
    const identities = data.identities || [];
    el.ssoIdentityList.replaceChildren();
    if (el.ssoIdentityStatus)
      el.ssoIdentityStatus.textContent = identities.length
        ? "Removing an identity needs a sign-in within the last five minutes."
        : "No sign-in identities are linked.";
    for (const identity of identities) {
      const item = document.createElement("li");
      item.className =
        "d-flex align-items-center justify-content-between gap-3 py-2";
      const label = document.createElement("span");
      const who = identity.email || identity.name || "unnamed identity";
      label.textContent = `${identity.provider}: ${who} - linked ${String(identity.linked_at).slice(0, 10)}`;
      const button = document.createElement("button");
      button.type = "button";
      button.className = "btn btn-sm btn-outline-danger";
      button.textContent = "Remove";
      button.addEventListener("click", async () => {
        if (
          !window.confirm(
            "Remove this identity? It stops signing in to your account, the address it was linked through is removed, and every session ends, this one included.",
          )
        )
          return;
        button.disabled = true;
        try {
          await api("/api/v1/me/sso-identities/remove", {
            method: "POST",
            body: { id: identity.id },
          });
          window.location.assign("/login.html");
        } catch (error) {
          if (el.ssoIdentityStatus)
            el.ssoIdentityStatus.textContent = error?.message || String(error);
          button.disabled = false;
        }
      });
      item.append(label, button);
      el.ssoIdentityList.append(item);
    }
  }

  async function requestSsoEmail(event) {
    event.preventDefault();
    const button = el.ssoEmailForm?.querySelector("button");
    if (button) button.disabled = true;
    try {
      const result = await api("/api/v1/me/sso-emails/request", {
        method: "POST",
        body: { email: el.ssoEmail?.value || "" },
      });
      if (el.ssoEmailStatus)
        el.ssoEmailStatus.textContent = result?.already_verified
          ? "This address is already verified."
          : "Verification email sent. Stay signed into this account and open the link within 30 minutes. Requesting another link replaces this one.";
    } catch (error) {
      if (el.ssoEmailStatus)
        el.ssoEmailStatus.textContent = error?.message || String(error);
    } finally {
      if (button) button.disabled = false;
    }
  }

  function roleOf(me) {
    return me?.effective_role || me?.role || "normal";
  }

  function buildStartPageOptions(me) {
    const role = roleOf(me);
    const opts = [];
    for (const page of ALLOWED_START_PAGES || []) {
      if (page.permission === "public") {
        opts.push(page);
        continue;
      }
      if (page.permission === "admin") {
        if (role === "admin") opts.push(page);
      }
    }
    return opts;
  }

  function getTheme() {
    // The account preference is authoritative; fall back to the shared
    // design system default.
    const saved = String(state.prefs?.theme || "").trim();
    return saved || "ink";
  }

  function applyTheme(id) {
    if (window.mospUi && typeof window.mospUi.applyTheme === "function") {
      // The design system keeps the browser in step for the pre-paint boot.
      window.mospUi.applyTheme(id);
      return;
    }
    const themeId = (id || "").trim() || "ink";
    document.documentElement.dataset.theme = themeId;
    try {
      localStorage.setItem("keen_theme", themeId);
    } catch {}
  }

  function renderThemeSelect(meObj) {
    if (!el.prefTheme) return;
    const avail =
      meObj?.available_themes && Array.isArray(meObj.available_themes)
        ? meObj.available_themes
        : THEMES;
    el.prefTheme.innerHTML = avail
      .map(
        (t) =>
          `<option value="${esc(String(t.id))}">${esc(String(t.name))}</option>`,
      )
      .join("");
    el.prefTheme.value = getTheme();
  }

  function renderStartPageSelect() {
    if (!el.defaultStartPage) return;
    const options = buildStartPageOptions(state.me);
    el.defaultStartPage.innerHTML = options
      .map((p) => `<option value="${esc(p.value)}">${esc(p.label)}</option>`)
      .join("");

    const current = state.prefs?.default_start_page || "";
    if (current && options.some((o) => o.value === current)) {
      el.defaultStartPage.value = current;
    } else {
      el.defaultStartPage.value = options[0]?.value || "/index.html";
    }
  }

  async function savePreferences() {
    const payload = {
      ...state.prefs,
      default_start_page:
        el.defaultStartPage?.value ||
        state.prefs?.default_start_page ||
        "/index.html",
    };
    const saved = await saveUserPreferences(payload);
    state.prefs = saved;
    toast("Preferences saved.");
  }

  async function loadShortcuts() {
    const data = await api("/api/v1/me/shortcuts");
    state.shortcuts = Array.isArray(data?.items)
      ? data.items
      : Array.isArray(data)
        ? data
        : [];
  }

  function renderShortcuts() {
    if (!el.shortcutsList) return;
    if (!state.shortcuts.length) {
      el.shortcutsList.innerHTML =
        '<div class="text-muted">No shortcuts saved yet.</div>';
      return;
    }
    el.shortcutsList.innerHTML = `
      <div class="list-group">
        ${state.shortcuts
          .slice()
          .sort((a, b) =>
            String(a.name || "").localeCompare(String(b.name || "")),
          )
          .map((s) => {
            const href = s.url || s.href || "#";
            const safe = safeHref(href);
            const isExternal = /^https?:\/\//i.test(safe);
            const linkHtml = safe
              ? `<a class="text-decoration-none font-monospace small text-break" href="${esc(safe)}"${isExternal ? ' target="_blank" rel="noopener noreferrer"' : ""}>${esc(href)}</a>`
              : `<span class="text-muted font-monospace small text-break">${esc(href)}</span>`;
            return `
              <div class="list-group-item d-flex flex-wrap gap-2 align-items-center justify-content-between">
                <div class="me-2">
                  <div class="fw-semibold">${esc(s.name || "Shortcut")}</div>
                  <div class="small">${linkHtml}</div>
                </div>
                <button type="button" class="btn btn-sm btn-outline-danger" data-del="${esc(s.id)}"><i class="bi bi-trash"></i> Remove</button>
              </div>
            `;
          })
          .join("")}
      </div>
    `;

    el.shortcutsList.querySelectorAll("button[data-del]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const id = btn.getAttribute("data-del");
        if (!id) return;
        if (!confirm("Remove this shortcut?")) return;
        try {
          await api(`/api/v1/me/shortcuts/${encodeURIComponent(id)}`, {
            method: "DELETE",
          });
          await loadShortcuts();
          renderShortcuts();
          toast("Shortcut removed.", "success");
        } catch (err) {
          toast(err?.message || "Failed to remove shortcut", "error");
        }
      });
    });
  }

  async function addShortcut() {
    const name = (el.shortcutName?.value || "").trim();
    const url = (el.shortcutUrl?.value || "").trim();
    if (!name || !url) {
      toast("Please provide both a name and a URL.", "error");
      return;
    }
    if (!safeHref(url)) {
      toast(
        "Invalid or unsafe URL. Use an http(s) URL or a same-site path (starting with /).",
        "error",
      );
      return;
    }
    await api("/api/v1/me/shortcuts", { method: "POST", body: { name, url } });
    el.shortcutName.value = "";
    el.shortcutUrl.value = "";
    await loadShortcuts();
    renderShortcuts();
    toast("Shortcut saved.", "success");
  }

  function setPasswordMsg(text, kind = "info") {
    if (!el.passwordMsg) return;
    el.passwordMsg.textContent = text || "";
    el.passwordMsg.className =
      "small mt-2 " + (kind === "error" ? "text-danger" : "text-secondary");
  }

  async function submitChangePassword() {
    const current_password = String(el.currentPassword?.value || "");
    const new_password = String(el.newPassword?.value || "");
    const confirm_password = String(el.confirmPassword?.value || "");

    if (!current_password || !new_password) {
      setPasswordMsg("Please fill in all fields.", "error");
      return;
    }
    if (new_password.length < 8) {
      setPasswordMsg("New password must be at least 8 characters.", "error");
      return;
    }
    if (new_password !== confirm_password) {
      setPasswordMsg("Passwords do not match.", "error");
      return;
    }

    await api("/api/v1/me/password", {
      method: "POST",
      body: { current_password, new_password },
    });

    if (el.currentPassword) el.currentPassword.value = "";
    if (el.newPassword) el.newPassword.value = "";
    if (el.confirmPassword) el.confirmPassword.value = "";

    // As in KEEN, the new password ends every session, this one included.
    setPasswordMsg("Password updated. Sign in again to continue.", "info");
    toast("Password updated. Sign in again to continue.", "success");
    window.location.assign("/login.html");
  }

  function setMfaMsg(text, kind = "info") {
    if (!el.mfaMsg) return;
    el.mfaMsg.textContent = text || "";
    el.mfaMsg.className =
      "small mt-2 " + (kind === "error" ? "text-danger" : "text-secondary");
  }

  async function loadMyMail() {
    if (!el.mailList) return;
    try {
      const body = await api("/api/v1/me/notifications");
      if (!body.length) {
        el.mailSummary.textContent =
          "Nothing has been emailed to this account from the current configuration yet.";
        return;
      }
      // No fallback: without the shared escaper nothing is rendered.
      const escapeHtml = window.MIDENA.escapeHtml;
      el.mailSummary.textContent = `${body.length} queued e-mail(s)`;
      el.mailList.innerHTML = body
        .map(
          (
            n,
          ) => `<div class="d-flex justify-content-between border-bottom py-2 small">
          <div>${escapeHtml(n.subject)} <span class="text-secondary">→ ${escapeHtml(n.recipient)}</span></div>
          <div><span class="badge ${n.status === "sent" ? "text-bg-success" : n.status === "failed" ? "text-bg-danger" : "text-bg-secondary"}">${escapeHtml(n.status)}</span></div>
          </div>`,
        )
        .join("");
    } catch (err) {
      el.mailSummary.textContent =
        err?.message || "Could not load e-mail history.";
    }
  }

  async function loadMfaStatus() {
    if (!el.securitySummary) return;
    try {
      const state2 = await api("/api/v1/me/mfa");
      if (!state2.local_enabled) {
        el.securitySummary.textContent =
          "Password sign-in is disabled. Manage multi-factor authentication with your sign-in provider.";
        if (el.securityForm) el.securityForm.classList.add("d-none");
        return;
      }
      el.securitySummary.textContent = state2.enabled
        ? `Two-factor authentication is enabled. ${state2.totp ? "Authenticator app; " : ""}${state2.credentials.length} security keys/passkeys; ${state2.recovery_codes_remaining} recovery codes remaining.`
        : "Two-factor authentication is not configured for password sign-in.";
      if (state2.required) {
        el.securitySummary.textContent +=
          " Your administrator requires a second factor.";
      }
      setMfaMsg("");
    } catch (err) {
      el.securitySummary.textContent =
        err?.message || "Could not load security settings.";
    }
  }

  async function submitMfaManage() {
    const password = String(el.securityPassword?.value || "");
    if (!password) {
      setMfaMsg("Enter your current password.", "error");
      return;
    }
    if (el.manageMfaBtn) el.manageMfaBtn.disabled = true;
    try {
      await api("/api/v1/auth/mfa/manage/start", {
        method: "POST",
        body: { password },
      });
      if (el.securityPassword) el.securityPassword.value = "";
      window.location.assign("/mfa.html");
    } catch (err) {
      setMfaMsg(err?.message || "Verification failed.", "error");
      if (el.securityPassword) el.securityPassword.value = "";
    } finally {
      if (el.manageMfaBtn) el.manageMfaBtn.disabled = false;
    }
  }

  function wireEvents() {
    el.ssoEmailForm?.addEventListener("submit", (event) => {
      requestSsoEmail(event);
    });

    el.changePasswordForm?.addEventListener("submit", (e) => {
      e.preventDefault();
      submitChangePassword().catch((err) => {
        console.error(err);
        setPasswordMsg(err?.message || "Failed to change password", "error");
        toast(err?.message || "Failed to change password", "error");
      });
    });

    el.securityForm?.addEventListener("submit", (e) => {
      e.preventDefault();
      submitMfaManage().catch((err) => {
        console.error(err);
        setMfaMsg(
          err?.message || "Failed to start account security management",
          "error",
        );
      });
    });

    el.prefTheme?.addEventListener("change", async () => {
      applyTheme(el.prefTheme.value);
      try {
        state.prefs = await saveUserPreferences({ theme: el.prefTheme.value });
        toast("Theme updated.", "success");
      } catch (err) {
        toast(err?.message || "Failed to save theme preference", "error");
      }
    });

    el.defaultStartPage?.addEventListener("change", () => {
      savePreferences().catch((err) =>
        toast(err?.message || "Failed to save preferences", "error"),
      );
    });

    el.prefSticky?.addEventListener("change", async () => {
      try {
        state.prefs = await saveUserPreferences({
          sticky_enabled: el.prefSticky.checked,
        });
        toast("Sticky preference saved.", "success");
      } catch (err) {
        toast(err?.message || "Failed to save sticky preference", "error");
      }
    });

    el.prefAutoApply?.addEventListener("change", async () => {
      try {
        state.prefs = await saveUserPreferences({
          auto_apply_enabled: el.prefAutoApply.checked,
        });
        toast("Auto-apply preference saved.", "success");
      } catch (err) {
        toast(err?.message || "Failed to save auto-apply preference", "error");
      }
    });

    for (const [input, field] of [
      [el.prefDiagramSourceCollapsed, "diagram_source_collapsed_by_default"],
      [el.prefDiagramSidebarCollapsed, "diagram_sidebar_collapsed_by_default"],
    ]) {
      input?.addEventListener("change", async () => {
        try {
          state.prefs = await saveUserPreferences({ [field]: input.checked });
          toast("Diagram layout preference saved.", "success");
        } catch (err) {
          toast(err?.message || "Failed to save preference", "error");
        }
      });
    }

    el.addShortcutBtn?.addEventListener("click", () => {
      addShortcut().catch((err) =>
        toast(err?.message || "Failed to add shortcut", "error"),
      );
    });

    el.shortcutUrl?.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        addShortcut().catch((err) =>
          toast(err?.message || "Failed to add shortcut", "error"),
        );
      }
    });
  }

  async function init() {
    initAccountTabs();
    state.me = await initAuth({ redirectOnFail: true });
    if (!state.me) return;

    const role = roleOf(state.me);
    if (el.profileUser) el.profileUser.textContent = state.me.username || "";
    if (el.profileUsername)
      el.profileUsername.textContent = state.me.username || "";
    if (el.profileRole) el.profileRole.textContent = role;
    if (el.profileEmail)
      el.profileEmail.textContent = state.me.email || "Not set";

    // Password change is only available for local-auth deployments when OIDC is disabled.
    const canChangePassword =
      Boolean(state.me?.password_features_enabled) &&
      String(state.me?.auth_method || "local") === "local";
    if (el.passwordCard) {
      if (canChangePassword) {
        el.passwordCard.classList.remove("d-none");
      } else {
        el.passwordCard.classList.add("d-none");
      }
    }
    if (el.passwordUnavailableMsg) {
      el.passwordUnavailableMsg.textContent = canChangePassword
        ? ""
        : "Password changes are only available for local accounts when external single sign-on is disabled.";
    }
    if (el.mfaCard) {
      if (canChangePassword) {
        el.mfaCard.classList.remove("d-none");
        // The card's summary reads the account's second-factor state.
        await loadMfaStatus();
      } else {
        el.mfaCard.classList.add("d-none");
      }
    }
    if (el.mailCard) {
      if (canChangePassword) {
        el.mailCard.classList.remove("d-none");
        await loadMyMail();
      } else {
        el.mailCard.classList.add("d-none");
      }
    }

    state.prefs = getUserPreferences() || {};

    if (el.prefSticky)
      el.prefSticky.checked = state.prefs?.sticky_enabled !== false;
    if (el.prefAutoApply)
      el.prefAutoApply.checked = state.prefs?.auto_apply_enabled !== false;
    if (el.prefDiagramSourceCollapsed)
      el.prefDiagramSourceCollapsed.checked =
        state.prefs?.diagram_source_collapsed_by_default !== false;
    if (el.prefDiagramSidebarCollapsed)
      el.prefDiagramSidebarCollapsed.checked =
        state.prefs?.diagram_sidebar_collapsed_by_default !== false;

    renderThemeSelect(state.me);
    applyTheme(getTheme());
    renderStartPageSelect();

    wireEvents();

    await loadSsoEmails().catch((error) => {
      if (el.ssoEmailStatus)
        el.ssoEmailStatus.textContent = error?.message || String(error);
    });
    await loadSsoIdentities().catch((error) => {
      if (el.ssoIdentityStatus)
        el.ssoIdentityStatus.textContent = error?.message || String(error);
    });

    await loadShortcuts();
    renderShortcuts();
  }

  document.addEventListener("DOMContentLoaded", () => {
    init().catch((err) => {
      console.error(err);
      toast(err?.message || "Failed to load account page", "error");
    });
  });
})();
