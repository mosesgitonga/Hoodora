#!/usr/bin/env bash
#
# Deploy a commit that deploy-gate.sh has already checked out in /srv/myradius:
#
#   deploy/vps/deploy.sh <sha> <previous sha>
#
# 1. builds the admin dashboard's static files for this commit (decision D.6),
#    beside the live ones, so a failed build stops the deploy before anything
#    changes;
# 2. backs up the database first if the release adds a migration;
# 3. rebuilds the image and restarts what changed (the API migrates as it starts);
# 4. waits for /ready; if it never comes, checks out the previous commit and
#    starts that again, and exits non-zero so CI shows the deploy failed;
# 5. once the API is live, points the dashboard's `current` at the new build, and
#    keeps the last three builds.
#
# A rollback restores the code, not the schema: a migration that ran stays applied.
# Every migration is reversible and run down and up in CI, so after a failed
# release with a migration, downgrade by hand if the old code needs it.
set -euo pipefail

sha="$1"
previous="$2"
cd /srv/myradius

compose() {
  docker compose -f docker-compose.prod.yml -f docker-compose.vps.yml \
    --env-file .env.production "$@"
}

ready() {
  for _ in $(seq 1 60); do
    if curl -fsS --max-time 5 http://127.0.0.1:8031/ready >/dev/null 2>&1; then
      return 0
    fi
    sleep 5
  done
  return 1
}

echo "deploy: ${previous:0:12} -> ${sha:0:12}"

# The dashboard talks to the API's public address, fixed at build time.
ADMIN_ROOT=/srv/myradius-admin
admin_api="$(grep -m1 '^ADMIN_API_BASE_URL=' .env.production | cut -d= -f2- || true)"
admin_api="${admin_api:-https://myradius.chatara.co}"
admin_build="${ADMIN_ROOT}/releases/${sha}"
if [[ -d admin ]]; then
  echo "deploy: building the admin dashboard against ${admin_api}"
  rm -rf "${admin_build}.tmp"
  docker build --quiet -f admin/Dockerfile \
    --build-arg VITE_API_BASE_URL="${admin_api}" \
    --output "type=local,dest=${admin_build}.tmp" admin >/dev/null
  # Docker's export makes the folder root-only (0700); nginx reads as www-data.
  chmod -R a+rX "${admin_build}.tmp"
  rm -rf "$admin_build"
  mv "${admin_build}.tmp" "$admin_build"
fi

publish_admin() {
  [[ -d "$admin_build" ]] || return 0
  ln -sfn "$admin_build" "${ADMIN_ROOT}/current.next"
  mv -T "${ADMIN_ROOT}/current.next" "${ADMIN_ROOT}/current"
  # The newest three builds stay, so a rollback has the last ones to hand.
  ls -1dt "${ADMIN_ROOT}"/releases/*/ 2>/dev/null | tail -n +4 | xargs -r rm -rf
  echo "deploy: the admin dashboard is ${sha:0:12}"
}

if [[ "$previous" != "$sha" ]] && ! git diff --quiet "$previous" "$sha" -- migrations/; then
  echo "deploy: this release changes migrations; backing up first"
  COMPOSE_FILE=docker-compose.prod.yml:docker-compose.vps.yml ENV_FILE=.env.production \
    bash scripts/backup.sh
fi

if compose up -d --build --remove-orphans && ready; then
  # The photo bucket, provisioned on purpose here (the app never creates one
  # outside development). Already existing is fine.
  compose exec -T storage sh -c 'echo "s3.bucket.create -name myradius-media" | weed shell' \
    >/dev/null 2>&1 || true
  echo "deploy: ${sha:0:12} is live"
  publish_admin
  docker image prune -f >/dev/null
  exit 0
fi

echo "deploy: ${sha:0:12} did not become ready; rolling back to ${previous:0:12}" >&2
compose logs --tail 80 api >&2 || true
git checkout --quiet --force "$previous"
compose up -d --build --remove-orphans
ready && echo "deploy: rolled back to ${previous:0:12}" >&2
exit 1
