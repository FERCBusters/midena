(() => {
  const state = { me: null, csrfToken: null };

  function getCookie(name) {
    const encoded = `${name}=`;
    const parts = document.cookie ? document.cookie.split(';') : [];
    for (const part of parts) {
      const trimmed = part.trim();
      if (trimmed.startsWith(encoded)) return decodeURIComponent(trimmed.slice(encoded.length));
    }
    return null;
  }

  function escapeHtml(value) {
    return String(value ?? '')
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;')
      .replaceAll("'", '&#39;');
  }

  async function parseError(response) {
    let message = `HTTP ${response.status}`;
    try {
      const data = await response.clone().json();
      if (typeof data?.detail === 'string') message = data.detail;
      else if (Array.isArray(data?.detail)) message = data.detail.map((d) => d?.msg || JSON.stringify(d)).join('; ');
      else if (data?.message) message = String(data.message);
    } catch (_) {
      try { const text = await response.clone().text(); if (text) message = text; } catch (__) {}
    }
    const err = new Error(message); err.status = response.status; throw err;
  }

  async function apiRequest(path, options = {}) {
    const method = (options.method || 'GET').toUpperCase();
    const headers = { ...(options.headers || {}) };
    if (!headers.Accept) headers.Accept = 'application/json';
    const hasBody = options.body !== undefined && options.body !== null;
    if (hasBody && !(options.body instanceof FormData) && !headers['Content-Type']) headers['Content-Type'] = 'application/json';
    const cookieCsrf = getCookie(window.mospUiConfig?.csrf?.cookieName || 'midena_csrf');
    const csrfToken = cookieCsrf || state.csrfToken;
    if (csrfToken) state.csrfToken = csrfToken;
    if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(method) && csrfToken) headers['X-CSRF-Token'] = csrfToken;
    const response = await fetch(path, {
      method,
      headers,
      credentials: 'same-origin',
      body: hasBody && headers['Content-Type'] === 'application/json' ? JSON.stringify(options.body) : options.body,
    });
    if (!response.ok && !options.allowErrorStatuses?.includes(response.status)) await parseError(response);
    const responseType = options.responseType || 'json';
    if (responseType === 'raw') return response;
    if (responseType === 'blob') return response.blob();
    if (responseType === 'text') return response.text();
    const text = await response.text();
    if (!text) return null;
    try { return JSON.parse(text); } catch (_) { return text; }
  }

  function ensureToastContainer() {
    let container = document.getElementById('toastContainer');
    if (container) return container;
    container = document.createElement('div');
    container.id = 'toastContainer';
    container.className = 'toast-container position-fixed bottom-0 end-0 p-3';
    container.style.zIndex = '1080';
    document.body.appendChild(container);
    return container;
  }

  function toast(message, level = 'info', opts = {}) {
    const txt = String(message ?? '').trim();
    if (!txt) return;
    const kind = ({ success: 'success', warn: 'warning', warning: 'warning', error: 'danger', danger: 'danger', info: 'info' })[String(level).toLowerCase()] || 'secondary';
    const delay = Number.isFinite(opts?.delay) ? opts.delay : (kind === 'danger' ? 5200 : 3500);
    const toastEl = document.createElement('div');
    toastEl.className = `toast align-items-center text-bg-${kind} border-0`;
    toastEl.setAttribute('role', 'alert');
    toastEl.setAttribute('aria-live', 'assertive');
    toastEl.setAttribute('aria-atomic', 'true');
    toastEl.innerHTML = `<div class="d-flex"><div class="toast-body">${escapeHtml(txt)}</div><button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button></div>`;
    ensureToastContainer().appendChild(toastEl);
    try {
      const inst = bootstrap.Toast.getOrCreateInstance(toastEl, { delay, autohide: true });
      toastEl.addEventListener('hidden.bs.toast', () => toastEl.remove(), { once: true });
      inst.show();
    } catch (_) {
      toastEl.classList.add('show');
      window.setTimeout(() => toastEl.remove(), delay);
    }
  }

  async function initAuth(opts = {}) {
    try {
      const me = await apiRequest('/v1/me', { allowErrorStatuses: [401] });
      if (!me || me.status === 401 || me.detail) throw new Error('Not authenticated');
      state.me = window.mospUiConfig?.mapMe ? window.mospUiConfig.mapMe(me) : me;
      state.csrfToken = me.csrf_token || getCookie('midena_csrf');
      document.querySelectorAll('[data-current-user]').forEach((el) => { el.textContent = state.me.username || ''; });
      return state.me;
    } catch (err) {
      if (opts.redirectOnFail) {
        const here = `${window.location.pathname}${window.location.search}${window.location.hash}`;
        window.location.href = `/login.html?next=${encodeURIComponent(here)}`;
      }
      throw err;
    }
  }

  async function requireAuth() { return initAuth({ redirectOnFail: true }); }

  function formatDate(value) {
    if (!value) return '—';
    const d = new Date(value);
    return Number.isNaN(d.getTime()) ? String(value) : d.toLocaleString();
  }

  function downloadText(filename, content, type = 'text/plain') {
    const blob = new Blob([content], { type });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = filename; document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  window.apiRequest = apiRequest;
  window.MIDENA = { state, api: apiRequest, initAuth, requireAuth, toast, escapeHtml, formatDate, downloadText };
})();
