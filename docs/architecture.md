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

## Ownership

- `frontend/` owns browser pages, shared styles, and browser-side behavior.
- `backend/` owns authentication, sessions, and user administration.
- `legacy/openproject/` retains the OpenProject control/proxy files. Root Compose manifests still refer to this directory and remain at the repository root to preserve existing project and volume names.
- `docs/` owns project documentation.

New portal pages should live under `frontend/` and link into the service directory from `frontend/index.html`. Keep API endpoints and session behavior in the backend; do not duplicate authentication logic in static pages.
