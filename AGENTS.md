# Working on MIDENA

## Scope and structure

- Read the relevant code and tests before editing. Prefer small changes to the layer that owns the behaviour, using existing helpers and services.
- Keep HTTP handlers focused on validation, authorisation and responses. Shared security boundaries live in `services/api/app/security/`; background work lives in `services/api/app/tasks/`; integrations live in `services/api/app/services/`. Feature switches live in `app/core/features.py` (administrator-managed, with `MIDENA_FEATURE_*` as the deployment ceiling; keep it aligned with KEEN's and OSPMAE's) and gate routes through `require_feature`.
- MIDENA's security primitives come from KEEN and OSPMAE and are the candidates for the shared `myf` framework. Keep each one behaviourally identical to its origin unless MIDENA's version is stronger, and record a deliberate difference beside the code.
- Use the design system and shared UI helpers (`@fercbusters/mosp-design-system`, pinned by commit in `services/ui/package.json` and vendored into `public/vendor/` by `scripts/vendor-assets.mjs`). Keep API authorisation authoritative even when the UI hides an action.
- Remove code only after checking all callers, configuration references and runtime entry points. Do not introduce compatibility machinery without a concrete supported use case.
- Before writing a helper, search for an existing one and reuse or extend it. Shared homes include:
  - `security/route_policy.py`: `PUBLIC_ROUTES` and `WRITE_POLICY`, the rule for every served route; `audit_path` for paths that carry tokens.
  - `security/client_addr.py`: `request_client_address` and `request_allowance_key` (an IPv6 /64 counts as one address).
  - `security/url_safety.py`: `validate_safe_href` for stored links, `safe_relative_route_path` for redirects and stored paths.
  - `security/xml.py`: `parse_untrusted_xml` for every XML document a user or upstream supplies.
  - `security/svg.py`: `sanitise_svg` for every stored SVG.
  - `security/sso_http.py`: `client_options` for every identity-provider request (bounded, uncompressed, no redirects, no proxy environment).
  - `core/datetime_utils.py`: `utc_now_naive` for every stored timestamp.
  - `security/rate_limit.py`: `take_rate_limit` for database-backed allowances; `security/local_allowance.py` for bounded in-memory ones.
  - `security/request_limits.py`: body classes, JSON shape, request targets and cookie screening, shared with KEEN.
  - `security/sessions.py` (`session_row`, `csrf_token_for`), `security/csrf.py` and `security/auth.session_cookie_name`: cookies are read and set under these names, never the bare settings.
  - `api/deps.py`: `DbId`, `OptionalDbId`, `PageLimit`, `PageOffset` for every integer parameter.
  - `api/downloads.py`: `attachment_media_type` and `content_disposition_attachment` for every download.
  - `security/audit.py` (`record_sign_in`), `tasks/maintenance.py` (retention sweeping), `services/entity_changelog.py` (semantic history).
  - In the UI: `app.js` (`safeHref`, `escapeHtml`, `featureOn`/`gateFeature`, `formatDate`) and `rendered-diagram-interactions.js` (`svgNodeFromMarkup`, `safeLinkUrl`).
- A second copy of a helper is a defect even when it starts out identical. Where a behaviour must be the same everywhere, give it one shared helper, route every caller through it, and add a contract test that refuses a hand-rolled copy and proves it would catch one.
- Trust declared types. Read typed settings, ORM columns and values the code has just built directly. Keep guards where data is untrusted or genuinely optional: request payloads, diagram content, provider answers and nullable columns.
- Every optional area honours its feature switch: routes answer 404 when it is off, and the UI hides it through `featureOn`/`gateFeature`.

## Security invariants

- Every HTTP route enters the authentication, Origin, CSRF and audit middleware in `main.py`. A new route needs a rule in `security/route_policy.py` (the suite fails without one), an explicit permission or object check, and regression tests against the assembled application.
- Diagram content is hostile wherever it appears. BPMN parses through `parse_untrusted_xml(strict=True)`; SVG is stored only after `sanitise_svg`; in the browser, SVG markup enters the page only through `svgNodeFromMarkup`, Mermaid runs with `securityLevel: 'strict'`, and links pass `safeLinkUrl`. Never assign diagram-derived markup to `innerHTML`.
- Diagrams are addressed by UUID. Public reads need the UUID and the public token together, compare the token in constant time, answer a uniform 404, and return the public projection only. A diagram leaving `public` gets a new token.
- Every read path (search, listings, tags, versions, comments, links, changelog, exports) applies the same visibility rule as the diagram detail. Writes take the diagram's row lock.
- Outbound requests go only to fixed or validated destinations: no redirects, no proxy environment, bounded answers, provider bodies kept out of errors. Always validate TLS certificates and hostnames.
- Password sign-in, second factors, SSO linking and account management follow KEEN's rules; a change there is made in KEEN, OSPMAE and MIDENA alike.
- Use bound SQL parameters and ORM expressions; escape `LIKE` wildcards with `autoescape=True`. Bound every integer parameter to the database's integer range.
- Regular expressions over user input are linear: no nested or overlapping quantifiers. Test the costliest accepted input at the largest accepted size.
- Fail closed on authentication or authorisation uncertainty. Keep errors useful without disclosing credentials, tokens or upstream response bodies.
- Downloads are attachments with fixed names; anything a browser could render actively is typed `application/octet-stream`.

## Validation

- Use `.github/workflows/tests.yml`, `tests.sh` and `tests-ui.sh` as the authoritative test workflow. The backend suite runs on PostgreSQL only (`MIDENA_TEST_DATABASE_URL`, a disposable database; `tests/conftest.py` refuses anything else) and skips nothing. Never point tests at an operational installation.
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
- `app/api/routes/` owns HTTP adapters. `app/security/` owns authentication, sessions, client addresses, allowances, content safety and redaction. `app/db/` owns models and session setup, `app/tasks/` owns background work, `app/services/` owns mail, notifications and integrations.
- Migrations live in `alembic/versions/` as explicit DDL; never `create_all` or an import of `app`. Write the model change, the migration and a test touching both together; `tests/test_migrations.py` checks that upgrading matches the models.
- A request's session discards whatever it has not committed. Queue mail in the transaction of the change it reports.

## Frontend

- The build vendors pinned third-party assets into `public/vendor/` (`npm run build` in `services/ui`, installed with `--ignore-scripts`), and nginx serves `dist/` with the policy in `services/ui/nginx/default.conf`. Pages load `theme-boot.js` in `<head>` so the saved palette applies before first paint.
- Keep first-party pages token-driven through the design system's variables.
- Only the embed page may be framed by other sites; keep it free of account code.
