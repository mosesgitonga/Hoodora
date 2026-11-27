# Deployment

How to run Hoodora on a single VPS: Caddy for TLS, the API and worker containers,
PostgreSQL with PostGIS, and Redis, all from `docker-compose.prod.yml`. Media lives in
Cloudflare R2, SMS goes through Africa's Talking, and push goes through FCM.

This is sized for launch in one town. Its limits, and what to change first when they
are reached, are at the end.

## 1. The server

- **Size:** 4 vCPU, 8 GB RAM, 80 GB SSD. PostgreSQL gets most of the memory.
- **OS:** Ubuntu 24.04 LTS, with Docker Engine and the Compose plugin from Docker's
  own repository.
- **Firewall:** only 22 (SSH, keys only), 80 and 443 are open:

  ```sh
  ufw default deny incoming
  ufw allow 22/tcp && ufw allow 80/tcp && ufw allow 443/tcp && ufw allow 443/udp
  ufw enable
  ```

  Docker publishes ports past `ufw`, which is why only Caddy publishes any. PostgreSQL,
  Redis, the API and the worker are reachable on the internal Compose network only.
- **Time:** UTC, with NTP on (the Ubuntu default). Staff sign-in codes are time-based
  and are refused if the clock drifts more than 30 seconds.
- **DNS:** an `A` (and `AAAA`) record for the API domain, pointing at the server,
  before the first start. Caddy needs it to get a certificate.

## 2. Logs: 30 days, as the data map promises

The containers log to journald. Docker's default driver keeps logs forever, which
would break the retention the data map promises. Cap journald on the host:

```ini
# /etc/systemd/journald.conf.d/myradius.conf
[Journal]
MaxRetentionSec=30day
SystemMaxUse=4G
```

```sh
systemctl restart systemd-journald
```

Read a service's logs with `docker compose -f docker-compose.prod.yml logs api`, or
`journalctl CONTAINER_TAG=myradius-api`. Application logs are already redacted:
no phone numbers, tokens, coordinates or query strings.

## 3. Configuration and secrets

```sh
git clone https://github.com/mosesgitonga/radius.git /srv/myradius && cd /srv/myradius
cp .env.example .env.production && chmod 600 .env.production
mkdir -m 700 secrets backups
```

`.env.production` holds every secret. It is never committed (`.gitignore`) and never
copied into an image (`.dockerignore`). Settings that must change from the template:

| Setting | Value |
| --- | --- |
| `APP_ENV` | `production` (the app refuses development defaults when this is set) |
| `DEBUG` | `false` |
| `SECRET_KEY` | `python3 -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `BAN_LIST_KEY` | Another value made the same way. Keep it when rotating `SECRET_KEY`. |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | A long random password |
| `DATABASE_URL` | `postgresql+asyncpg://USER:PASSWORD@postgres:5432/DB` |
| `REDIS_URL` | `redis://redis:6379/0` |
| `LOG_FORMAT` | `json` |
| `CORS_ORIGINS` | Empty for the mobile app. Set it only for a browser client. |
| `SMS_PROVIDER`, `AFRICASTALKING_*` | `africastalking`, with the account's credentials |
| `GOOGLE_CLIENT_ID` | The Firebase project's **web** OAuth client ID, to turn Google sign-in on. Empty leaves it off (decision A.1) |
| `STORAGE_PROVIDER`, `STORAGE_*` | `s3`, with R2's endpoint, bucket and keys |
| `PUSH_PROVIDER`, `FCM_CREDENTIALS_FILE` | `fcm`, `/run/secrets/myradius/fcm.json` |
| `SENTRY_DSN` | The project's DSN, or empty to leave error tracking off |
| `METRICS_TOKEN` | A random token, if Prometheus will scrape the API |
| `WORKER_METRICS_PORT` | `9100`, if Prometheus will scrape the worker |
| `API_DOMAIN`, `ACME_EMAIL` | For Caddy: the API's domain, and where Let's Encrypt writes |
| `BACKUP_BUCKET`, `BACKUP_ENDPOINT_URL`, `BACKUP_ACCESS_KEY_ID`, `BACKUP_SECRET_ACCESS_KEY` | A **separate, private** R2 bucket and keys, for off-site dumps |

The Firebase service-account file goes in `secrets/`, readable only by the container
user (UID 1001):

```sh
install -m 600 -o 1001 -g 1001 /path/to/firebase.json secrets/fcm.json
```

## 4. First start

```sh
docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build
docker compose -f docker-compose.prod.yml ps        # all healthy?
curl https://API_DOMAIN/health
```

The API applies migrations as it starts. Then, once:

```sh
# The areas whose names labels are made from: one GeoJSON file per town.
docker compose -f docker-compose.prod.yml exec api python -m scripts.seed_areas seeds/areas/nyeri.geojson

# The places Home names as "near Gatitu" (decision L.4). The file is not in the
# repository; copy it in first. Re-running replaces the county's places.
docker compose -f docker-compose.prod.yml cp nyeri_places.geojson api:/tmp/nyeri_places.geojson
docker compose -f docker-compose.prod.yml exec api python -m scripts.seed_places /tmp/nyeri_places.geojson

# The first admin. Prints a temporary password and an authenticator secret, once.
docker compose -f docker-compose.prod.yml exec api python -m scripts.create_admin --email you@example.com --name "Your Name"
```

Sign in at `POST /v1/admin/auth/sign-in`, change the password at
`POST /v1/admin/me/password`, and create moderator accounts at `POST /v1/admin/staff`.
The bootstrap script refuses to run again once an admin exists.

## 5. Updating

```sh
git pull
docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build
```

The API migrates before it serves, and every migration has been run down and up on
an empty database in CI. Take a backup first (`scripts/backup.sh`) when a release
includes a migration.

## 6. Backups, and proving they restore

`scripts/backup.sh` dumps the database (`pg_dump`, custom format), checks the dump
reads back, keeps 14 days locally, and copies each dump to the backup bucket when
`BACKUP_BUCKET` is set. Schedule it from root's crontab:

```cron
15 1 * * * cd /srv/myradius && scripts/backup.sh >> /var/log/myradius-backup.log 2>&1
45 1 * * 0 cd /srv/myradius && scripts/restore_test.sh >> /var/log/myradius-backup.log 2>&1
```

`scripts/restore_test.sh` restores the newest dump into a scratch database next to the
live one. It compares the migration revision and every table's row count, then drops
the scratch database, and exits non-zero on any difference. It runs weekly, at a
quiet hour, so rows written since the dump don't show up as differences.

To restore for real, onto a fresh server:

```sh
# Fetch the dump without starting the API, which would migrate an empty database.
docker compose -f docker-compose.prod.yml --env-file .env.production run --rm --no-deps -T api     python -m scripts.backup_offsite get myradius-YYYYMMDDTHHMMSSZ.dump > restore.dump
docker compose -f docker-compose.prod.yml --env-file .env.production up -d postgres
docker compose -f docker-compose.prod.yml exec -T postgres     sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --exit-on-error' < restore.dump
docker compose -f docker-compose.prod.yml --env-file .env.production up -d
```

The dumps are personal data. `backups/` is mode 700 and the bucket must be private.
They age out with the 14-day retention, so a purged account is gone from backups two
weeks after it is gone from the database. The data map states this.

**Redis is not backed up.** It holds only short-lived state: one-time codes, rate-limit
counters, presence, the job queue and the radius cache. Losing it signs nobody out
and loses no content. At worst it drops jobs that were queued and not yet run, and
the nightly sweeps catch those up.

## 7. Monitoring

- **Health:** `GET /health` (liveness) and `GET /ready` (database and Redis). Each
  container has a healthcheck, and Compose restarts anything that dies.
- **Errors:** Sentry, when `SENTRY_DSN` is set. Events are scrubbed by the log
  redaction rules, and carry no headers, query strings, bodies, local variables or
  IP addresses.
- **Metrics:** the API at `http://api:8000/metrics` (bearer `METRICS_TOKEN`) and the
  worker at `http://worker:9100/`, both on the internal network. Caddy returns 404
  for `/metrics` from outside. Alerts worth having from day one:
  - `myradius_worker_job_last_success_timestamp_seconds{task="refresh_density"}` older
    than 1 hour: radii are going stale.
  - The same for `send_event_reminders` (5 minutes), `run_retention` (26 hours),
    `recompute_badges` (26 hours).
  - p95 of `myradius_http_request_duration_seconds` above 500 ms for 10 minutes.
  - Rate of 5xx responses in `myradius_http_requests_total` above 1%.

## 8. Limits of this setup

One machine is one failure domain. Backups and the restore test bound the damage, at
the cost of up to a day's data and the time to rebuild. Once the launch town outgrows
one machine, change these first, in this order:

1. **Managed PostgreSQL**, with point-in-time recovery, in place of the container and
   nightly dumps.
2. **A second API host** behind a load balancer. Run migrations as a separate step
   (`RUN_MIGRATIONS=false`, then `entrypoint.sh migrate`), so two containers don't
   race on the same upgrade.
3. **Managed Redis.** The realtime hub already fans out across processes through
   Redis, so more API hosts need no code change.

## 9. The shared VPS (staging, from 2026-11-06)

Hoodora staging runs on 77.237.238.14 at **https://myradius.chatara.co**. The
server is shared: it also runs other projects behind their own nginx, which owns
ports 80 and 443, plus its own PostgreSQL and Redis on loopback. So the setup
differs from the sections above. Nothing here touches the other projects.

- **No Caddy.** `docker-compose.vps.yml` layers over the production file:
  - it switches Caddy off;
  - it publishes the API on `127.0.0.1:8031` and object storage on
    `127.0.0.1:8032`.
  nginx proxies both, using `deploy/vps/nginx-myradius.conf`, installed as
  `/etc/nginx/sites-available/myradius.chatara.co`. certbot adds TLS to it.
- **Photos stay on the server,** in SeaweedFS (`storage`). Its keys are in
  `secrets/s3.json`. Clients reach it by presigned URL at
  `https://myradius.chatara.co/myradius-media/…`.
- **Staging mode.** `APP_ENV=staging` with `SMS_PROVIDER=console`, so sign-in
  codes are written to the API log (`docker compose … logs api | grep
  sms_not_sent`). Switch to production once Africa's Talking is set up.
- **Setup.** `deploy/vps/bootstrap.sh`, run once as root, creates:
  - the checkout in `/srv/myradius`;
  - `.env.production` with fresh secrets, and `secrets/s3.json`;
  - the deploy gate;
  - the nginx site.
- **Logs.** journald's retention is the host's, shared with the other projects,
  and was left as it was. Section 2's 30-day cap has not been applied here.

### Media CDN (decision U.2, from 2026-11-24)

Photos reach phones through a Bunny pull zone, `hoodora-staging-media` (zone
7076924), at `https://media.myradius.chatara.co`, a CNAME to
`hoodora-staging-media.b-cdn.net` set at Namecheap. The Bunny account and its
billing are the product owner's.

- **Secrets, all only in `/srv/myradius/.env.production` (600, root):**
  - `BUNNY_API_KEY`: the account key, used to purge deleted media and to manage
    the zone;
  - `BUNNY_TOKEN_KEY`: the zone's token key, which signs every media URL;
  - `CDN_ORIGIN_SECRET`: the header value the zone sends to the origin.
  - None of them is in the repository or any other file.
- **The zone:**
  - token authentication on;
  - query strings ignored in the cache key, so one cached copy serves every
    token;
  - a year at the edge, since variants never change;
  - cookies stripped;
  - IP addresses dropped from its logs;
  - one edge rule that adds `X-Hoodora-Cdn: <CDN_ORIGIN_SECRET>` to origin
    requests.
- **The origin** is `https://myradius.chatara.co/cdn-origin/<key>`, a location
  in Hoodora's nginx site.
  - It answers only GETs for a variant's key shape, and only with the secret
    header.
  - It reads from the storage filer on `127.0.0.1:8033`, which is published to
    localhost only.
  - The secret reaches nginx through `/etc/nginx/snippets/myradius-cdn-origin.conf`
    (600, root), which `bootstrap.sh` writes from `CDN_ORIGIN_SECRET`. It is an
    `if` included in the location, not a `map`: a 64-character key overflows
    nginx's default `map_hash_bucket_size`, and raising that would be a
    server-wide change.
  - The live site file was edited by hand to match the template, since certbot
    owns it, and checked with `nginx -t` before reloading.
- **The API:** `STORAGE_PUBLIC_BASE_URL=https://media.myradius.chatara.co` and
  `BUNNY_TOKEN_KEY` turn signing on. `MEDIA_TOKEN_TTL_PUBLIC_SECONDS` (a week)
  and `MEDIA_TOKEN_TTL_PRIVATE_SECONDS` (an hour) set the lifetimes. Uploads
  still use presigned PUTs to `/myradius-media/`.
- **HTTP/2** comes from Bunny's edge. Hoodora's nginx stays on HTTP/1.1,
  because on nginx 1.24 turning HTTP/2 on applies to every site sharing port
  443 (decision U.1).
- **Rolling back:** empty `STORAGE_PUBLIC_BASE_URL` and `BUNNY_TOKEN_KEY` and
  restart `api` and `worker`. Photos go back to presigned URLs straight away.

### Domains (decision D.10, from 2026-11-27)

| Name | Serves | DNS |
| --- | --- | --- |
| `api.hoodora.one` | the API, uploads (`/myradius-media/`) and the CDN's origin (`/cdn-origin/`) | `A 77.237.238.14` |
| `hoodora-admin.hoodora.one` | the admin dashboard | `A 77.237.238.14` |
| `media.hoodora.one` | photos, through the Bunny pull zone | `CNAME hoodora-staging-media.b-cdn.net` |

- **The old names still answer** (`myradius.chatara.co`,
  `myradius-admin.chatara.co`, `media.myradius.chatara.co`), from the same nginx
  sites and certificates. The site files keep their old names:
  `/etc/nginx/sites-available/myradius.chatara.co` and
  `myradius-admin.chatara.co`.
- **Adding a name to a site:** add it to the site's `server_name` lines, run
  `nginx -t && systemctl reload nginx`, then expand that site's certificate:
  ```sh
  certbot --nginx --cert-name myradius.chatara.co -d myradius.chatara.co -d api.hoodora.one --expand --redirect
  ```
- **Settings that name the domain,** in `.env.production`:
  - `STORAGE_PRESIGN_ENDPOINT_URL` (uploads);
  - `STORAGE_PUBLIC_BASE_URL` (the photo CDN);
  - `ADMIN_CORS_ORIGINS`;
  - `ADMIN_API_BASE_URL` (what the dashboard is built to call);
  - `API_DOMAIN`.

### Admin dashboard (decision D.6, from 2026-11-25)

The moderation dashboard (`admin/`) is static files on its own subdomain. It
calls the API at `https://myradius.chatara.co`, which allows its origin on
`/v1/admin` only.

**On the server:**

| What | Where |
| --- | --- |
| The site | `/etc/nginx/sites-available/myradius-admin.chatara.co`, from `deploy/vps/nginx-myradius-admin.conf` |
| Its files | `/srv/myradius-admin/current`, a symlink to `releases/<sha>` (the last three are kept) |
| The IP allowlist | `/etc/nginx/snippets/myradius-admin-allow.conf`, included by the dashboard's site and by the API's `location /v1/admin/` |
| The API's setting | `ADMIN_CORS_ORIGINS=https://myradius-admin.chatara.co` in `.env.production` |

**Setting it up, once:**

1. **DNS (the product owner's job).** Add this record where `chatara.co` is
   managed:

   | Name | Type | Value | Proxy |
   | --- | --- | --- | --- |
   | `myradius-admin` | `A` | `77.237.238.14` | DNS only |

   There is no AAAA record: the server is reached over IPv4, like
   `myradius.chatara.co`.
2. **The site, the allowlist and the releases folder.** `bootstrap.sh`
   installs all three, or install them by hand. Either way, test before reloading,
   because the other projects' sites share this nginx:
   ```sh
   nginx -t && systemctl reload nginx
   ```
3. **The certificate,** once the name resolves to the server:
   ```sh
   certbot --nginx -d myradius-admin.chatara.co
   ```
   It adds the TLS lines and the HTTP-to-HTTPS redirect to the site file.
4. **The API's setting.** Set `ADMIN_CORS_ORIGINS` in `.env.production`. The next
   deploy picks it up, or run `docker compose ... up -d api`.
5. **Sign-in codes (decision D.7).** On unless `STAFF_TOTP_REQUIRED=false` is in
   `.env.production`, as it is on staging for now. To turn them back on, remove
   that line or set it to `true`, then redeploy.

**Each deploy:**
- `deploy.sh` builds `admin/` for the commit, in `node:24.22.3-alpine`, before
  the API restarts. A failed build stops the deploy with nothing changed.
- Once `/ready` answers, it moves `current` to the new build.
- The API address the build calls comes from `ADMIN_API_BASE_URL` in
  `.env.production`, defaulting to `https://myradius.chatara.co`.

**The headers,** to check after any change:
```sh
curl -sI https://myradius-admin.chatara.co/ | grep -iE 'content-security|x-frame|referrer|robots'
```
- The CSP carries a fresh `nonce-…` on every request, and the same value is in
  the page's `csp-nonce` meta (decision D.5).
- `index.html` is served with `Cache-Control: no-cache`; `/assets/` is cached for a
  year.

**Turning the IP allowlist on.** It is off by default, because the product
owner's mobile IP changes. To restrict the dashboard and `/v1/admin` to fixed
addresses:
```sh
cat > /etc/nginx/snippets/myradius-admin-allow.conf <<'ALLOW'
allow 203.0.113.7;      # the office
allow 198.51.100.0/24;  # a VPN's range
deny all;
ALLOW
nginx -t && systemctl reload nginx
```
- Anyone else gets 403 from nginx, before the API sees the request.
- The mobile app is unaffected: it never calls `/v1/admin`.
- To turn it off again, leave only comments in the file and reload.
- If a changed IP locks you out, SSH in and edit the file: SSH isn't behind it.

### Continuous deployment

1. **CI first.** A push to `main` runs CI.
2. **The Deploy workflow** (`.github/workflows/deploy.yml`) runs only if CI
   passed, one deploy at a time, never cancelled.
3. **The SSH connection.** The workflow connects with a deploy key of its own.
   In `/root/.ssh/authorized_keys` that key is limited to one forced command,
   `/usr/local/bin/myradius-deploy` (`deploy/vps/deploy-gate.sh`), which:
   - accepts only `deploy <sha>`, and only for a commit on `origin/main`;
   - checks that commit out;
   - runs `deploy/vps/deploy.sh`.
4. **`deploy.sh`:**
   - builds the admin dashboard for the commit (decision D.6). A failed build
     stops here, with nothing changed;
   - backs up the database first if the release changes migrations;
   - runs `docker compose up -d --build`, and the API migrates as it starts;
   - waits for `/ready`. If it never comes, it checks the previous commit out,
     starts that again, and fails the workflow;
   - once the API is live, moves the dashboard's `current` to the new build.
5. **The final check:** the workflow then calls `https://myradius.chatara.co/ready`.

Repository secrets: `DEPLOY_SSH_KEY` (the deploy key's private half) and
`DEPLOY_KNOWN_HOSTS` (`ssh-keyscan 77.237.238.14`). Without them the workflow
skips with a warning. To deploy by hand, run **Actions → Deploy → Run workflow**,
or `ssh root@77.237.238.14 myradius-deploy "deploy $(git rev-parse origin/main)"`
from a machine with root's own key.
