// The public diagram page is the one page anyone can open without a session,
// so it is exercised end to end with hostile stored data: the request carries
// no credentials, and nothing the diagram holds becomes markup or script.
import test from "node:test";
import assert from "node:assert/strict";
import { loadPage } from "./support/load-page.mjs";

const ID = "8b0c3f8e-5d2a-4c61-9a57-2f0b7e3d1c44";
const TOKEN = "tok_abcdefghijklmnopqrstuvwxyz012345";

const HOSTILE_SVG =
  '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" onload="window.pwned=1">' +
  "<script>window.pwned=2</script>" +
  '<foreignObject><div xmlns="http://www.w3.org/1999/xhtml"><img src="x" onerror="window.pwned=3"/></div></foreignObject>' +
  '<a xlink:href="javascript:window.pwned=4"><text>link</text></a>' +
  "<style>.n{background:url(https://evil.example/s)}</style>" +
  "<style>.ok{marker-end:url(#arrow)}</style>" +
  '<g id="Task_1" class="node"><rect width="10" height="10" style="fill:url(https://evil.example/x)"/>' +
  '<rect width="5" height="5" fill="url( \'https://evil.example/f\')" marker-end="url(#arrow)"/><text>Task</text></g>' +
  "</svg>";

async function openPublic(t, diagram, { status = 200 } = {}) {
  const credentials = [];
  const page = await loadPage(
    "public-diagram.html",
    ["rendered-diagram-interactions.js", "pages/public-diagram.js"],
    {
      url: `https://midena.example/public/diagrams/${ID}/${TOKEN}.html`,
      api: async () => [status, diagram],
      setup: (window) => {
        const answer = window.fetch;
        window.fetch = (input, init = {}) => {
          credentials.push(init.credentials);
          return answer(input, init);
        };
      },
    },
  );
  t.after(page.close);
  for (let i = 0; i < 10; i += 1) await page.settle();
  return { ...page, credentials };
}

test("the public diagram is fetched without credentials by its id and token", async (t) => {
  const { requests, credentials, document } = await openPublic(
    t,
    {},
    { status: 404 },
  );
  assert.deepEqual(requests, [
    ["GET", `/v1/public/diagrams/${ID}/${TOKEN}`, undefined],
  ]);
  assert.deepEqual(credentials, ["omit"]);
  assert.equal(
    document.getElementById("title").textContent,
    "Diagram not found or not public",
  );
});

test("stored public data never becomes markup or script", async (t) => {
  const hostile = '<img src=x onerror="window.pwned=5">';
  const { window, document } = await openPublic(t, {
    name: hostile,
    diagram_type: "sequence",
    svg_xml: HOSTILE_SVG,
    tags: [hostile, '"><script>window.pwned=6</script>'],
    header_text: hostile,
    footer_text: hostile,
    entity_links: [
      {
        element_id: "Task_1",
        url: "javascript:window.pwned=7",
        label: hostile,
      },
    ],
  });
  assert.equal(window.pwned, undefined);
  for (const id of ["title", "diagramHeader", "diagramFooter"]) {
    assert.equal(document.getElementById(id).textContent, hostile);
    assert.equal(document.getElementById(id).children.length, 0);
  }
  const tags = document.getElementById("publicDiagramTags");
  assert.equal(tags.querySelectorAll("img, script").length, 0);
  for (const link of tags.querySelectorAll("a")) {
    assert.match(link.getAttribute("href"), /^\/index\.html\?tag=/);
  }
  const canvas = document.getElementById("canvas");
  assert.ok(canvas.querySelector("svg"), "the stored SVG is shown");
  // Same-document references stay; a style sheet that loads nothing stays.
  assert.equal(canvas.querySelectorAll("[marker-end='url(#arrow)']").length, 1);
  assert.deepEqual(
    [...canvas.querySelectorAll("style")].map((node) => node.textContent),
    [".ok{marker-end:url(#arrow)}"],
  );
  assert.equal(canvas.querySelectorAll("script, foreignObject, img").length, 0);
  for (const element of canvas.querySelectorAll("*")) {
    for (const attribute of element.attributes) {
      assert.doesNotMatch(attribute.name, /^on/i);
      assert.doesNotMatch(attribute.value, /javascript:|evil\.example/i);
    }
  }
});
