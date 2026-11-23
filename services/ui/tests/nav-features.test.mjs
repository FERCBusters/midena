// Navbar links follow the account's role from the first render.
import test from "node:test";
import assert from "node:assert/strict";
import { loadPage } from "./support/load-page.mjs";

async function config(t) {
  const page = await loadPage("index.html", "mosp-ui-config.js");
  t.after(page.close);
  return page.window.mospUiConfig;
}

const allowed = (link, me) =>
  (link.requireAny || []).some((flag) => me[flag]) &&
  (link.requireAll || []).every((flag) => me[flag]);

const keys = (cfg, me) =>
  // Spread into this realm: the page's arrays have their own prototype.
  [...cfg.links].filter((link) => allowed(link, me)).map((link) => link.key);

test("administrators see every link", async (t) => {
  const cfg = await config(t);
  const me = cfg.mapMe({ username: "admin", effective_role: "admin" });
  assert.deepEqual(keys(cfg, me), ["diagrams", "folders", "tags", "admin"]);
});

test("folder managers see folders; other accounts see diagrams only", async (t) => {
  const cfg = await config(t);
  const managing = cfg.mapMe({
    username: "manager",
    effective_role: "normal",
    permissions: ["diagram.read_private", "folder.manage"],
  });
  assert.deepEqual(keys(cfg, managing), ["diagrams", "folders"]);
  for (const permissions of [[], ["diagram.write", "diagram.comment"], null]) {
    const me = cfg.mapMe({
      username: "member",
      effective_role: "normal",
      permissions,
    });
    assert.deepEqual(keys(cfg, me), ["diagrams"], String(permissions));
  }
  // The flags the pages read follow the permissions too.
  const writer = cfg.mapMe({
    effective_role: "normal",
    permissions: ["diagram.write"],
  });
  assert.deepEqual(
    [writer.can_edit_diagrams, writer.can_comment_diagrams, writer.is_admin],
    [true, true, false],
  );
  const commenter = cfg.mapMe({
    role: "normal",
    permissions: ["diagram.comment"],
  });
  assert.deepEqual(
    [
      commenter.can_edit_diagrams,
      commenter.can_comment_diagrams,
      commenter.role,
    ],
    [false, true, "normal"],
  );
  assert.equal(cfg.mapMe({}).role, "normal");
});

test("the navigation stays expanded at laptop widths, as in KEEN", async (t) => {
  const cfg = await config(t);
  assert.equal(cfg.nav.expandClass, "navbar-expand-lg");
  assert.equal(cfg.framework.enabled, false);
});
