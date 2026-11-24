# Working on MIDENA

## Scope and structure

- Read the relevant code and tests before editing. Prefer small changes to the layer that owns the behaviour, using existing helpers and services.
- Keep HTTP handlers focused on validation, authorisation and responses. Signing in, sessions, second factors, single sign-on, CSRF, request limits, client addresses, the audit trail and the shared security primitives come from the `MOSP` framework (`FERCBusters/mosp`, pinned in `services/api/pyproject.toml`), which KEEN and OSPMAE share; MIDENA binds to it in `app/__init__.py` and takes part through `app/mosp_hooks.py`. MIDENA's own route policy and permissions live in `services/api/app/security/`; background work lives in `services/api/app/tasks/`; integrations live in `services/api/app/services/`. Feature switches live in `app/core/features.py` (administrator-managed, with `MIDENA_FEATURE_*` as the deployment ceiling; keep it aligned with KEEN's and OSPMAE's) and gate routes through `require_feature`.
- A behaviour the three applications share belongs in MOSP, changed there for all of them; MIDENA keeps only what is its own. Where MIDENA needs something MOSP lacks, add it to MOSP (with MOSP's tests) rather than a local copy.
- Use the design system and shared UI helpers (`@fercbusters/mosp-design-system`, pinned by commit in `services/ui/package.json` and vendored into `public/vendor/` by `scripts/vendor-assets.mjs`). Keep API authorisation authoritative even when the UI hides an action.
- Remove code only after checking all callers, configuration references and runtime entry points. Do not introduce compatibility machinery without a concrete supported use case.
- Before writing a helper, search for an existing one in MIDENA and in MOSP, and reuse or extend it. Shared homes include:
  - `app/security/route_policy.py`: `MIDENA_POLICY`, the rule for every MIDENA route, merged with MOSP's own (`mosp.security.route_policy`); `audit_path` for paths that carry tokens.
  - `app/security/permissions.py`: MIDENA's permission codes and their seed.
  - `mosp.security.client_ip`: `request_ip` (forwarded addresses through `MIDENA_SECURITY_TRUSTED_PROXY_CIDRS`); `mosp.security.rate_limit`: `sliding_window_allow` for Valkey-backed allowances and `address_allowance` (an IPv6 /64 counts as one address).
  - `mosp.security.urls`: `external_url` for stored links, `same_site_path` for redirects and stored paths.
  - `mosp.security.xml`: `parse_untrusted_xml` for every XML document a user or upstream supplies; `mosp.security.svg`: `sanitise_svg` for every stored SVG. MIDENA passes its 3 MiB bound (`MAX_XML_BYTES` in `diagrams.py`).
  - `mosp.security.sso_http`: `client_options` for every identity-provider request (bounded, uncompressed, no redirects, no proxy environment).
  - `mosp.core.datetime_utils`: `utc_now_naive` for every stored timestamp, `iso_or_none` for every serialised one; `mosp.core.identifiers.try_uuid` for a UUID a route reads.
  - `mosp.security.auth`: `require_authenticated` and `require_admin` for every route's account.
  - `mosp.core.task_deadline`: `TIME_LIMITS`, re-raised before every broad handler in task code (`tests/test_celery_contract.py` checks it).
  - `mosp.security.json_shape.decode_json` for every JSON document from outside (Google's and the AI provider's answers).
  - `mosp.security.request_limits` and `app/mosp_hooks.body_limit`: body classes, request targets and cookie screening; `mosp.api.routing.Router` for every router, so JSON bodies are decoded with MOSP's shape limits.
  - `mosp.security.sessions`, `mosp.security.csrf` and `mosp.security.auth.cookie_name`: cookies are read and set under these names, never the bare settings.
  - `mosp.security.permissions.bump_authz_versions`: after any change to an account's role, groups or permissions, so its sessions follow.
  - `api/deps.py`: `DbId`, `OptionalDbId`, `PageLimit`, `PageOffset` for every integer parameter.
  - `api/downloads.py`: `attachment_media_type` and `content_disposition_attachment` for every download.
  - `tasks/maintenance.py` (MOSP's `housekeeping` and `audit_retention` sweeps with MIDENA's locks), `services/entity_changelog.py` (semantic history), `services/notifications.py` (the share-notice outbox, delivered by `mosp.services.outbox`).
  - In the UI: `app.js` (`safeHref`, `escapeHtml`, `featureOn`/`gateFeature`, `formatDate`, `logout`) and `rendered-diagram-interactions.js` (`svgNodeFromMarkup`, `safeLinkUrl`).
- A second copy of a helper is a defect even when it starts out identical. Where a behaviour must be the same everywhere, give it one shared helper, route every caller through it, and add a contract test that refuses a hand-rolled copy and proves it would catch one.
- Trust declared types. Read typed settings, ORM columns and values the code has just built directly. Keep guards where data is untrusted or genuinely optional: request payloads, diagram content, provider answers and nullable columns.
- Every optional area honours its feature switch: routes answer 404 when it is off, and the UI hides it through `featureOn`/`gateFeature`.

## Security invariants

- Every HTTP route enters MOSP's authentication, Origin, CSRF and audit middleware, installed in `main.py`. A new route needs a rule in `app/security/route_policy.py` (a write without one is refused for everyone, and the suite fails), an explicit permission or object check, and regression tests against the assembled application.
- Diagram content is hostile wherever it appears. BPMN parses through `parse_untrusted_xml(strict=True)`; SVG is stored only after `sanitise_svg`; in the browser, SVG markup enters the page only through `svgNodeFromMarkup`, Mermaid runs with `securityLevel: 'strict'`, and links pass `safeLinkUrl`. Never assign diagram-derived markup to `innerHTML`.
- Diagrams are addressed by UUID. Public reads need the UUID and the public token together, compare the token in constant time, answer a uniform 404, and return the public projection only. A diagram leaving `public` gets a new token.
- Every read path (search, listings, tags, versions, comments, links, changelog, exports) applies the same visibility rule as the diagram detail. Writes take the diagram's row lock.
- Outbound requests go only to fixed or validated destinations: no redirects, no proxy environment, bounded answers, provider bodies kept out of errors. Always validate TLS certificates and hostnames.
- Password sign-in, second factors, SSO linking and sessions are MOSP's; a change there is made in MOSP, with its tests, for KEEN, OSPMAE and MIDENA alike. Accounts are administrators, ordinary accounts or inherit their role from their groups; what an ordinary account may do comes from its permissions.
- Use bound SQL parameters and ORM expressions; escape `LIKE` wildcards with `autoescape=True`. Bound every integer parameter to the database's integer range.
- Regular expressions over user input are linear: no nested or overlapping quantifiers. Test the costliest accepted input at the largest accepted size.
- Fail closed on authentication or authorisation uncertainty. Keep errors useful without disclosing credentials, tokens or upstream response bodies.
- Downloads are attachments with fixed names; anything a browser could render actively is typed `application/octet-stream`.

## Validation

- Use `.github/workflows/tests.yml`, `tests.sh` and `tests-ui.sh` as the authoritative test workflow. The backend suite runs on PostgreSQL only (`MIDENA_TEST_DATABASE_URL`, a disposable database; `tests/conftest.py` refuses anything else) and skips nothing; Valkey is an in-memory stand-in (fakeredis). Never point tests at an operational installation. MOSP's own suite covers its sign-in, session and request rules; MIDENA's tests cover how MIDENA assembles them and everything MIDENA adds.
- UI tests need `npm ci --prefix services/ui/tests`. Page tests load the real page HTML and classic scripts into jsdom through `services/ui/tests/support/load-page.mjs`, substituting only `window.MIDENA` or the network; assert what a user sees and what reaches the API.
- `coverage-requirement.txt` and `coverage-requirement-ui.txt` are ratchets towards 100: raise them with each batch of tests, never lower them.
- For security changes, add a reproducible negative test demonstrating the attack prerequisite and its rejection, through the assembled application where the property is enforced there.
- Update `services/api/pyproject.toml` and `poetry.lock` together. Preserve pinned Actions, image digests and the design-system revision. Pin a new image with `python3 tools/docker_image_pins.py update`; record a reviewed git package with `npm run vendor:record` in `services/ui` after reviewing it.
- Keep `ruff check ../..`, `ruff format --check ../..` and `mypy app` (from `services/api`), `bash lint-ui.sh` and `bash format-ui.sh --check` clean. Keep imports at the top of each module.
- Validate the exact final working tree after formatter or lint fixes. Report what passed, what failed and what could not run.

## Security re-review whenever completing a round of work

Whenever completing a round of work, work through the required security review checklist in SECURITY.md, record evidence and untested limitations, and re-review whether the changes weaken any security property. Example hazards: account takeover, privilege escalation or authorisation bypass, injection, XSS through diagram content, SSRF, CSRF, trivial DoS or ReDoS, open redirects, unbounded requests, middleware bypass through route nesting, TLS validation gaps, weak OIDC parameter checking, token replay, public-token disclosure, stale records, sensitive values in logs or errors, client-trust mistakes, redaction gaps, cryptographic failure, race conditions and missing rate limits.

Fix each confirmed issue across its whole class. Name the property it violates, search the codebase for every path sharing that property, fix them all, and enforce the property with a codebase-wide contract test that includes a check proving the test detects the original defect.

## Documentation and delivery

- README.md describes current capabilities and setup. SECURITY.md describes the current security model, realistic risks and reporting policy; keep findings and fix history out of it.
- Write in present tense and British English, without release-update narratives or developer handover instructions in user-facing documentation. Avoid contrastive-negation language.

## Backend architecture

- The request path is middleware → HTTP adapter → domain operation → persistence. Middleware handles cross-cutting request policy for every route in one place; keep it generic.
- `app/api/routes/` owns HTTP adapters; MOSP's routers serve signing in and out, second factors, single sign-on and the account's own password and SSO addresses. `app/security/` owns MIDENA's route policy and permissions. `app/db/` owns models (MOSP's account mixins and MIDENA's own tables) and session setup, `app/tasks/` owns background work, `app/services/` owns mail, notifications and integrations.
- Migrations live in `alembic/versions/` as explicit DDL; never `create_all` or an import of `app`. Write the model change, the migration and a test touching both together; `tests/test_migrations.py` checks that upgrading matches the models.
- A request's session discards whatever it has not committed. Queue mail in the transaction of the change it reports.

## Frontend

- The build vendors pinned third-party assets into `public/vendor/` (`npm run build` in `services/ui`, installed with `--ignore-scripts`), and nginx serves `dist/` with the policy in `services/ui/nginx/default.conf`. Pages load `theme-boot.js` in `<head>` so the saved palette applies before first paint.
- Keep first-party pages token-driven through the design system's variables.
- Only the embed page may be framed by other sites; keep it free of account code.
