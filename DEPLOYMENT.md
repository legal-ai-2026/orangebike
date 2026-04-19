# Deployment Guide — Orange Bike Data Browser

**Target:** `https://crowdsaasing.com/orangebike/` (read-only, shared password)
**Cluster:** homelab Kubernetes, `staging` namespace
**Registry:** Zot at `192.168.0.247:5000`
**LoadBalancer IP:** `192.168.0.248` (MetalLB)
**CI:** Woodpecker @ `ci.fresnelfabian.com`

This follows the pattern in `ci-cd-deployment-guide.md` verbatim — Dockerfile, `k8s/deployment.yaml` (with `IMAGE_TAG` placeholder), and `.woodpecker.yaml` are all in place.

---

## One-time setup (Fresnel)

### 1. Enable repo in Woodpecker

- Visit `https://ci.fresnelfabian.com`
- "Add Repository" → "Reload repositories"
- Find `orangebike` (or whatever repo name Thomas uses) and click **Enable**

### 2. Create the k8s Secret with credentials

```bash
kubectl create secret generic orangebike-secrets -n staging \
  --from-literal=SECRET_KEY="$(openssl rand -hex 32)" \
  --from-literal=OBB_PASSWORD="<pick-a-class-password>" \
  --from-literal=ANTHROPIC_API_KEY=""
```

- `SECRET_KEY` — Flask session signing key. 32 random bytes is plenty.
- `OBB_PASSWORD` — the shared password class members will use to sign in. Coordinate with Thomas on what to use.
- `ANTHROPIC_API_KEY` — can be empty. Only needed if the photo-AI feature is turned on later (currently disabled in read-only mode).

### 3. Cloudflare Tunnel ingress rule

The existing tunnel serves `*.fresnelfabian.com`. Add a rule for `crowdsaasing.com` routing `/orangebike/*` to the MetalLB IP:

**If using the dashboard** (Zero Trust → Networks → Tunnels → [tunnel] → Public Hostname):
- Subdomain: (blank)
- Domain: `crowdsaasing.com`
- Path: `orangebike*` *(note: some UIs need `orangebike` without the leading slash)*
- Service: `HTTP://192.168.0.248:80`

**If using cloudflared config.yml directly**, add before the catch-all rule:

```yaml
ingress:
  # ... existing fresnelfabian.com rules ...

  - hostname: crowdsaasing.com
    path: /orangebike.*
    service: http://192.168.0.248:80

  # catch-all (keep last)
  - service: http_status:404
```

### 4. DNS

Cloudflare DNS for `crowdsaasing.com`:
- Type: `CNAME`
- Name: `@` (or `crowdsaasing.com`)
- Target: `<tunnel-id>.cfargotunnel.com` (same tunnel as Ignite — should already exist)
- Proxy: **Proxied (orange cloud)** — required for tunnel routing

Thomas owns the `crowdsaasing.com` zone. He'll need to add Cloudflare as the DNS provider if he hasn't already.

### 5. Push to trigger first deploy

```bash
git push origin main
```

Pipeline will:
1. kaniko builds image, pushes to `ci-cd-zot:5000/orangebike:<sha>`
2. kubectl substitutes `IMAGE_TAG` → commit SHA in `k8s/deployment.yaml`
3. Applies the manifest — creates PVC, Deployment, Service

---

## Verification

```bash
# Pipeline
# visit https://ci.fresnelfabian.com — should show green run

# Image in Zot
curl http://192.168.0.247:5000/v2/orangebike/tags/list

# Pod running
kubectl get pods -n staging -l app=orangebike
kubectl logs -n staging -l app=orangebike --tail=50

# Service
kubectl get svc -n staging orangebike
# -> EXTERNAL-IP should show 192.168.0.248

# Health inside network
curl http://192.168.0.248/orangebike/health
# -> {"ok": true, "read_only": true}

# Health via Cloudflare (after tunnel rule is added)
curl https://crowdsaasing.com/orangebike/health
# -> {"ok": true, "read_only": true}
```

Then in a browser, visit `https://crowdsaasing.com/orangebike/` — you should land on the login page.

---

## Architecture notes

- **Why a PVC?** Class suggestions submitted via the `/orangebike/suggestions` page persist to the same SQLite DB. The bundled DB at `/app/orange_bike.db` is copied to `/data/orange_bike.db` on first pod boot if `/data` is empty. Subsequent pods reuse the persisted DB. Storage: 1Gi.

- **Why `Recreate` strategy?** The PVC is ReadWriteOnce — only one pod at a time can mount it. Rolling updates would fail.

- **Why subpath mount instead of a subdomain?** The user owns `crowdsaasing.com` and wants `/orangebike` specifically. `webapp/wsgi.py` uses `DispatcherMiddleware` to mount Flask at the `URL_PREFIX` env var, which is set to `/orangebike` in the Dockerfile. Flask's `url_for()` automatically generates prefixed URLs. JavaScript uses a `window.URL_PREFIX` variable set from `request.script_root`.

- **Auth model:** Shared password in `OBB_PASSWORD`. Cookie-backed session via Flask. 12-hour expiry. Every route except `/login`, `/logout`, `/health` requires a valid session.

- **Read-only enforcement:** `READ_ONLY=true` is baked into the Dockerfile. All POST handlers that mutate data are wrapped in a `@require_write` decorator that returns 403 / flashes a redirect to `/suggestions` when read-only.

- **What's still writable in read-only mode?** Only the `suggestions` table (via `/orangebike/suggestions`) and authentication (session writes). The Photo AI upload form is hidden from the nav entirely when read-only.

---

## Future updates

Every push to `main` triggers a rebuild and redeploy via Woodpecker. Just edit, commit, push.

To rebuild the underlying dataset (e.g., after Thomas refreshes the Square exports):

1. Run `etl_pipeline.py` locally in the `Data/` workspace to regenerate `orange_bike.db`
2. Copy the fresh DB to the repo root
3. Commit + push → image rebuild → pod restart

**Important:** a fresh deploy alone will NOT replace the PVC's `orange_bike.db` (the copy-on-first-boot logic only triggers when `/data/orange_bike.db` is absent). To force-replace:

```bash
kubectl delete pvc orangebike-data -n staging
# wait for the PVC to be cleaned up, then
kubectl rollout restart deployment/orangebike -n staging
```

The next pod boot will re-copy the bundled DB. **This wipes suggestions.** For an in-place refresh that keeps suggestions, exec into the pod and overwrite `/data/orange_bike.db` manually, or add a migration step to the container entrypoint.
