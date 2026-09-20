(async () => {
  const { api, requireAuth, toast, escapeHtml } = window.MIDENA;
  const me = await requireAuth();
  const THEMES = [
    { id: 'purple', name: 'Purple' },
    { id: 'ocean', name: 'Ocean' },
    { id: 'forest', name: 'Forest' },
    { id: 'sunset', name: 'Sunset' },
    { id: 'rose', name: 'Rose' },
    { id: 'slate', name: 'Slate' },
    { id: 'teal', name: 'Teal' },
  ];
  const DEFAULT_PAGES = [
    { value: '/index.html', label: 'Diagrams' },
    { value: '/folders.html', label: 'Folders' },
    { value: '/account.html', label: 'Account' },
  ];
  let prefs = me.preferences || {};

  const el = {
    username: document.getElementById('username'),
    role: document.getElementById('role'),
    email: document.getElementById('email'),
    authMethod: document.getElementById('authMethod'),
    emailForm: document.getElementById('emailForm'),
    emailInput: document.getElementById('emailInput'),
    prefTheme: document.getElementById('prefTheme'),
    defaultStartPage: document.getElementById('defaultStartPage'),
    prefSticky: document.getElementById('prefSticky'),
    prefAutoApply: document.getElementById('prefAutoApply'),
    prefDiagramSourceCollapsed: document.getElementById('prefDiagramSourceCollapsed'),
    prefDiagramSidebarCollapsed: document.getElementById('prefDiagramSidebarCollapsed'),
    savePreferencesBtn: document.getElementById('savePreferencesBtn'),
    shortcutForm: document.getElementById('shortcutForm'),
    shortcutName: document.getElementById('shortcutName'),
    shortcutUrl: document.getElementById('shortcutUrl'),
    shortcuts: document.getElementById('shortcuts'),
  };

  function themeStorageKey() {
    return window.mospUiConfig?.storage?.themeKey || 'mosp-ui:midena:theme';
  }

  function getTheme() {
    try { return localStorage.getItem(themeStorageKey()) || 'purple'; }
    catch { return 'purple'; }
  }

  function applyTheme(id) {
    const themeId = (id || '').trim() || 'purple';
    document.documentElement.dataset.theme = themeId;
    try { localStorage.setItem(themeStorageKey(), themeId); } catch {}
  }

  function renderProfile() {
    el.username.textContent = me.username || '';
    el.role.textContent = me.effective_role || me.role || '';
    el.email.textContent = me.email || '—';
    el.authMethod.textContent = me.auth_method || 'local';
    el.emailInput.value = me.email || '';
    if (!me.email_editable) el.emailForm.classList.add('d-none');
  }

  function renderThemeSelect() {
    el.prefTheme.innerHTML = THEMES.map((theme) => `<option value="${escapeHtml(theme.id)}">${escapeHtml(theme.name)}</option>`).join('');
    el.prefTheme.value = getTheme();
  }

  function renderStartPageSelect() {
    const allowed = Array.isArray(prefs.allowed_start_pages) && prefs.allowed_start_pages.length
      ? prefs.allowed_start_pages
      : DEFAULT_PAGES;
    const options = allowed.map((page) => ({ value: page.value || page.href || page.url || page, label: page.label || page.name || page.value || page.href || page }));
    el.defaultStartPage.innerHTML = options.map((page) => `<option value="${escapeHtml(page.value)}">${escapeHtml(page.label)}</option>`).join('');
    const current = prefs.default_start_page || options[0]?.value || '/index.html';
    el.defaultStartPage.value = options.some((page) => page.value === current) ? current : (options[0]?.value || '/index.html');
  }

  function renderPreferences() {
    renderThemeSelect();
    renderStartPageSelect();
    el.prefSticky.checked = Boolean(prefs.sticky_enabled);
    el.prefAutoApply.checked = prefs.auto_apply_enabled !== false;
    el.prefDiagramSourceCollapsed.checked = prefs.diagram_source_collapsed_by_default !== false;
    el.prefDiagramSidebarCollapsed.checked = prefs.diagram_sidebar_collapsed_by_default !== false;
  }

  async function savePreferences() {
    applyTheme(el.prefTheme.value);
    prefs = await api('/v1/me/preferences', {
      method: 'PUT',
      body: {
        default_start_page: el.defaultStartPage.value || '/index.html',
        sticky_enabled: el.prefSticky.checked,
        auto_apply_enabled: el.prefAutoApply.checked,
        diagram_source_collapsed_by_default: el.prefDiagramSourceCollapsed.checked,
        diagram_sidebar_collapsed_by_default: el.prefDiagramSidebarCollapsed.checked,
      },
    });
    toast('Preferences saved.', 'success');
  }

  async function loadShortcuts() {
    const data = await api('/v1/me/shortcuts');
    const items = Array.isArray(data) ? data : data.items || [];
    el.shortcuts.innerHTML = items.map((s) => `<div class="d-flex justify-content-between align-items-center border rounded p-2 mb-2"><a href="${escapeHtml(s.url)}">${escapeHtml(s.name)}</a><button class="btn btn-sm btn-outline-danger" type="button" data-del="${s.id}">Delete</button></div>`).join('') || '<div class="text-secondary">No shortcuts.</div>';
    document.querySelectorAll('[data-del]').forEach((btn) => btn.addEventListener('click', async () => {
      try { await api(`/v1/me/shortcuts/${btn.dataset.del}`, { method: 'DELETE' }); await loadShortcuts(); }
      catch (err) { toast(err.message, 'error'); }
    }));
  }

  el.emailForm.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    try {
      await api('/v1/me/profile', { method: 'PUT', body: { email: el.emailInput.value || null } });
      el.email.textContent = el.emailInput.value || '—';
      toast('Profile saved.', 'success');
    } catch (err) { toast(err.message, 'error'); }
  });
  el.prefTheme.addEventListener('change', () => applyTheme(el.prefTheme.value));
  el.savePreferencesBtn.addEventListener('click', () => savePreferences().catch((err) => toast(err.message, 'error')));
  el.shortcutForm.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    try {
      await api('/v1/me/shortcuts', { method: 'POST', body: { name: el.shortcutName.value, url: el.shortcutUrl.value } });
      el.shortcutForm.reset();
      await loadShortcuts();
      toast('Shortcut saved.', 'success');
    } catch (err) { toast(err.message, 'error'); }
  });

  renderProfile();
  renderPreferences();
  await loadShortcuts();
})();
