# MIDENA

MIDENA is the Mapping, Integration, Diagram Editing and Navigation Application: a diagram workspace for BPMN process models, Mermaid flowcharts and Mermaid sequence diagrams. It shares its stack and security model with KEEN and OSPMAE through the myf framework: FastAPI, PostgreSQL, Valkey and Celery behind nginx, with static pages built on the MOSP Design System.

## Capabilities

- **Editing.** BPMN editing with `bpmn-js`; Mermaid flowchart and sequence editing with live preview, plus a visual builder for common flowchart shapes that writes Mermaid source.
- **AI-assisted drafting.** Optional generation of flowchart and sequence source through a server-side OpenAI-compatible endpoint. The provider key stays on the server, each user has an hourly allowance, and generated source is validated like typed source.
- **Versions and locks.** Every save creates an immutable version. A user locks a diagram while editing; locks expire, and administrators can clear them.
- **Organisation.** Folders, tags, search across names, descriptions, tags and folders, comments and per-element links to other systems.
- **Visibility and sharing.** Each diagram is `private`, `internal` (every signed-in user) or `public`. Diagrams are shared with named users as viewers or editors, with an e-mail notice to the recipient.
- **Public views and embeds.** A public diagram has a read-only page and an embeddable view, each addressed by the diagram's UUID and a random token. Making a diagram private again retires its links.
- **Export.** BPMN XML, Mermaid source and SVG from the server; PNG, JPG and PDF rendered in the browser; optional export of any of these to a Google Drive folder the operator configures.
- **Administration.** Accounts and groups, each an administrator, an ordinary account or (accounts only) taking its role from its groups, with permissions for what ordinary accounts may do; local and LDAP sign-in with TOTP and WebAuthn second factors; single sign-on through OpenID Connect, Google or GitHub for existing accounts; feature switches; diagram header, footer and theme; locks; the mail outboxes; request audit log and semantic change history.

## Running locally

```bash
cp .env.example .env
# Set every empty credential, MIDENA_PUBLIC_BASE_URL and MIDENA_MFA_ENCRYPTION_KEY.
# Set MIDENA_BOOTSTRAP_ADMIN_USERNAME and MIDENA_BOOTSTRAP_ADMIN_PASSWORD
# for the first administrator, and remove them after the first sign-in.
docker compose up --build
```

The UI listens on `127.0.0.1:8083` and PostgreSQL on `127.0.0.1:5445`. The API publishes no port; nginx in the UI container serves it under `/api/` (`/api/v1/...` and the notification socket at `/api/ws/notifications`), as KEEN's does. The UI build fetches the MOSP Design System at the commit pinned in `services/ui/package.json`.

## Configuration

Settings use the `MIDENA_` prefix; `.env.example` documents each one. The main groups are:

- `MIDENA_DATABASE_URL`, `REDIS_PASSWORD`, `MIDENA_REDIS_URL`, `MIDENA_CELERY_*`: storage, the Valkey store for sessions and allowances, and the broker.
- `MIDENA_PUBLIC_BASE_URL` (required): the origin browsers use, the only origin accepted for sign-in and writes, and the host of links in mail.
- `MIDENA_COOKIE_*`, `MIDENA_CSRF_*`, `MIDENA_SESSION_*`: sessions and CSRF. With Secure cookies and no cookie domain, cookies take the `__Host-` prefix.
- `MIDENA_LOCAL_AUTH_ENABLED`, `MIDENA_PASSWORD_MIN_LENGTH`, `MIDENA_MFA_POLICY`, `MIDENA_MFA_ENCRYPTION_KEY`, `MIDENA_LOGIN_RATE_LIMIT_*`: local sign-in, its limits and second factors.
- `MIDENA_OIDC_*`, `MIDENA_GOOGLE_*`, `MIDENA_GITHUB_*`, `MIDENA_LDAP_*`: single sign-on providers and directory sign-in.
- `MIDENA_SECURITY_TRUSTED_PROXY_CIDRS`, `MIDENA_TRUST_REMOTE_USER`, `MIDENA_REMOTE_USER_TRUSTED_CIDRS`: proxies and header authentication.
- `MIDENA_FEATURE_PUBLIC_DIAGRAMS`, `MIDENA_FEATURE_AI_GENERATION`, `MIDENA_FEATURE_GOOGLE_DRIVE_EXPORT`: the ceiling for the feature switches administrators manage.
- `MIDENA_GOOGLE_DRIVE_*`: the service account and destination folder for Drive export.
- `MIDENA_AI_*`: the AI endpoint (HTTPS), model, key, timeout and per-user allowance.
- `MIDENA_SMTP_*`: mail for share notices, security notices and address confirmation.
- `MIDENA_AUDIT_LOG_RETENTION_DAYS`: how long the request audit trail keeps its records.

## Development

- Backend tests: `MIDENA_TEST_DATABASE_URL=postgresql+psycopg://… bash tests.sh` against a disposable PostgreSQL database.
- UI tests: `npm ci --prefix services/ui/tests`, then `bash tests-ui.sh`.
- Linting and formatting: `ruff check`, `ruff format --check` and `mypy app` in `services/api`; `bash lint-ui.sh` and `bash format-ui.sh --check` at the root.
- `AGENTS.md` describes the code layout, shared helpers and invariants; `SECURITY.md` describes the security model and how to report a vulnerability.

## Licence

See `LICENSE`.
