// MOSP UI configuration for MIDENA.
(function () {
  function mapMe(me) {
    const role = String(me?.effective_role || me?.role || '').toLowerCase() || 'viewer';
    const isAdmin = role === 'admin';
    const canEdit = isAdmin || ['maintainer', 'contributor', 'architect'].includes(role);
    const canComment = isAdmin || canEdit || ['engineer', 'product_owner'].includes(role);
    const canManageFolders = isAdmin || ['maintainer', 'architect', 'diagram_admin'].includes(role);
    return {
      ...me,
      user: String(me?.user || me?.username || '').trim(),
      role,
      is_admin: isAdmin,
      can_edit_diagrams: canEdit,
      can_comment_diagrams: canComment,
      can_manage_folders: canManageFolders,
    };
  }

  window.mospUiConfig = {
    appId: 'midena',
    appName: 'MIDENA',
    brandIcon: '/favicon.svg',
    brandHref: '/index.html',
    auth: {
      meEndpoint: '/v1/me',
      loginUrl: '/login.html',
      logoutEndpoint: '/v1/auth/logout',
      logoutRedirect: '/login.html',
      accountHref: '/account.html',
    },
    csrf: { cookieName: 'midena_csrf' },
    links: [
      { key: 'diagrams', label: 'Diagrams', href: '/index.html' },
      { key: 'folders', label: 'Folders', href: '/folders.html', requireAny: ['can_manage_folders', 'is_admin'] },
      { key: 'tags', label: 'Tags', href: '/tags.html', requireAny: ['is_admin'] },
      { key: 'admin', label: 'Admin', href: '/admin.html', requireAny: ['is_admin'] },
    ],
    framework: { enabled: false },
    search: { enabled: false },
    shortcuts: { enabled: true, endpoint: '/v1/me/shortcuts', label: 'Shortcuts' },
    bell: { enabled: false },
    nav: { extraHtml: '' },
    storage: { themeKey: 'mosp-ui:midena:theme' },
    uiPreferences: { endpoint: '/v1/me/preferences', method: 'PUT', stickyField: 'sticky_enabled' },
    mapMe,
  };
})();
