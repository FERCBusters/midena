// What app.js does for every page: the session, API errors, live
// notifications, preferences and feature visibility.
import test from "node:test";
import assert from "node:assert/strict";
import { account, appPage, FEATURES } from "./support/app-page.mjs";

const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

// A browser WebSocket that records each connection and lets the test play
// the server.
function sockets(window, { refuse = false } = {}) {
  const opened = [];
  window.WebSocket = class {
    static CONNECTING = 0;
    static OPEN = 1;
    constructor(url) {
      if (refuse) throw new Error("blocked");
      this.url = url;
      this.readyState = 1;
      this.listeners = {};
      this.closed = 0;
      opened.push(this);
    }
    addEventListener(type, listener) {
      this.listeners[type] = listener;
    }
    close() {
      this.closed += 1;
      if (this.failsToClose) throw new Error("already gone");
    }
    receive(data) {
      this.listeners.message({ data });
    }
    drop() {
      this.readyState = 3;
      this.listeners.error?.();
      this.listeners.close();
    }
  };
  return opened;
}

async function shell(t, options = {}) {
  let opened;
  const heard = [];
  const page = await appPage(t, options.html || "tags.html", [], {
    ...options,
    setup(window) {
      opened = sockets(window, options.sockets);
      if (!window.document.getElementById("whoami")) {
        const who = window.document.createElement("span");
        who.id = "whoami";
        window.document.body.append(who);
      }
      window.addEventListener("midena-notification", (event) =>
        heard.push(event.detail.kind),
      );
      options.setup?.(window);
    },
  });
  const app = page.window.MIDENA;
  const me = options.signIn === false ? null : await app.initAuth(options.auth);
  await page.wait();
  return { ...page, app, me, opened, heard };
}

test("signing in opens one notification socket for the session", async (t) => {
  const page = await shell(t);
  assert.equal(page.me.username, "ada");
  assert.deepEqual(
    page.opened.map((socket) => socket.url),
    ["wss://midena.example/ws/notifications"],
  );
  // Asking again while it is open reuses it.
  page.app.startNotifications();
  assert.equal(page.opened.length, 1);
  assert.equal(page.$("whoami").textContent, "ada (admin)");
});

test("notices become page events; malformed frames are ignored", async (t) => {
  const page = await shell(t);
  const [socket] = page.opened;
  socket.receive(JSON.stringify({ kind: "diagram_shared" }));
  socket.receive(JSON.stringify({ kind: "lock_released" }));
  socket.receive("not json");
  socket.receive("null");
  assert.deepEqual(page.heard, ["diagram_shared", "lock_released"]);
  assert.deepEqual(page.toasts(), []);
});

test("a dropped socket reconnects while signed in", async (t) => {
  const page = await shell(t);
  page.opened[0].drop();
  await pause(2100);
  assert.equal(page.opened.length, 2);
});

test("signing out closes the socket and leaves through the server with the CSRF value", async (t) => {
  const page = await shell(t, {
    setup(window) {
      window.document.cookie = "theme=ink";
      window.document.cookie = "midena_csrf=abc%20123";
    },
  });
  page.opened[0].failsToClose = true;
  await page.app.logout();
  assert.equal(page.opened[0].closed, 1);
  assert.equal(page.navigations(), 1);
  assert.equal(page.app.state.me, null);
  // Nothing reconnects for a signed-out page.
  page.opened[0].drop();
  await pause(2100);
  assert.equal(page.opened.length, 1);
  assert.equal(page.app.getUserPreferences().theme, "ink");
});

test("the host-bound CSRF cookie is read ahead of one a sibling site could plant", async (t) => {
  // A site under the same parent domain can set midena_csrf for the whole
  // domain; a browser lets only this host set the __Host- name.
  const page = await shell(t, {
    setup(window) {
      window.document.cookie = "midena_csrf=planted";
      window.document.cookie = "__Host-midena_csrf=issued; Secure; Path=/";
      window.document.cookie = "theme=ink";
    },
  });
  assert.match(page.window.document.cookie, /midena_csrf=planted/);
  await page.app.api("/v1/thing", { method: "POST", body: { a: 1 } });
  await page.app.api("/v1/thing", { method: "DELETE" });
  const [post, remove] = page.requestHeaders.slice(-2);
  assert.equal(post["X-CSRF-Token"], "issued");
  assert.equal(remove["X-CSRF-Token"], "issued");
});

test("the bare CSRF cookie serves an installation that sets no prefix", async (t) => {
  const page = await shell(t, {
    setup(window) {
      window.document.cookie = "my_midena_csrf=other";
      window.document.cookie = "midena_csrf=plain";
    },
  });
  await page.app.api("/v1/thing", { method: "PUT", body: {} });
  assert.equal(page.requestHeaders.at(-1)["X-CSRF-Token"], "plain");
});

test("unsafe requests carry the CSRF cookie in preference to the cached token", async (t) => {
  const page = await shell(t, {
    setup(window) {
      window.document.cookie = "midena_csrf=from-cookie";
    },
  });
  await page.app.api("/v1/thing", { method: "POST", body: { a: 1 } });
  await page.app.api("/v1/thing");
  const [post, get] = page.requestHeaders.slice(-2);
  assert.equal(post["X-CSRF-Token"], "from-cookie");
  assert.equal(post["Content-Type"], "application/json");
  assert.equal(get["X-CSRF-Token"], undefined);
});

test("a page still works where sockets are blocked", async (t) => {
  const page = await shell(t, { sockets: { refuse: true } });
  assert.equal(page.me.username, "ada");
  assert.deepEqual(page.opened, []);
});

test("a refused request carries the server's reason, whatever its shape", async (t) => {
  const answers = {
    "/list": [
      422,
      { detail: [{ msg: "name is required" }, { loc: ["body"] }] },
    ],
    "/message": [500, { message: "Worker restarting" }],
    "/text": [502, "Bad gateway"],
    "/empty": [503, undefined],
    "/odd": [400, { other: true }],
  };
  const page = await shell(t, {
    api: (method, path) => answers[path] || null,
  });
  const reason = (path) =>
    page.app.api(path).then(
      () => "no error",
      (error) => error.message,
    );
  assert.equal(await reason("/list"), 'name is required; {"loc":["body"]}');
  assert.equal(await reason("/message"), "Worker restarting");
  assert.equal(await reason("/text"), "Bad gateway");
  assert.equal(await reason("/empty"), "HTTP 503");
  assert.equal(await reason("/odd"), "HTTP 400");
});

test("answers are read as JSON, text, or nothing", async (t) => {
  const page = await shell(t, {
    api: (method, path) =>
      path === "/plain"
        ? [200, "just text"]
        : path === "/nothing"
          ? [204, undefined]
          : null,
  });
  assert.equal(await page.app.api("/plain"), "just text");
  assert.equal(await page.app.api("/nothing"), null);
  assert.equal(
    await page.app.api("/plain", { responseType: "text" }),
    "just text",
  );
  const raw = await page.app.api("/plain", { responseType: "raw" });
  assert.equal(raw.status, 200);
});

test("a visitor without a session is sent to sign in, unless the page asks otherwise", async (t) => {
  const sent = await shell(t, { me: null });
  assert.equal(sent.me, null);
  assert.equal(sent.navigations(), 1);
  assert.equal(sent.$("whoami").textContent, "");
  assert.deepEqual(sent.opened, []);

  const stays = await shell(t, { me: null, auth: { redirectOnFail: false } });
  assert.equal(stays.me, null);
  assert.equal(stays.navigations(), 0);

  const broken = await shell(t, {
    api: (method, path) =>
      path === "/v1/me" ? [500, { detail: "down" }] : null,
  });
  assert.equal(broken.me, null);
  assert.equal(broken.navigations(), 1);
});

test("feature switches that cannot be read leave every area on", async (t) => {
  const page = await shell(t, {
    api: (method, path) =>
      path === "/v1/system/features" ? [500, { detail: "down" }] : null,
  });
  assert.equal(page.me.username, "ada");
  assert.equal(page.app.featureOn("ai_generation"), true);
});

test("the site root moves on to the account's start page", async (t) => {
  const prefer = (page) => (method, path) =>
    path === "/v1/me/preferences" ? [200, { default_start_page: page }] : null;
  const moved = await shell(t, {
    address: "https://midena.example/",
    api: prefer("folders.html"),
  });
  assert.equal(moved.me, null);
  assert.equal(moved.navigations(), 1);

  // The catalogue is already what the root shows, and a page outside the
  // offered list counts as the catalogue.
  for (const page of ["/index.html", "/somewhere-else.html"]) {
    const stays = await shell(t, {
      address: "https://midena.example/",
      api: prefer(page),
    });
    assert.equal(stays.me.username, "ada");
    assert.equal(stays.navigations(), 0);
  }
  const elsewhere = await shell(t, { api: prefer("/folders.html") });
  assert.equal(elsewhere.navigations(), 0);
});

test("colours saved under the old capability names still apply", async (t) => {
  const page = await shell(t, {
    api: (method, path) =>
      path === "/v1/me/preferences"
        ? [
            200,
            {
              capability_colors: { agents: "#ABCDEF", broken: "red" },
              node_colors: { "tax:wallet": "#123456" },
            },
          ]
        : null,
  });
  assert.equal(page.app.nodeColor("uwra:agents"), "#abcdef");
  assert.equal(page.app.nodeColor("tax:wallet"), "#123456");
  assert.equal(
    page.app.nodeColor("uwra:broken"),
    page.app.defaultNodeColor("uwra:broken"),
  );
  // Built-in groups have fixed colours; any other key gets a stable one.
  assert.equal(page.app.defaultNodeColor("uwra:channel_tier"), "#5b8def");
  const generated = [
    "a",
    "b",
    "c",
    "d",
    "e",
    "f",
    "g",
    "h",
    "i",
    "j",
    "k",
    "l",
  ].map((key) => page.app.defaultNodeColor(`tax:${key}`));
  for (const colour of generated) assert.match(colour, /^#[0-9a-f]{6}$/);
  assert.ok(new Set(generated).size > 6);
  assert.equal(page.app.defaultNodeColor("tax:a"), generated[0]);
});

test("preferences that fail to load fall back to the defaults", async (t) => {
  const page = await shell(t, {
    api: (method, path) =>
      path === "/v1/me/preferences" ? [500, { detail: "down" }] : null,
  });
  assert.deepEqual(JSON.parse(JSON.stringify(page.app.getUserPreferences())), {
    theme: "ink",
    node_colors: {},
    default_start_page: "/index.html",
    sticky_enabled: false,
    auto_apply_enabled: true,
    diagram_source_collapsed_by_default: true,
    diagram_sidebar_collapsed_by_default: true,
  });
  // Loaded once, they are not asked for again.
  const before = page.sent("GET", "/v1/me/preferences").length;
  await page.app.loadUserPreferences();
  assert.equal(page.sent("GET", "/v1/me/preferences").length, before);
});

test("controls of switched-off features and pages above the role are hidden", async (t) => {
  const page = await shell(t, {
    me: account("engineer", {
      features: { ...FEATURES, ai_generation: false },
    }),
    setup(window) {
      window.document.body.insertAdjacentHTML(
        "beforeend",
        `<a id="l-admin" href="/admin.html">Admin</a>
         <div id="marked" data-feature="ai_generation"></div>
         <div id="kept" data-feature="public_diagrams"></div>`,
      );
    },
  });
  assert.equal(page.$("l-admin").style.display, "none");
  assert.equal(page.$("marked").hidden, true);
  assert.equal(page.$("kept").hidden, false);
  page.app.setFeatures(null);
  assert.equal(page.app.featureOn("ai_generation"), true);
});

test("administrators keep the links their role allows", async (t) => {
  const page = await shell(t, {
    setup(window) {
      window.document.body.insertAdjacentHTML(
        "beforeend",
        '<a id="l-admin" href="/admin.html">Admin</a>',
      );
    },
  });
  assert.equal(page.$("l-admin").style.display, "");
});

test("a toast of an unknown kind is shown plainly, and an empty one is skipped", async (t) => {
  const page = await shell(t, { signIn: false });
  page.app.toast("Heads up", "sparkly");
  page.app.toast("   ");
  page.app.toast("Careful", "warn");
  assert.deepEqual(page.toasts(), [
    ["secondary", "Heads up"],
    ["warning", "Careful"],
  ]);
});
