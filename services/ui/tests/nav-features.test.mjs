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

test("folder managers see folders; viewers see diagrams only", async (t) => {
  const cfg = await config(t);
  for (const role of ["maintainer", "architect", "diagram_admin"]) {
    const me = cfg.mapMe({ username: role, effective_role: role });
    assert.deepEqual(keys(cfg, me), ["diagrams", "folders"], role);
  }
  for (const role of ["viewer", "engineer", "contributor", "product_owner"]) {
    const me = cfg.mapMe({ username: role, effective_role: role });
    assert.deepEqual(keys(cfg, me), ["diagrams"], role);
  }
});

test("the navigation stays expanded at laptop widths, as in KEEN", async (t) => {
  const cfg = await config(t);
  assert.equal(cfg.nav.expandClass, "navbar-expand-lg");
  assert.equal(cfg.framework.enabled, false);
});
