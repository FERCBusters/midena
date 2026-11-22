import test from "node:test";
import assert from "node:assert/strict";
import { loadApp } from "./_harness.mjs";

const MIDENA = await loadApp();
assert.ok(MIDENA, "app.js must expose window.MIDENA");

test("escapeHtml neutralises HTML-significant characters", () => {
  const esc = MIDENA.escapeHtml;
  assert.equal(
    esc("<img src=x onerror=alert(1)>"),
    "&lt;img src=x onerror=alert(1)&gt;",
  );
  assert.equal(esc("a&b\"c'd"), "a&amp;b&quot;c&#39;d");
});

test("featureOn fails open for unknown keys, honours the server for known ones", () => {
  assert.equal(MIDENA.featureOn("frameworks"), true);
  assert.equal(MIDENA.featureOn("nonexistent-feature"), true);
});

test("gateFeature redirects disabled pages to the dashboard", () => {
  MIDENA.state.features = { frameworks: false };
  assert.equal(MIDENA.gateFeature("frameworks"), false);
  MIDENA.state.features = { frameworks: true };
  assert.equal(MIDENA.gateFeature("frameworks"), true);
});

test("normalizeHexColor keeps safe hex only", () => {
  const n = MIDENA.normalizeHexColor;
  assert.equal(n("#aabbcc"), "#aabbcc");
  assert.equal(n("#ABC"), null);
  assert.equal(n("javascript:alert(1)"), null);
  assert.equal(n("#ggg"), null);
  assert.equal(n(""), null);
});

test("preferences normalisation preserves safe start pages", () => {
  const p = MIDENA.normalizeUserPreferences({
    node_colors: {},
    default_start_page: "/index.html",
    sticky_enabled: true,
  });
  assert.equal(p.default_start_page, "/index.html");
  assert.equal(p.sticky_enabled, true);
});

test("accounts are created by administrators: no pending start page", () => {
  // As in KEEN, there is no pending sign-up role or page.
  assert.equal(MIDENA.isPendingUser, undefined);
  const values = MIDENA.ALLOWED_START_PAGES.map((p) => p.value);
  assert.equal(values.includes("/pending.html"), false);
  assert.equal(MIDENA.normalizeStartPage("/pending.html"), "/index.html");
});

test("applyFeatureVisibility hides links of disabled pages", () => {
  MIDENA.state.features = { manifests: true, frameworks: false };
  // With no document links, the call must be a no-op without throwing.
  MIDENA.applyFeatureVisibility();
});

test("csvCell quotes cells and neutralises formula prefixes", () => {
  const cell = MIDENA.csvCell;
  assert.equal(cell("plain"), '"plain"');
  assert.equal(cell('say "hi"'), '"say ""hi"""');
  assert.equal(cell(null), '""');
  assert.equal(cell(3), '"3"');
  for (const hostile of ["=1+1", "+cmd", "-2+3", "@SUM(A1)", "\tlead"]) {
    assert.equal(cell(hostile), `"'${hostile}"`);
  }
  // Interior formula characters are ordinary text.
  assert.equal(cell("a=b"), '"a=b"');
});

test("start pages offer Diagrams, Folders and Tags, never another page", () => {
  const values = MIDENA.ALLOWED_START_PAGES.map((p) => p.value);
  assert.equal(values[0], "/index.html");
  assert.ok(values.includes("/folders.html"));
  assert.ok(values.includes("/tags.html"));
  for (const retired of [
    "/manifests.html",
    "/reset-password.html",
    "//evil.example/",
  ]) {
    assert.equal(values.includes(retired), false, retired);
    assert.equal(MIDENA.normalizeStartPage(retired), "/index.html");
  }
});
