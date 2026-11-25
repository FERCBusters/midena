# Security policy and threat model

## Reporting a vulnerability

Please report suspected vulnerabilities through this project's GitHub repository. Prefer **Security → Advisories → Report a vulnerability** for a private report. If private reporting is unavailable, open an issue asking for a private reporting channel and keep exploit details, credentials and sensitive data out of the public issue.

Every report must include a reproducible proof of concept demonstrating the issue. Include:

- The MIDENA version or commit, the deployment configuration relevant to the issue, and the affected component.
- The attacker's required access, permissions and other prerequisites.
- Minimal reproduction steps or a script, expected and actual results, and evidence of the security impact.
- Synthetic test data and redacted logs or screenshots where useful.

Test on an installation you own or have explicit permission to assess. Use the smallest demonstration that establishes the issue, preserve other people's data, and avoid disruptive testing against public or hosted instances.

Our goal is to provide a preliminary response within **72 hours**. This is an acknowledgement and initial assessment target; investigation and remediation time depends on the report. MIDENA offers **no monetary bounties**. Authors of validated reports are credited, using their preferred name or handle, unless they request anonymity. We coordinate disclosure with reporters after assessing impact and remediation.

## Scope and trust boundaries

### What MIDENA protects

MIDENA stores process and architecture diagrams (BPMN, Mermaid flowcharts and Mermaid sequence diagrams), their immutable versions, folders, tags, comments, element links, shares and change history, plus user accounts and preferences. Diagrams often describe an organisation's internal systems, data flows and controls. Security objectives are controlling who reads or changes each diagram, keeping private diagrams out of public views, search results and exports their reader cannot see, keeping diagram content inert wherever it is shown, keeping integration credentials (Google Drive, the AI provider) on the server, and maintaining service availability.

A MIDENA installation is an organisational trust boundary. Users inside it receive access through roles, groups and permissions; a diagram's creator, its shares and its visibility (`private`, `internal` or `public`) scope who may read and change it. Hosting mutually distrustful organisations requires isolated installations, databases and secrets.

### Actors

The threat model includes an unauthenticated Internet client (including one holding a public diagram link), a malicious website visited by a signed-in user, a website embedding a public diagram, a user acting beyond their assigned permissions, a user who uploads hostile diagram content (BPMN XML, Mermaid source, SVG) for others to open, and hostile answers from the configured AI provider or Google's APIs.

Application administrators are trusted to configure providers, permissions, feature switches, diagram chrome and retention. Deployment operators control the executable code, database, broker and environment secrets. Compromise of these privileges can compromise the installation. An administrator's intended ability to read every diagram, delete data or grant permissions is part of that role; escaping the role's intended authority remains a security issue.

Identity providers, Google and the AI provider are trusted for their specific functions. A compromised identity provider can assert identities; the AI provider sees the prompt and diagram source a user chooses to send it; Google Drive receives the exports users send there.

### Hostile diagram content

Every diagram field is attacker-shaped. The API stores diagrams in forms that cannot act:

- **BPMN XML** parses through `security/xml.parse_untrusted_xml(strict=True)` (defusedxml beneath it): any document type declaration, entity or processing instruction is refused, the document is capped at 3 MiB, and the root must be a BPMN 2.0 `definitions` element.
- **Mermaid source** is text: control characters and markup tags are refused by linear-time checks, and size is capped (3,000,000 characters of source).
- **SVG** is rebuilt by `security/svg.sanitise_svg` from an allowlist of SVG elements and attributes. Scripts, `foreignObject`, images, animation and event handlers are dropped; `href`/`xlink:href` keep same-document `#fragment` references only; inline styles and `<style>` sheets survive only when they load nothing (no `url()` other than `url(#…)`, no `@import`, no backslash escapes, no legacy script hooks). Text and the `data-*`/`aria-*` annotations bpmn-js and Mermaid add are kept.
- **Element links and metadata** are flat, bounded and validated: element identifiers follow an XML-name shape, metadata holds at most 50 keys of at most 2,000 characters, and link addresses pass `security/url_safety.validate_safe_href` (web schemes or same-site paths; no backslashes or control characters).

The browser treats stored content as hostile again. SVG markup is parsed as XML through `DOMParser`, filtered with the same CSS rule as the server, and inserted as nodes (`MIDENA_RENDERED.svgNodeFromMarkup`); no page assigns SVG markup to `innerHTML`. Mermaid always renders with `securityLevel: 'strict'`. Links on rendered diagrams pass `safeLinkUrl`, which keeps web and same-site addresses only. Within those limits a diagram can still describe something false or misleading; its change history records who changed it and when.

## Authentication

Signing in, sessions, second factors, single sign-on, CSRF and Origin checks, request limits, client addresses and the request audit trail come from MOSP, the framework MIDENA shares with KEEN and OSPMAE, so the three behave alike and a change to one of these rules is made there for all of them.

### Pages

nginx serves an application page only to a signed-in browser, as KEEN's does: each page request is first put to the API (`auth_request` to `/v1/auth/check`), so a signed-out browser receives the sign-in page in place of the page it asked for (status 403, at the same address, which a completed sign-in returns to). The administration page and its scripts are checked against `/v1/auth/check-admin` and answer 404 to any other account. The sign-in, second-factor and e-mail confirmation pages, and the public diagram and embed pages, are served without a session; none holds account data. The gate keeps pages from signed-out browsers; every record is still authorised by the API.

### Sessions

Browser sessions use random, server-generated identifiers. Valkey keys each session by the SHA-256 digest of its identifier, so the store, its snapshot file and a client holding its password see no identifier a browser could present. The session cookie is HttpOnly, with `SameSite` and `Secure` from configuration. Where cookies are Secure and no cookie domain is set, the session, CSRF, device and pending second-factor cookies take the `__Host-` prefix (`__Host-midena_session`, `__Host-midena_csrf`), which a browser accepts only from the installation's own host over HTTPS, so a site on a sibling subdomain can neither set nor shadow them. Cookie names holding bytes outside printable ASCII are removed from every request, WebSocket handshakes included, before anything reads them, so a look-alike name cannot be read as one of these cookies.

Signing in issues a fresh identifier. Signing out is a POST carrying the session's CSRF token and deletes the session; when the store cannot confirm the deletion, sign-out answers with a retryable error and the browser keeps its cookies for the retry. A provider's session answers with the provider's end-session address. A session ends at its sliding expiry (`MIDENA_SESSION_TTL_SECONDS`) and also a fixed time after sign-in (`MIDENA_SESSION_MAX_AGE_SECONDS`, 30 days by default), whatever its sign-in method. A session opened through a provider ends while that provider is disabled.

Each session carries a snapshot of the account's role and permissions, checked against a database-backed authorisation version: every change to an account's role, groups or permissions, or to a group's role or permissions, moves the version of each account it affects, so open sessions follow. A password change or reset, a second-factor change and deactivation move the account's security version, which ends its sessions; a deactivated account's sessions stay ended if it is activated again. While Valkey is unavailable no session can be read, so authenticated requests are answered 503 with `Retry-After`.

### Sign-in throttling

Password sign-in follows the policy shared with KEEN and OSPMAE (`mosp.security.sign_in_throttle`), built on NIST SP 800-63B-4 section 3.2.2 and the OWASP device-cookie protocol:

- **Recognised browsers.** A browser that has given an account's correct password holds an HttpOnly, Secure, `SameSite=Strict` device cookie for that account, valid for 90 days and replaced at each correct password; Valkey holds only its digest, and an account keeps its 20 newest. Its attempts skip the per-address allowance and the account's throttle and draw on their own allowance: five wrong passwords in a row end its recognition.
- **Other browsers.** Attempts draw on a per-address allowance (`MIDENA_LOGIN_RATE_LIMIT_PER_IP` in `MIDENA_LOGIN_RATE_LIMIT_WINDOW_SECONDS`, 30 in five minutes by default, counting an IPv6 /64 network as one address) and on the account's throttle: five consecutive failures are free, each later attempt opens a wait of 30 seconds that doubles up to an hour, and after 100 consecutive failures other browsers are refused until a correct password from a recognised browser or an administrator's password reset. The throttle is keyed by a digest of the sign-in method and the compared username whether or not an account has it.
- **Refusals.** A held attempt is answered 429 with `Retry-After` and never reaches password verification. Every other rejection performs one full PBKDF2 verification (against a fixed dummy hash where no usable account exists), so response timing carries no account-existence signal. Sign-in limits fail closed while Valkey is unavailable.

**Accepted risk.** Someone who knows a username can make sign-in from browsers that have never signed in to that account wait up to an hour between attempts, and after 100 consecutive failures refuse them until recovery; recognised browsers keep signing in throughout, and an administrator can reset the password. A second factor covers a guessed password.

### Passwords and accounts

Passwords hash with PBKDF2-SHA256 at 600,000 iterations and per-password salts. New passwords follow NIST SP 800-63B-4: at least `MIDENA_PASSWORD_MIN_LENGTH` characters (15; fewer, down to eight, only with `MIDENA_MFA_POLICY=all`), at most 1,024, no composition rules, and a comparison with commonly guessed passwords, sequences and the account's own username. A username holds no control, format or line-break character, and no two accounts have names that differ only in case, width, spacing or invisible characters. Administrators create accounts, set their e-mail and reset passwords; there is no self-service reset by e-mail. A password change (`POST /v1/me/password`) re-verifies the current password under per-address and per-account (`MIDENA_PASSWORD_CHANGE_RATE_LIMIT_PER_ACCOUNT`) allowances and ends every session of the account. An administrator's reset ends the account's sessions and every browser's recognition, clears its throttle and mails its owner.

The first administrator comes from `MIDENA_BOOTSTRAP_ADMIN_USERNAME` and `MIDENA_BOOTSTRAP_ADMIN_PASSWORD`, which take effect only while the users table is empty, under a database lock so concurrent API processes create one account. A placeholder or weak bootstrap password is refused, and the refusal never repeats the password.

### Second factors

Local accounts may enrol a TOTP authenticator, WebAuthn security keys or passkeys, or both, backed by ten single-use recovery codes stored as SHA-256 digests. `MIDENA_MFA_POLICY` (`optional`, `admins`, `all`) decides whom the ceremony demands of. A second factor starts a five-minute challenge whose cookie is separate from the session cookie and dies with any account change. Each ceremony step checks `Origin` against `MIDENA_PUBLIC_BASE_URL` and draws on the account's allowance (15 in any five minutes); starting factor management, which checks the password, also draws on a per-address allowance (40 in five minutes), and only once the account admits it, so no account can use up another's steps behind the same address; five wrong codes refuse every code for an hour, counted for a day after the latest wrong one. TOTP secrets are stored Fernet-encrypted under `MIDENA_MFA_ENCRYPTION_KEY`. An enrolment change ends every other local session of the account. An operator recovers an account that has lost every factor with `scripts/mfa_admin.py` inside the API container (MOSP's `operator_reset`), which mails the owner a notice. For an account that signs in only through SSO, `--list-identities` lists its SSO identities and `--reset --keep-identity ID` keeps the one the owner confirms and removes every other SSO identity and SSO email address.

### Single sign-on and account linking

OpenID Connect providers and the bundled Google and GitHub support require an explicitly configured HTTPS redirect URI (plain HTTP only on localhost); the callback address never derives from a request host. Sign-in uses PKCE S256 and single-use server-side state with a 10-minute expiry, bound to the browser that started it by a host-bound cookie, so a callback link sent to someone else signs nobody in. ID tokens verify only under the asymmetric algorithms the deployment allows (`MIDENA_OIDC_ALLOWED_ALGS`, RS256 by default; the token header cannot widen the list) and are validated for signature, issuer, a single audience equal to MIDENA's client ID, authorised party, nonce, expiry and issued-at, with each claim of its expected type. Provider requests verify TLS, ignore proxy settings from the environment, follow no redirects, read uncompressed answers of at most 1 MiB, and end at a deadline. Single sign-on reaches existing accounts only: an account links a provider through an address it has proved by mailbox (`mosp.services.sso_emails`), the provider must report that address verified, and MIDENA never creates accounts from provider claims. The account's owner is mailed whenever an identity is linked, sees the linked identities beside the addresses, and can remove any that is not the account's only way to sign in; removing one also removes the address it was linked through and ends every session. An operator's MFA reset of an account that can sign in without SSO removes its identities and addresses as well. Session trust never derives from `preferred_username` or other selectable claims. The callback's query string is never stored in the audit log.

### Trusted remote-user authentication

`MIDENA_TRUST_REMOTE_USER=true` hands authentication to the configured identity header, honoured only when the socket peer sits inside `MIDENA_REMOTE_USER_TRUSTED_CIDRS` (a list separate from the forwarding proxies, with no default) and only for the single configured header name. The supplied nginx clears the client's copies of the identity headers authenticating proxies commonly use.

### Security notices and mail

The account's owner is mailed when something changes or tests the account's protection: a sign-in from an unfamiliar address, a password change or reset, a second factor added or removed, recovery codes replaced or used, a second-factor lockout, an operator's second-factor reset, and an SSO address verified or removed. Outgoing mail is two transactional outboxes, MOSP's security notices and MIDENA's diagram share notices: senders queue inside the transaction of the change they report and the worker drains both with backoff, recording only the exception class on failure and clearing a sent message's body. The Administration page lists both. Links in mail take their host from `MIDENA_PUBLIC_BASE_URL` only, never from a request.

### Client addresses

`mosp.security.client_ip` resolves every client address (allowances, audit rows): it walks `X-Forwarded-For` right-to-left while each hop stays inside `MIDENA_SECURITY_TRUSTED_PROXY_CIDRS` and keeps the socket peer otherwise. Allowance keys count one IPv4 address or one IPv6 /64 network. An untrusted client's forwarded headers cannot change its resolved address. The API reads no forwarded scheme or host: the public base URL names the installation's own origin.

## Authorisation

### Route policy

Every HTTP route passes one middleware decision (MOSP's route policy, with MIDENA's routes declared in `app/security/route_policy.py` as `MIDENA_POLICY`). The public routes are health, the root, the sign-in and SSO ceremonies, second-factor steps and the public diagram reads. Every write is declared with what it needs: an account acting on its own records, a named permission, an object check the route itself performs, or an administrator (every route under `/v1/admin/` apart from the audit readers, which `audittrail.read` also opens, and tag management). MIDENA closes every write it does not declare: such a route is refused for everyone, administrators included, so a new route fails closed until its rule is written. The test suite reconciles the policy with the routes the application serves.

### Diagrams

Diagrams are addressed by UUID; a sequential database identifier names no diagram. A diagram is readable by administrators and holders of `diagram.read_private`, its creator, users it is shared with, and, when its visibility is `internal` or `public`, every signed-in user. Changing a diagram needs `diagram.write` and either its creation or an editor share; sharing and deletion belong to its creator and administrators. A lock held by another user refuses writes (423); locks expire and the maintenance sweeper removes them, and administrators can clear them, with each clearance in the change history. Saves, updates, locks, shares and deletions take the diagram's row lock, so concurrent writers serialise. A clone starts private and carries no shares. Search, listings, tag counts, changelogs, versions, comments, links and exports apply the same read rule as the diagram itself, and every `LIKE` search escapes its wildcards.

Sharing resolves the recipient by exact, case-insensitive username or e-mail match and refuses an ambiguous one. The user search behind it needs at least two characters and returns usernames only; recipients' e-mail addresses are shown only to people who manage the diagram's sharing.

### API tokens

API tokens are off unless the deployment sets `MIDENA_API_TOKENS_ENABLED=true`: off, no token is accepted or issued, and tokens issued earlier can still be listed and revoked. An administrator issues an API token for one account under Administration, API tokens (MOSP's `/v1/admin/api-tokens`), so another application, such as KEEN, can read diagrams as that account. The token is sent as `Authorization: Bearer midena_at_…`, and a request carrying one acts as its account with that account's current role, permissions and shares, for the reads `MIDENA_POLICY.token_reads` lists: listing diagrams and opening one (`GET /v1/diagrams`, `GET /v1/diagrams/{uuid}`). Every other request carrying a token, every write among them, is refused before any route runs, and the request's cookies are not read. A token is 256 random bits shown once; MIDENA keeps its SHA-256 digest and its last four characters. It stops working when revoked, when it expires (30 days to a year, or never) and while its account is inactive; deleting the account deletes its tokens, and deactivating it revokes them in the same transaction, so they stay revoked if the account is activated again. The account's own password, second factors and SSO identities are separate credentials: changing or resetting them leaves its tokens as they are, and revoking a token is what ends it. Each token has its own allowance of 600 reads a minute, counted only after it verifies. The account's holder receives a security notice when a token is issued or revoked for it, and the token's last use is recorded to the minute. Requests made with a token are audited under the account's name. Tokens are redacted wherever MOSP redacts. A token for an administrator, or for an account holding `diagram.read_private`, reads private diagrams; issue tokens for an account holding only the access the reading application needs.

### Public diagrams

A public diagram is reached by its UUID and a random public token together (`/public/diagrams/{uuid}/{token}.html`, `/embed/{uuid}/{token}`, and the API's `/v1/public/diagrams/{uuid}/{token}` with `/source` and `/svg`). Tokens are compared in constant time, every refusal is the same 404, and a diagram that leaves `public` gets a new token, so a link once shared stops working when the diagram is made private and does not return if it is made public again. The public answer is a projection: diagram content, chrome and tags, with no account names, e-mail addresses, comments, shares or internal identifiers. The `public_diagrams` feature switch turns every public route off at once. The token appears in the page address; audit rows record public and embed paths with the token replaced by `REDACTED`, and the referrer policy sends other sites the origin only.

The embed page is the only page another site may frame (`frame-ancestors *`); it runs no account code and makes its one API request without credentials. Every other page allows framing by MIDENA itself only, and API responses forbid framing entirely.

### Roles, permissions and features

Accounts follow MOSP's model: an account is an administrator, an ordinary account, or takes its role from its groups (`inherit`); a group is an administrator group, an ordinary group, or carries no role. What an ordinary account may do comes from the permissions granted to it directly and through its groups: `diagram.read_private`, `diagram.write`, `diagram.comment`, `diagram.export`, `folder.manage` and `audittrail.read`. Administrators hold every permission. A change that would leave no active administrator, counting those who are administrators through a group, is refused under a lock that serialises such changes.

Feature switches (`core/features.py`: `public_diagrams`, `ai_generation`, `google_drive_export`) are managed on the Administration page within the ceiling the deployment's `MIDENA_FEATURE_*` settings set; a disabled feature's routes answer 404. Each save is checked against the stored configuration version under a row lock and kept as a revision naming who saved it.

## Integrations

### Google Drive export

Exports to Google Drive use a service account configured by the operator (`MIDENA_GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON` or `_FILE`, optional domain-wide delegation user) and upload into the one folder `MIDENA_GOOGLE_DRIVE_FOLDER_ID` names; a request cannot choose another destination. The API signs its own RS256 JWT bearer assertion and talks only to Google's fixed token and upload endpoints, with redirects off, the environment's proxy settings ignored, a bounded answer (64 KiB) and a configured timeout. An export needs read access to the diagram and `diagram.export`; source and SVG exports are built on the server from the stored diagram, and browser-rendered PNG, JPG and PDF exports are checked by their magic bytes and capped at 8 MiB. Exports count against a per-user hourly allowance (`MIDENA_GOOGLE_DRIVE_EXPORTS_PER_HOUR`, 30 by default) and each one is recorded in the diagram's change history. The link returned to the browser must be an HTTPS `drive.google.com` or `docs.google.com` address. Errors name the failure without Google's response body.

### AI-assisted generation

AI generation is opt-in per action and runs on the server only; the API key never reaches the browser. `MIDENA_AI_API_BASE_URL` must be HTTPS (plain HTTP only on localhost) and may carry no credentials, query or fragment. The request follows no redirects, reads at most 1 MiB of answer, and has a timeout (`MIDENA_AI_TIMEOUT_SECONDS`). Each user draws on an allowance (`MIDENA_AI_RATE_LIMIT_ATTEMPTS` per `MIDENA_AI_RATE_LIMIT_WINDOW_SECONDS`). Generated source passes the same validation as typed source before the browser sees it, and errors report only the provider's status code. The prompt and any current diagram source go to the configured provider when a user asks.

## Browser boundaries

### CSRF and Origin

Every unsafe request (POST, PUT, PATCH, DELETE) must come from MIDENA's own origin: `Origin` must equal `MIDENA_PUBLIC_BASE_URL`, and a write without `Origin` is refused, since every browser MIDENA serves sends it. The origin check also covers sign-in and second-factor steps, which have no CSRF token yet. Every signed-in unsafe request also needs the CSRF header matching the CSRF cookie, and the token must be the one issued with the session, so another session's token or a cookie planted from a sibling site proves nothing. Notification WebSockets need the same origin and a signed-in session, are limited per user and per address, end when their session ends (checked at least every 30 seconds) and accept no frames larger than 1 KiB.

### Request limits

MOSP reads each request body in full, within 30 seconds, before any middleware or route sees it: credential forms take at most 16 KiB, second-factor ceremonies 256 KiB, diagram creation and saves 8 MiB, Google Drive exports 12 MiB, and everything else 2 MiB (`app/mosp_hooks.body_limit`). JSON bodies must be standard JSON with finite numbers, at most 64 levels of nesting and at most 20,000 values; NUL characters, which PostgreSQL cannot store, become U+FFFD. A BPMN document or SVG is read whole only up to 3 MiB. Request targets carrying NUL, dot segments or encoded `/` or `\` are refused. Every integer in a path, query or body is bounded to PostgreSQL's integer range before it reaches a query, and a value the database still refuses is answered 400. Validation errors name invalid fields without echoing submitted values.

### Rendering, links and navigation

First-party JavaScript renders untrusted text through `escapeHtml` or `textContent`; the remaining HTML insertion sites are recorded and reviewed in `services/ui/tests/eslint-suppressions.json`, and the `no-unsanitized` lint rule refuses new ones. Links run through `safeHref` (pages) and `safeLinkUrl` (rendered diagrams), which drop script, data and other schemes, protocol-relative URLs, backslashes and control characters. Post-authentication destinations are paths on MIDENA's own site, validated through `same_site_path` on the server and the matching rule in the browser.

### Proxy, headers and caching

The supplied nginx adds the security-header set (X-Content-Type-Options, X-Frame-Options, Referrer-Policy `strict-origin-when-cross-origin`, COOP, HSTS, a `default-src 'self'` CSP with `script-src 'self'` and `img-src 'self' data: blob:`, and a Permissions-Policy denying camera, microphone and geolocation), refuses `//`-prefixed request targets, serves the API and its notification socket under `/api/` (passing the API the request target as the browser sent it, less the prefix, and refusing one that only normalises to `/api/`), clears client-supplied identity headers there, and marks every API response `no-store`. The API sets its own headers on every response, whatever proxy sits in front: `nosniff`, `X-Frame-Options: DENY`, cross-origin resource, opener and embedder policies, `no-store`, HSTS over HTTPS, and, on every response that sets no policy of its own, a CSP of `default-src 'none'; frame-ancestors 'none'; sandbox`, so an API answer opened directly runs nothing. The page check that nginx's `auth_request` reads names the account in a header, percent-encoding anything outside printable ASCII.

### Downloads and exports

Downloads are attachments with fixed, escaped names. Source and SVG downloads are typed `application/octet-stream` (only passive types such as PNG and PDF keep their own), so a browser saves a hostile file without rendering it. PNG, JPG and PDF exports are rendered in the browser from the filtered SVG.

## Background work

Celery workers deliver mail and run maintenance only, with JSON serialisation and per-task time limits (`MIDENA_TASK_TIME_LIMIT_SECONDS`). The beat-scheduled sweeper deletes expired sign-in states, second-factor challenges, SSO address proofs and diagram locks, and audit rows past `MIDENA_AUDIT_LOG_RETENTION_DAYS` (90 by default). Sessions, sign-in throttles and allowances live in Valkey and expire there.

## Secrets, redaction and logging

Runtime secrets (database and broker passwords, SMTP credentials, provider client secrets, the Google service account, the AI key, the second-factor encryption key) live in the environment, and Compose requires the critical ones through `:?` guards. The example environment file ships every credential empty. Stored query strings, referers and error text redact credentials through the shared sensitive-key list; configure further keys through `MIDENA_SENSITIVE_KEYS`. Redaction is best effort: keep secrets out of diagram names, descriptions, comments and content.

Request audit rows record client address, method, redacted path and query, status and duration, with fixed caps. Requests from signed-in accounts are always recorded; anonymous requests add at most 60 rows a minute per client address per API process. Each sign-in attempt adds one row naming the account it reached; a name matching no account is never stored. **Accepted risk:** an attacker with many addresses can still add anonymous audit rows at that rate; retention bounds how long they stay.

## Deployment posture

The Compose file pins every third-party image by digest (`tools/docker_image_pins.py`, with a scheduled workflow proposing updates through reviewed pull requests), and the GitHub Actions workflows pin every third-party action by commit. The UI build installs packages with `npm ci --ignore-scripts`, pins the MOSP Design System by commit, and refuses a git package whose tree differs from the reviewed record in `services/ui/scripts/reviewed-git-packages.json`. The API, worker and beat containers run as a non-root user with every Linux capability dropped and `no-new-privileges`; the API and worker root filesystems are read-only. The API publishes no port and serves no schema or interactive documentation; it is reached through the UI container's nginx. The Compose network has a fixed subnet so the trusted-proxy list names exactly the proxy and the gateway.

## Post-quantum cryptography

Browser, SMTP, identity provider, Google and AI provider traffic relies on TLS alone; its post-quantum posture follows what both ends negotiate. Stored secrets are hashed with PBKDF2-SHA256 or SHA-256, or encrypted with Fernet (AES-128), whose symmetric strength Grover's algorithm halves without breaking.

## Required security review checklist

Reviewers check these boundaries after every round of changes and before a release. A green suite establishes only the behaviours it exercises. Record each applicable check's evidence, untested prerequisites and remaining limitations; do not mark an untested boundary as verified. Use synthetic credentials, local fixtures and disposable databases, and review the final working tree.

- **Account discovery and timing:** compare existing, absent, inactive and SSO-only accounts on sign-in, linking, sharing and user search. Check bodies, status codes and expensive operations as well as timing.
- **Route inventory:** every served route has a rule in `app/security/route_policy.py` or MOSP's policy; exercise permitted users, users without the permission, other owners, inactive accounts and anonymous callers, including adjacent paths, extra segments, wrong methods and encoded separators.
- **Diagram visibility:** for each representation of a diagram (detail, listing, search, tags, versions, comments, links, changelog, exports, public projection, Drive export, API token reads), check that a reader without access learns nothing, and that a diagram leaving `public` invalidates its old links.
- **API tokens:** a token reaches only `token_reads`, never a write, an administration route or a WebSocket; revoked, expired and deactivated-account tokens are refused alike; a token request ignores the session cookie; the token never appears in the database, listings, notices, audit rows or logs.
- **Hostile content:** run hostile BPMN (DTD, entities, processing instructions, billion-laughs, deep nesting), Mermaid (directives, HTML labels, click handlers) and SVG (scripts, `foreignObject`, event handlers, external `href`, CSS `url()`/`@import`/escapes) through save, render, public view, embed and export.
- **CSRF, Origin and cookies:** cross-site GET and POST, missing and wrong tokens, another session's token, sibling-domain cookie injection, duplicate cookies, and the embed page's frame policy.
- **Sessions, second factors and linking:** fixation, replay, concurrent revocation, deactivation and reactivation, pending-ceremony confusion, OIDC issuer, audience, nonce, PKCE and browser binding, and verified-address linking.
- **Outbound destinations:** identity provider, Google and AI requests keep their fixed or validated destinations, refuse redirects, ignore proxy environment variables, bound their answers and keep provider bodies out of errors.
- **Resources:** body classes, JSON shape, integer bounds, SVG and XML size, regular expressions on the costliest accepted input at the largest accepted size, AI and Drive allowances.
- **Logs and redaction:** trace passwords, tokens, public diagram tokens and one-time links through URLs, referers, audit rows, errors, mail and exports.
- **Supply chain:** image digests, action commits, the reviewed git-package tree and `--ignore-scripts` installs.
- **Class sweeps:** for each confirmed issue, record the property it violates, the search that found every path sharing it, and the contract test that enforces it across the codebase.

The full validation workflow uses PostgreSQL. jsdom page tests and mocked transports are focused checks with a narrower reach: real-browser rendering, the built Docker images and resistance to sustained distributed attacks lie outside them, and need their own verification.
