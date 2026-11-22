// Diagram rendering never turns diagram data into script: stored SVG and
// Mermaid output are inserted as filtered XML, links pass the safe-link rule,
// and Mermaid always runs in its strict mode.
import test from "node:test";
import assert from "node:assert/strict";
import { readFile, readdir } from "node:fs/promises";
import { loadPage } from "./support/load-page.mjs";

const publicRoot = new URL("../public/", import.meta.url);

async function rendered(t) {
  const page = await loadPage(
    "public-diagram.html",
    "rendered-diagram-interactions.js",
  );
  t.after(page.close);
  return page.window.MIDENA_RENDERED;
}

test("stored SVG loses everything that could run or load", async (t) => {
  const R = await rendered(t);
  const node = R.svgNodeFromMarkup(
    `<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" onload="alert(1)">
       <script>alert(2)</script>
       <foreignObject><div xmlns="http://www.w3.org/1999/xhtml"><img src="x" onerror="alert(3)"/></div></foreignObject>
       <a xlink:href="javascript:alert(4)"><text>link</text></a>
       <use href="https://evil.example/x.svg#a"/><use href="#ok"/>
       <animate attributeName="href" to="javascript:alert(5)"/>
       <set attributeName="onmouseover" to="alert(6)"/>
       <image href="https://evil.example/track.png"/>
       <g onclick="alert(7)"><rect width="1"/></g>
     </svg>`,
  );
  const markup = node.outerHTML;
  for (const bad of [
    "onload",
    "onerror",
    "onclick",
    "<script",
    "foreignObject",
    "javascript:",
    "evil.example",
    "<animate",
    "<set",
    "<image",
  ]) {
    assert.equal(markup.includes(bad), false, bad);
  }
  assert.match(markup, /href="#ok"/);
  assert.match(markup, /<rect width="1"/);
});

test("markup that is not an SVG document gives nothing to insert", async (t) => {
  const R = await rendered(t);
  assert.equal(R.svgNodeFromMarkup("<html><script>x</script></html>"), null);
  assert.equal(R.svgNodeFromMarkup("<svg><unclosed></svg"), null);
  assert.equal(R.svgNodeFromMarkup(""), null);
});

test("only web and same-site addresses become links", async (t) => {
  const R = await rendered(t);
  for (const bad of [
    "javascript:alert(1)",
    " JavaScript:alert(1)",
    "data:text/html,<script>",
    "vbscript:x",
    "//evil.example/",
    "/\\evil.example",
    "https://ok.example/\u0000",
    "ftp://files.example/",
    "",
  ]) {
    assert.equal(R.safeLinkUrl(bad), "", JSON.stringify(bad));
  }
  assert.equal(R.safeLinkUrl("/diagram.html?id=1"), "/diagram.html?id=1");
  assert.equal(R.safeLinkUrl("https://ok.example/a"), "https://ok.example/a");
});

async function pageSources() {
  const out = [];
  for (const dir of ["", "pages/"]) {
    for (const name of await readdir(new URL(dir, publicRoot))) {
      if (name.endsWith(".js")) {
        out.push([
          dir + name,
          await readFile(new URL(dir + name, publicRoot), "utf8"),
        ]);
      }
    }
  }
  return out;
}

const LOOSE_MERMAID = /securityLevel\s*:\s*['"](?!strict['"])/;
const SVG_AS_HTML = /\.innerHTML\s*=\s*[^;\n]*(?:svg|\.svg\b)/i;

test("every Mermaid render runs in strict mode", async () => {
  for (const [name, source] of await pageSources()) {
    assert.doesNotMatch(source, LOOSE_MERMAID, name);
  }
  // The check catches the setting MIDENA's pages once used.
  assert.match("securityLevel: 'loose'", LOOSE_MERMAID);
});

test("no page assigns SVG markup as HTML", async () => {
  for (const [name, source] of await pageSources()) {
    assert.doesNotMatch(source, SVG_AS_HTML, name);
  }
  // The check catches the assignments the public pages once made.
  assert.match("canvas.innerHTML = svgXml;", SVG_AS_HTML);
  assert.match("preview.innerHTML = result.svg;", SVG_AS_HTML);
});
