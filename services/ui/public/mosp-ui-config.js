// MOSP UI configuration for MIDENA.
(function () {
  function mapMe(me) {
    const role =
      String(me?.effective_role || me?.role || "").toLowerCase() || "normal";
    const isAdmin = role === "admin";
    // What an ordinary account may do comes from its permissions (the
    // server's own checks decide; these only choose which links to show).
    const permissions = new Set(
      Array.isArray(me?.permissions) ? me.permissions : [],
    );
    const canEdit = isAdmin || permissions.has("diagram.write");
    const canComment = canEdit || permissions.has("diagram.comment");
    const canManageFolders = isAdmin || permissions.has("folder.manage");
    return {
      ...me,
      user: String(me?.user || me?.username || "").trim(),
      role,
      is_admin: isAdmin,
      can_edit_diagrams: canEdit,
      can_comment_diagrams: canComment,
      can_manage_folders: canManageFolders,
    };
  }

  window.mospUiConfig = {
    appId: "midena",
    appName: "MIDENA",
    brandIcon: "/favicon.svg",
    brandHref: "/index.html",
    auth: {
      meEndpoint: "/api/v1/me",
      loginUrl: "/login.html",
      logoutEndpoint: "/api/v1/auth/logout",
      logoutRedirect: "/login.html",
      accountHref: "/account.html",
    },
    csrf: { cookieName: "midena_csrf" },
    links: [
      {
        key: "diagrams",
        label: "Diagrams",
        href: "/index.html",
        requireAny: ["user"],
      },
      {
        key: "folders",
        label: "Folders",
        href: "/folders.html",
        requireAny: ["can_manage_folders", "is_admin"],
      },
      {
        key: "tags",
        label: "Tags",
        href: "/tags.html",
        requireAny: ["is_admin"],
      },
      {
        key: "admin",
        label: "Admin",
        href: "/admin.html",
        requireAny: ["is_admin"],
      },
    ],
    framework: { enabled: false },
    search: { enabled: false },
    shortcuts: {
      enabled: true,
      endpoint: "/api/v1/me/shortcuts",
      label: "Shortcuts",
    },
    bell: { enabled: false },
    // As in KEEN, the bar stays expanded from 992px (the design system's
    // default collapses it below 1400px, every laptop at 100% zoom).
    nav: { extraHtml: "", expandClass: "navbar-expand-lg" },
    // The design system's default key, so the pre-paint theme-boot reads the
    // same value on pages that load without this config (sign-in).
    storage: { themeKey: "keen_theme" },
    uiPreferences: {
      endpoint: "/api/v1/me/preferences",
      method: "PUT",
      stickyField: "sticky_enabled",
    },
    mapMe,
  };
})();
