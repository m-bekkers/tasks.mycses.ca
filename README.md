# CSES Affiliates Portal

The portal is a static frontend with a small FastAPI authentication and administration API. The root page is the portal directory; the existing request workflow is available at `/requests/`.

## Project layout

```text
frontend/                 Static pages and shared styles/scripts
  index.html              Portal landing page
  requests/index.html     Request form and account controls
backend/                  FastAPI API, OAuth, and SQLite user store
docs/                     Architecture and operational notes
legacy/openproject/       OpenProject control and proxy assets retained for compatibility
```

Root Compose files are kept in place because the existing host deployment relies on their project directory and volume naming. The OpenProject stack is separate from the CSES portal API.

## Frontend

Serve the static site from `frontend/` with a web server configured to use `index.html` for `/` and directory indexes for `/requests/`. Shared frontend assets remain at the site root. The request form retains the existing Google sign-in, form validation feedback, administrator user list, and sign-out behavior.

## Backend

The API is in `backend/app.py`. It provides Google OAuth, session handling, user administration, and `/health`. Runtime credentials and database files belong outside the repository; see [backend/.env.example](backend/.env.example) for the required configuration names.

The existing deployment uses `docker-compose.backend.yml` to build the API and attach it to the external Caddy network. On a configured host, the API can be rebuilt with:

```sh
docker compose -f docker-compose.backend.yml up -d --build
```

## Deployment

The host's `/usr/local/sbin/deploy-tasks-site` script copies the frontend files to `/var/www/tasks.mycses.ca`. It now includes the nested request page. The script operates on a separate clone at `/home/bekkers/working/tasks-site-deploy`; publish the desired commit to `main` before running the deploy command.

The API deployment is separate from the static-site copy. Preserve the host-managed secrets under `/opt/tasks-portal/secrets/` and data under `/opt/tasks-portal/data/` when updating it.

## Legacy OpenProject stack

The root `docker-compose.yml`, `docker-compose.override.yml`, and `docker-compose.control.yml` belong to the retained OpenProject setup. Its control and proxy build contexts now point into `legacy/openproject/`. The original installation guide is preserved at [legacy/openproject/README.md](legacy/openproject/README.md).
