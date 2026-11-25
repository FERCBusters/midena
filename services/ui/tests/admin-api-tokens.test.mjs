// The API tokens tab on the Administration page: issuing a token for an
// active account, showing it once, listing tokens and revoking them.
import test from "node:test";
import assert from "node:assert/strict";
import { loadPage } from "./support/load-page.mjs";

const USERS = {
  items: [
    { id: "u-keen", username: "keen-reader", is_active: true },
    { id: "u-gone", username: "former", is_active: false },
  ],
};

const listing = (items, enabled = true) => ({ enabled, items });

function token(overrides = {}) {
  return {
    id: "t-1",
    name: "KEEN <b>",
    user_id: "u-keen",
    username: "keen-reader",
    hint: "abcd",
    created_at: "2026-11-01T00:00:00Z",
    created_by: "admin",
    expires_at: null,
    last_used_at: null,
    revoked_at: null,
    status: "active",
    ...overrides,
  };
}

async function tokens(t, { responses, isAdmin = true, hash = "#api-tokens" }) {
  const calls = [];
  const page = await loadPage("admin.html", "pages/admin-api-tokens.js", {
    url: `https://midena.example/admin.html${hash}`,
    midena: {
      isAdmin: () => isAdmin,
      formatTimestamp: (value, empty = "—") => (value ? `at ${value}` : empty),
      api: async (path, options = {}) => {
        const body =
          options.body === undefined
            ? undefined
            : JSON.parse(JSON.stringify(options.body));
        calls.push([options.method || "GET", path, body]);
        const next = responses.shift();
        if (next instanceof Error) throw next;
        return structuredClone(next);
      },
    },
  });
  t.after(page.close);
  await page.settle();
  await page.settle();
  return { ...page, calls };
}

const listed = (document) =>
  [...document.querySelectorAll("#api-token-list tbody tr")].map((row) =>
    [...row.querySelectorAll("td")].map((td) => td.textContent),
  );

test("the open tab lists active accounts and tokens as text", async (t) => {
  const { document, calls } = await tokens(t, {
    responses: [USERS, listing([token()])],
  });
  assert.deepEqual(calls, [
    ["GET", "/api/v1/admin/users", undefined],
    ["GET", "/api/v1/admin/api-tokens", undefined],
  ]);
  const options = [...document.querySelectorAll("#api-token-user option")];
  assert.deepEqual(
    options.map((o) => [o.value, o.textContent]),
    [["u-keen", "keen-reader"]],
  );
  assert.deepEqual(listed(document), [
    [
      "KEEN <b>",
      "keen-reader",
      "…abcd",
      "at 2026-11-01T00:00:00Z by admin",
      "Never",
      "Never",
      "active",
      "Revoke",
    ],
  ]);
  // Names are text, never markup.
  assert.equal(document.querySelector("#api-token-list b"), null);
});

test("an empty listing says so, inactive rows offer no revoke, and a deployment with tokens off says so", async (t) => {
  const { document } = await tokens(t, {
    responses: [USERS, listing([])],
  });
  assert.match(
    document.getElementById("api-token-list").textContent,
    /No API tokens have been issued/,
  );
  const again = await tokens(t, {
    responses: [
      USERS,
      listing(
        [token({ status: "revoked", created_by: null, username: null })],
        false,
      ),
    ],
  });
  // Turned off by the deployment: the page says so and issues nothing.
  assert.equal(again.document.getElementById("api-token-off").hidden, false);
  assert.ok(
    [...again.document.getElementById("apiTokenForm").elements].every(
      (control) => control.disabled,
    ),
  );
  assert.equal(document.getElementById("api-token-off").hidden, true);
  assert.deepEqual(listed(again.document)[0].slice(1, 4), [
    "—",
    "…abcd",
    "at 2026-11-01T00:00:00Z",
  ]);
  assert.equal(again.document.querySelector("#api-token-list button"), null);
});

test("issuing shows the token once and refreshes the list", async (t) => {
  const { document, window, calls, settle } = await tokens(t, {
    responses: [
      USERS,
      listing([]),
      { token: "midena_at_secret", item: token() },
      USERS,
      listing([token()]),
    ],
  });
  document.getElementById("api-token-name").value = " KEEN ";
  document.getElementById("api-token-expiry").value = "90";
  document
    .getElementById("apiTokenForm")
    .dispatchEvent(new window.Event("submit", { cancelable: true }));
  await settle();
  await settle();
  assert.deepEqual(calls[2], [
    "POST",
    "/api/v1/admin/api-tokens",
    { name: "KEEN", user_id: "u-keen", expires_in_days: 90 },
  ]);
  assert.equal(document.getElementById("api-token-issued").hidden, false);
  assert.equal(
    document.getElementById("api-token-value").value,
    "midena_at_secret",
  );
  assert.equal(listed(document).length, 1);
  // The form returns to a year's expiry.
  assert.equal(document.getElementById("api-token-expiry").value, "365");
});

test("a token that never expires is asked for without an expiry", async (t) => {
  const { document, window, calls, settle } = await tokens(t, {
    responses: [USERS, listing([]), new Error("Refused")],
  });
  document.getElementById("api-token-name").value = "KEEN";
  document.getElementById("api-token-expiry").value = "";
  document
    .getElementById("apiTokenForm")
    .dispatchEvent(new window.Event("submit", { cancelable: true }));
  await settle();
  assert.equal(calls[2][2].expires_in_days, null);
  assert.equal(document.getElementById("api-token-issued").hidden, true);
  assert.match(
    document.getElementById("api-token-status").textContent,
    /Could not issue a token: Refused/,
  );
});

test("revoking asks first, then refreshes", async (t) => {
  const { document, window, calls, settle } = await tokens(t, {
    responses: [
      USERS,
      listing([token()]),
      { item: token({ status: "revoked" }) },
      USERS,
      listing([token({ status: "revoked" })]),
    ],
  });
  window.confirm = () => false;
  document.querySelector("#api-token-list button").click();
  await settle();
  assert.equal(calls.length, 2);
  window.confirm = () => true;
  document.querySelector("#api-token-list button").click();
  await settle();
  await settle();
  assert.deepEqual(calls[2], [
    "POST",
    "/api/v1/admin/api-tokens/t-1/revoke",
    undefined,
  ]);
  assert.match(
    document.getElementById("api-token-status").textContent,
    /Revoked "KEEN <b>"/,
  );
  assert.equal(document.querySelector("#api-token-list button"), null);
});

test("a refused revoke and a failed load are reported", async (t) => {
  const { document, window, settle } = await tokens(t, {
    responses: [
      USERS,
      listing([token()]),
      new Error("Gone"),
      new Error("Offline"),
    ],
  });
  window.confirm = () => true;
  document.querySelector("#api-token-list button").click();
  await settle();
  await settle();
  assert.match(
    document.getElementById("api-token-status").textContent,
    /Could not load API tokens: Offline/,
  );
});

test("copying uses the clipboard, or selects the token", async (t) => {
  const { document, window, settle } = await tokens(t, {
    responses: [USERS, listing([])],
  });
  const copied = [];
  Object.defineProperty(window.navigator, "clipboard", {
    configurable: true,
    value: { writeText: async (text) => copied.push(text) },
  });
  document.getElementById("api-token-value").value = "midena_at_x";
  document.getElementById("api-token-copy").click();
  await settle();
  assert.deepEqual(copied, ["midena_at_x"]);
  assert.match(
    document.getElementById("api-token-status").textContent,
    /Token copied/,
  );
  Object.defineProperty(window.navigator, "clipboard", {
    configurable: true,
    value: {
      writeText: async () => {
        throw new Error("denied");
      },
    },
  });
  document.getElementById("api-token-copy").click();
  await settle();
  assert.match(
    document.getElementById("api-token-status").textContent,
    /Select the token and copy it/,
  );
});

test("the tab loads when first shown, once", async (t) => {
  const { document, window, calls, settle } = await tokens(t, {
    hash: "",
    responses: [USERS, listing([])],
  });
  assert.equal(calls.length, 0);
  const tab = document.getElementById("tab-api-tokens");
  tab.dispatchEvent(new window.Event("shown.bs.tab"));
  await settle();
  tab.dispatchEvent(new window.Event("shown.bs.tab"));
  await settle();
  assert.equal(calls.length, 2);
});

test("only administrators get the tab's behaviour", async (t) => {
  const { calls } = await tokens(t, { isAdmin: false, responses: [] });
  assert.deepEqual(calls, []);
});
