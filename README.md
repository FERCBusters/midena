# MIDENA

MIDENA is the Mapping, Integration, Diagram Editing and Navigation Application. It follows the same FastAPI, Postgres, Valkey, Docker Compose and static Bootstrap/MOSP Design System pattern used by KEEN and OSPMAE, but replaces the OSPMAE catalogue domain with a BPMN diagram workspace.

## What this starter implements

- Browser BPMN editing with `bpmn-js` modeler assets vendored into the UI container.
- Browser Mermaid flowchart editing with live preview and an optional drag-and-drop visual builder for common flowchart nodes/connectors.
- Browser Mermaid sequence diagram editing with live preview.
- Optional AI-assisted Mermaid flowchart and sequence diagram generation through a server-side OpenAI-compatible API integration.
- Diagram records with UUIDs, friendly names, descriptions, tags, public/private visibility and folder placement.
- Immutable diagram versions: every save creates a new `diagram_versions` row and moves the diagram current-version pointer.
- Locking workflow: users can lock a diagram while editing; admins can forcibly clear active locks from the Admin UI.
- Folder hierarchy for organising diagrams, with admin/maintainer/architect/diagram_admin folder management.
- Search and filtering across diagram name, description, tags and folder.
- Public read-only views and embeddable views, guarded by `is_public`.
- Authenticated editor UI with comments and per-element entity links.
- Export controls for BPMN, flowchart source, sequence source, SVG, PNG, JPG and PDF. BPMN/SVG are available from the API; PNG/JPG/PDF are produced in-browser from the rendered SVG.
- Global diagram header/footer text managed from the Admin UI and applied to diagram/editor/embed views.
- OSPMAE-style users, groups, RBAC permissions, local login, password reset plumbing and SSO provider settings for generic OpenID Connect, Google and GitHub.
- Request audit logging plus semantic entity changelogs for diagrams, versions, folders, comments, entity links and admin actions.


## Mermaid flowchart visual builder

Flowchart diagrams include a **Visual editor** button in the editor toolbar. The visual builder is intentionally dependency-free and serialises its canvas back into Mermaid source so existing MIDENA versioning, validation, export, comments and entity-link behaviour continue to work.

The visual builder currently supports the common Mermaid flowchart subset: `flowchart` direction, process boxes, decision diamonds, start/end pills, database/data-store nodes, circles, arrows, plain lines, dotted arrows and optional connector labels. Users can drag nodes around the canvas, positions snap to the visible grid, connectors can be created by dragging the small handle on one node onto another node, and dragging on empty canvas draws a hatched selection region for selecting multiple nodes/connectors at once. The **Direction** selector changes the generated Mermaid direction while preserving manual positions; **Auto-layout** remains available when users want MIDENA to rearrange the graph. Complex Mermaid features such as subgraphs, class definitions, click handlers and styling directives remain editable in source mode; use **Load from source** when you want to reparse a simple source diagram into the visual builder.

## Not yet implemented

- Live collaborative editing is intentionally not implemented in this starter. The included lock/heartbeat model is the safe baseline and avoids concurrent write conflicts.
- The KEEN plug-in/embed package is not split out yet. The diagram routes and UI are deliberately isolated so they can later be mounted into KEEN with a reduced editor/viewer.
- PNG/JPG/PDF export is client-side only. Server-side rendering can be added later with a hardened headless renderer service if required.
- Comments are stored server-side, not embedded inside BPMN XML. This preserves MIDENA RBAC, audit trail, deletion and user-attribution semantics.

## Running locally

This repository expects the MOSP Design System to be available as a sibling directory when building the UI container:

```text
workspace/
  midena/
  mosp-design-system/
```

From the `midena/` directory:

```bash
cp .env.example .env
# Edit .env and replace all placeholder passwords and public URLs.
# Set MIDENA_BOOTSTRAP_ADMIN_USERNAME and MIDENA_BOOTSTRAP_ADMIN_PASSWORD
# for the first admin account, then remove them after the first login.
docker compose up --build
```

The default compose ports are:

- UI: `127.0.0.1:8083`
- API: `127.0.0.1:8183`
- Postgres: `127.0.0.1:5445`

## Important environment variables

MIDENA uses a `MIDENA_` environment prefix. The important groups are:

- `MIDENA_DATABASE_URL`: SQLAlchemy/Postgres connection string.
- `MIDENA_SESSION_COOKIE_NAME`, `MIDENA_COOKIE_SECURE`, `MIDENA_COOKIE_SAMESITE`, `MIDENA_CSRF_*`: session and CSRF controls.
- `MIDENA_LOCAL_AUTH_ENABLED`: enable/disable native password login.
- `MIDENA_BOOTSTRAP_ADMIN_USERNAME`, `MIDENA_BOOTSTRAP_ADMIN_PASSWORD`, `MIDENA_BOOTSTRAP_ADMIN_EMAIL`: optional first-run admin account creation. Existing users are never overwritten.
- `MIDENA_OIDC_*`, `MIDENA_GOOGLE_*`, `MIDENA_GITHUB_*`: SSO provider configuration.
- `MIDENA_*_AUTO_PROVISION`, `MIDENA_*_AUTO_LINK_EXISTING`, `MIDENA_*_ALLOWED_EMAIL_DOMAINS`, `MIDENA_*_USERNAME_CLAIMS`: controls for whether SSO users are created automatically, linked to existing users, restricted by email domain and mapped to usernames.
- `MIDENA_SMTP_*`: password-reset mail settings.
- `MIDENA_AI_*`: optional AI diagram generation settings. Set `MIDENA_AI_API_KEY`, `MIDENA_AI_MODEL` and, if needed, `MIDENA_AI_API_BASE_URL` for Regolo.ai or another OpenAI-compatible `/chat/completions` endpoint. The API key is used only by the backend and is never sent to the browser.
- `MIDENA_CELERY_*` and `REDIS_PASSWORD`: retained to match the KEEN/OSPMAE deployment topology and leave room for later scheduled/collaboration work.

## Security notes

- Private diagrams are only returned to authenticated users with private diagram read permission.
- Public embed and public view routes are read-only and only resolve diagrams with `is_public=true`.
- Diagram XML rejects DOCTYPE, ENTITY and XML stylesheet declarations before persistence.
- SVG is treated as data, not trusted HTML; obvious scripts and inline event handlers are stripped on save.
- All mutating API calls keep the existing CSRF/session pattern inherited from OSPMAE.
- AI diagram generation is opt-in per user action, rate-limited per user, server-side only, and validates generated source before returning it to the browser. Prompts and current diagram source are sent to the configured AI provider when the user clicks Ask AI.
- Semantic changelogs are created for diagram, version, folder, comment and entity-link changes.
