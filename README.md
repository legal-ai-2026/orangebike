# Orange Bike Brewing — Data Browser

Read-only web app for browsing the unified Orange Bike Brewing operational database.

**Public URL (production):** `https://orangebike.fresnelfabian.com/`
**Context:** ALY 6080 Integrated Experiential Learning, Roux Institute, Spring 2026

---

## What's in here

| Path | What it is |
|------|------------|
| `webapp/app.py` | Flask app — auth, data browser, SQL console, exports, suggestions |
| `webapp/wsgi.py` | gunicorn entry; mounts the app under `/orangebike` in production |
| `webapp/templates/` | Jinja templates (all URLs use `url_for` for subpath-safe routing) |
| `orange_bike.db` | Unified SQLite database (21 MB, 71,235 rows across 8 tables) |
| `data_dictionary.md` | Full per-column documentation |
| `OBB_DATA_SPEC.md` | Business context + schema + sample queries |
| `Dockerfile` | Production image (python:3.11-slim + gunicorn) |
| `requirements.txt` | Pinned Python deps |
| `k8s/deployment.yaml` | Deployment + Service (MetalLB) + PVC |
| `.woodpecker.yaml` | CI/CD pipeline (kaniko build + kubectl apply) |
| `DEPLOYMENT.md` | **Fresnel starts here** — one-time setup for the cluster |

---

## Features

- **Dashboard** with revenue trend, top SKUs, top wholesale accounts
- **Data Browser** — paginated, sortable, searchable view of every table
- **SQL Console** — run read-only `SELECT` queries, download results as CSV
- **Tableau Export** — bulk ZIP of all 8 tables as CSVs
- **Full database download** — grab the entire SQLite file
- **Suggestions** — class members submit change requests (persisted to the same DB)
- **Shared-password auth** via Flask session (`OBB_PASSWORD` env var)
- **Read-only mode** in production — write routes return 403 and redirect to Suggestions

---

## Running locally

```bash
pip install -r requirements.txt

# Dev mode, no subpath, not read-only (full editor)
OBB_PASSWORD=devpass \
SECRET_KEY=dev-secret \
READ_ONLY=false \
PORT=8080 \
python3 -m webapp.app

# Dev mode matching production behavior (subpath + read-only)
OBB_PASSWORD=devpass \
SECRET_KEY=dev-secret \
READ_ONLY=true \
URL_PREFIX=/orangebike \
python3 -c "from werkzeug.serving import run_simple; from webapp.wsgi import application; run_simple('0.0.0.0', 8080, application)"
```

Then visit `http://localhost:8080/` (or `http://localhost:8080/orangebike/` for subpath mode).

---

## Environment variables

| Var | Required | Default | Purpose |
|-----|----------|---------|---------|
| `OBB_PASSWORD` | **yes** | — | Shared login password |
| `SECRET_KEY` | **yes** | `dev-only-change-in-production` | Flask session signing |
| `READ_ONLY` | no | `false` | When `true`, POST endpoints are disabled (returns 403 / redirects to Suggestions) |
| `URL_PREFIX` | no | `""` | Mount app under this subpath (e.g. `/orangebike`) |
| `DB_DIR` | no | (repo root) | Directory holding the runtime SQLite DB. In prod, the PVC is mounted here |
| `UPLOADS_DIR` | no | `webapp/uploads/` | Where shelf-scan photos are saved |
| `SESSION_HOURS` | no | `12` | How long auth sessions last |
| `ANTHROPIC_API_KEY` | no | — | Enables Photo AI (disabled in read-only mode anyway) |
| `PORT` | no | `8080` | Dev server port only (prod uses gunicorn bind) |

---

## Deploy

See **[DEPLOYMENT.md](./DEPLOYMENT.md)** for the complete one-time setup: Woodpecker enablement, k8s Secret creation, Cloudflare Tunnel config, DNS, verification.

After initial setup, every push to `main` triggers a rebuild + redeploy.

---

## Security notes

- All routes require an authenticated session except `/login`, `/logout`, and `/health`
- The SQL console validates queries must start with `SELECT` / `WITH` / `PRAGMA` / `EXPLAIN` and blocks keywords: `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `CREATE`, `ATTACH`, `DETACH`, `REPLACE`, `VACUUM`
- PII fields (customer name, card PAN suffix) from the Square POS source were excluded at ETL time — they do not exist in the database
- Sessions use `HttpOnly` + `SameSite=Lax` cookies
- `ProxyFix` trusts `X-Forwarded-*` headers from the Cloudflare Tunnel edge — the Service is only reachable via the tunnel on public internet, so this is safe
