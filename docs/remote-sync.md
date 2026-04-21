# Remote Sync

This document describes [`v2/remote-diff-sync.sh`](../remote-diff-sync.sh), a small helper aligned with [`v2/deploy-backend.sh`](../deploy-backend.sh) and [`v2/deploy-frontend.sh`](../deploy-frontend.sh) (same SSH key, host, user, and default paths).

## Commands

| Command | Backend | Frontend |
|---------|---------|----------|
| `diff` | Dry-run: local `v2/backend/` vs remote app dir (rsync `-n`). Excludes `.env`, `.venv`, caches. | Dry-run: local `v2/frontend/dist/` vs remote web root. Requires `npm run build` first. |
| `pull` | Rsync **from** server **into** local `v2/backend/`. Remote `.env` is **not** pulled (exclude). | Rsync remote web root into `v2/frontend/dist-remote/`. |
| `push` | Rsync local backend **to** server (same excludes as deploy-backend; no venv/pip/systemd). | Rsync `dist/` to home staging, then remote `sudo rsync` into web root, `chown`, `nginx -t`, reload (same pattern as deploy-frontend). |

Examples:

```bash
chmod +x v2/remote-diff-sync.sh

./v2/remote-diff-sync.sh diff backend
./v2/remote-diff-sync.sh diff backend --checksum

./v2/remote-diff-sync.sh pull backend
./v2/remote-diff-sync.sh push backend

(cd v2/frontend && npm run build)
./v2/remote-diff-sync.sh diff frontend
./v2/remote-diff-sync.sh push frontend
```

## Environment variables

Same names as the deploy scripts where applicable:

| Variable | Role |
|----------|------|
| `ZENHEART_EC2_KEY` | PEM path (default `aws/zenheart-ec2.pem` under repo root) |
| `ZENHEART_EC2_HOST` | Server address |
| `ZENHEART_EC2_USER` | SSH user (default `ec2-user`) |
| `ZENHEART_V2_REMOTE_DIR` | Remote backend tree (default `/opt/zenheart/services/v2_backend`) |
| `ZENHEART_WEB_DIR` | Remote static site root (default `/opt/zenheart/frontend`) |
| `ZENHEART_V2_STAGING` | Home-relative staging directory for frontend push (default `zenheart-v2-frontend-dist`) |

## When to use deploy scripts instead

- **Backend**: after `push backend`, restart the service if Python code or entrypoints changed: `sudo systemctl restart zenheart-v2-backend`. For dependency or systemd changes, run `./v2/deploy-backend.sh`.
- **Frontend**: `push frontend` already reloads nginx on success. For a clean first-time install, still use `./v2/deploy-frontend.sh`.

## Safety

- `pull backend` can overwrite local files under `v2/backend/`. Commit or stash work first.
- `push backend` uses `--delete` on the remote tree side of the mirror; it matches deploy-backend behavior for code files but does not remove server-only secrets if they live outside excluded paths.
- `diff` is read-only (rsync dry-run).
