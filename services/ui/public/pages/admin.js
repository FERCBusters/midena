(async () => {
  const { api, requireAuth, toast, escapeHtml, formatDate } = window.MIDENA;
  const me = await requireAuth();
  if (me.effective_role !== 'admin') { window.location.href = '/index.html'; return; }
  const userModal = new bootstrap.Modal(document.getElementById('userModal'));
  const state = { users: [], auditOffset: 0, changeOffset: 0, limit: 50, chrome: null };
  const DEFAULT_THEME = {
    bpmn: { fill_color: '#ffffff', stroke_color: '#344054', text_color: '#1f2937', connector_color: '#667085', border_width: 1.5, connector_width: 1.8, font_family: 'Arial, sans-serif', font_size: 14 },
    flowchart: { fill_color: '#ffffff', stroke_color: '#2563eb', text_color: '#111827', connector_color: '#64748b', border_width: 1.5, connector_width: 1.8, font_family: 'Arial, sans-serif', font_size: 14 },
    sequence: { fill_color: '#ffffff', stroke_color: '#2563eb', text_color: '#111827', connector_color: '#475467', border_width: 1.5, connector_width: 1.8, font_family: 'Arial, sans-serif', font_size: 14 },
  };
  const THEME_TYPES = [
    ['bpmn', 'BPMN symbols'],
    ['flowchart', 'Flowchart boxes'],
    ['sequence', 'WSD participants/messages'],
  ];
  const THEME_FIELDS = [
    ['fill_color', 'Fill colour', 'color'],
    ['stroke_color', 'Border colour', 'color'],
    ['text_color', 'Font colour', 'color'],
    ['connector_color', 'Connector colour', 'color'],
    ['border_width', 'Border thickness', 'number'],
    ['connector_width', 'Connector thickness', 'number'],
    ['font_family', 'Font family', 'text'],
    ['font_size', 'Font size', 'number'],
  ];

  function cloneTheme(value = DEFAULT_THEME) {
    return JSON.parse(JSON.stringify(value));
  }

  function themeInputId(type, field) {
    return `theme_${type}_${field}`;
  }

  function renderThemeForm(theme) {
    const effective = cloneTheme(DEFAULT_THEME);
    Object.entries(theme || {}).forEach(([type, values]) => {
      if (!effective[type] || !values || typeof values !== 'object') return;
      Object.assign(effective[type], values);
    });
    const html = THEME_TYPES.map(([type, title]) => `
      <div class="col-12 col-xl-4">
        <div class="border rounded p-3 h-100 bg-white">
          <div class="fw-semibold mb-2">${escapeHtml(title)}</div>
          <div class="row g-2">
            ${THEME_FIELDS.map(([field, label, inputType]) => {
              const value = effective[type][field];
              const attrs = inputType === 'number' ? ' min="0.5" max="28" step="0.1"' : '';
              return `<div class="col-12 ${inputType === 'color' ? 'col-sm-6' : ''}"><label class="form-label small text-secondary mb-1" for="${themeInputId(type, field)}">${escapeHtml(label)}</label><input class="form-control form-control-sm" id="${themeInputId(type, field)}" data-theme-type="${type}" data-theme-field="${field}" type="${inputType}" value="${escapeHtml(value)}"${attrs}></div>`;
            }).join('')}
          </div>
        </div>
      </div>`).join('');
    document.getElementById('diagramThemeForm').innerHTML = html;
  }

  function readThemeForm() {
    const theme = cloneTheme(DEFAULT_THEME);
    document.querySelectorAll('[data-theme-type][data-theme-field]').forEach((input) => {
      const type = input.dataset.themeType;
      const field = input.dataset.themeField;
      if (!theme[type]) return;
      if (['border_width', 'connector_width', 'font_size'].includes(field)) theme[type][field] = Number(input.value);
      else theme[type][field] = input.value;
    });
    return theme;
  }

  async function loadUsers() {
    const data = await api('/v1/admin/users'); state.users = data.items || [];
    document.getElementById('userRows').innerHTML = state.users.map((u) => `<tr><td>${escapeHtml(u.username)}</td><td>${escapeHtml(u.email || '')}</td><td>${escapeHtml(u.effective_role || u.role)}</td><td>${u.is_active ? 'Yes' : 'No'}</td><td class="text-end"><button class="btn btn-sm btn-outline-secondary" data-edit-user="${u.id}">Edit</button></td></tr>`).join('');
    document.querySelectorAll('[data-edit-user]').forEach((btn) => btn.addEventListener('click', () => editUser(Number(btn.dataset.editUser))));
  }
  function editUser(id) {
    const u = state.users.find((x) => x.id === id); if (!u) return;
    document.getElementById('userId').value = u.id; document.getElementById('username').value = u.username; document.getElementById('username').disabled = true; document.getElementById('email').value = u.email || ''; document.getElementById('role').value = u.role; document.getElementById('active').checked = !!u.is_active; document.getElementById('passwordWrap').classList.add('d-none'); userModal.show();
  }
  document.getElementById('newUserBtn').addEventListener('click', () => { document.getElementById('userForm').reset(); document.getElementById('userId').value = ''; document.getElementById('username').disabled = false; document.getElementById('passwordWrap').classList.remove('d-none'); userModal.show(); });
  document.getElementById('userForm').addEventListener('submit', async (ev) => { ev.preventDefault(); const id = document.getElementById('userId').value; const body = { email: document.getElementById('email').value || null, role: document.getElementById('role').value, is_active: document.getElementById('active').checked }; if (!id) { body.username = document.getElementById('username').value; body.password = document.getElementById('password').value; } try { await api(id ? `/v1/admin/users/${id}` : '/v1/admin/users', { method: id ? 'PATCH' : 'POST', body }); userModal.hide(); await loadUsers(); } catch (err) { toast(err.message, 'error'); } });

  async function loadLocks() {
    const data = await api('/v1/admin/diagram-locks');
    document.getElementById('lockRows').innerHTML = (data.items || []).map((l) => `<tr><td><a href="/diagram.html?id=${encodeURIComponent(l.diagram_uuid)}">${escapeHtml(l.diagram_name)}</a></td><td>${escapeHtml(l.locked_by || '')}</td><td>${formatDate(l.locked_at)}</td><td>${formatDate(l.expires_at)}</td><td class="text-end"><button class="btn btn-sm btn-outline-danger" data-unlock="${l.diagram_id}">Force unlock</button></td></tr>`).join('') || '<tr><td colspan="5" class="text-secondary p-4">No active locks.</td></tr>';
    document.querySelectorAll('[data-unlock]').forEach((btn) => btn.addEventListener('click', async () => { await api(`/v1/admin/diagrams/${btn.dataset.unlock}/unlock`, { method: 'POST' }); toast('Diagram unlocked.', 'success'); await loadLocks(); }));
  }

  async function loadChrome() {
    const data = await api('/v1/admin/diagram-chrome');
    state.chrome = data;
    document.getElementById('globalHeader').value = data.header_text || '';
    document.getElementById('globalFooter').value = data.footer_text || '';
    renderThemeForm(data.theme_settings || DEFAULT_THEME);
  }

  async function saveChrome(extra = {}) {
    state.chrome = await api('/v1/admin/diagram-chrome', {
      method: 'PUT',
      body: {
        header_text: document.getElementById('globalHeader').value,
        footer_text: document.getElementById('globalFooter').value,
        ...extra,
      },
    });
    renderThemeForm(state.chrome.theme_settings || DEFAULT_THEME);
  }

  document.getElementById('saveChromeBtn').addEventListener('click', async () => { try { await saveChrome(); toast('Global header/footer saved.', 'success'); } catch (err) { toast(err.message, 'error'); } });
  document.getElementById('saveThemeBtn').addEventListener('click', async () => { try { await saveChrome({ theme_settings: readThemeForm() }); toast('Global diagram theme saved.', 'success'); } catch (err) { toast(err.message, 'error'); } });
  document.getElementById('resetThemeBtn').addEventListener('click', () => renderThemeForm(DEFAULT_THEME));

  async function loadAudit() { const data = await api(`/v1/admin/audit?limit=${state.limit}&offset=${state.auditOffset}`); document.getElementById('auditRows').innerHTML = (data.items || []).map((r) => `<tr><td>${formatDate(r.ts)}</td><td>${escapeHtml(r.username || '')}</td><td>${escapeHtml(r.method)}</td><td class="path-cell">${escapeHtml(r.path)}${r.query_string ? '?' + escapeHtml(r.query_string) : ''}</td><td>${r.status_code}</td></tr>`).join(''); document.getElementById('auditInfo').textContent = `${data.offset + 1}-${Math.min(data.offset + data.limit, data.total)} of ${data.total}`; }
  async function loadChanges() { const data = await api(`/v1/admin/entity-changelog?limit=${state.limit}&offset=${state.changeOffset}`); document.getElementById('changeRows').innerHTML = (data.items || []).map((r) => `<tr><td>${formatDate(r.changed_at)}</td><td>${escapeHtml(r.entity_type)} #${r.entity_id}<div class="small text-secondary">${escapeHtml(r.entity_title || '')}</div></td><td>${escapeHtml(r.action)}</td><td>${escapeHtml(r.summary)}</td><td>${escapeHtml(r.changed_by_username || '')}</td></tr>`).join(''); document.getElementById('changeInfo').textContent = `${data.offset + 1}-${Math.min(data.offset + data.limit, data.total)} of ${data.total}`; }
  document.getElementById('auditPrev').onclick = () => { state.auditOffset = Math.max(0, state.auditOffset - state.limit); loadAudit(); }; document.getElementById('auditNext').onclick = () => { state.auditOffset += state.limit; loadAudit(); };
  document.getElementById('changePrev').onclick = () => { state.changeOffset = Math.max(0, state.changeOffset - state.limit); loadChanges(); }; document.getElementById('changeNext').onclick = () => { state.changeOffset += state.limit; loadChanges(); };
  try { await Promise.all([loadUsers(), loadLocks(), loadChrome(), loadAudit(), loadChanges()]); } catch (err) { toast(err.message, 'error'); }
})();
