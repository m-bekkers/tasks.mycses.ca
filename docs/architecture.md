# Portal architecture

## Request flow

| Path | Owner | Purpose |
| --- | --- | --- |
| `/` | Static frontend | Portal landing page and service directory |
| `/requests/` | Static frontend | Existing request form, sign-in controls, and admin view |
| `/auth/*` | FastAPI backend | Google OAuth and logout |
| `/api/*` | FastAPI backend | Current-user and administrator APIs |
| `/health` | FastAPI backend | Container health check |

Caddy routes `/auth/*`, `/api/*`, and `/health` to the backend; other paths are served by the static frontend. The request page loads shared assets from the frontend root, so it works at the nested `/requests/` path without duplicating styles or scripts.

## Work item flow

Authenticated users submit request form data to `POST /api/requests`. The backend adds the authenticated account identity and creates a work package in the configured OpenProject project. Admin-only `GET /api/admin/work-packages` lists open work packages and their editable status, priority, and assignee options. `PATCH /api/admin/work-packages/{id}` updates allowed fields using the work package lock version.

OpenProject API credentials are held only in the backend's environment. The configured integration account needs project membership and permissions to view, create, and edit work packages. The browser never receives the API key.

## Ownership

- `frontend/` owns browser pages, shared styles, and browser-side behavior.
- `backend/` owns authentication, sessions, and user administration.
- `legacy/openproject/` retains the OpenProject control/proxy files. Root Compose manifests still refer to this directory and remain at the repository root to preserve existing project and volume names.
- `docs/` owns project documentation.

New portal pages should live under `frontend/` and link into the service directory from `frontend/index.html`. Keep API endpoints and session behavior in the backend; do not duplicate authentication logic in static pages.
