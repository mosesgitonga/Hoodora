#!/usr/bin/env bash
#
# A full Android release through Shorebird (DECISIONS M.12). Run from the
# repository, after `shorebird login` (or with SHOREBIRD_TOKEN set in CI):
#
#   scripts/app_release.sh          an APK to share with testers: 64-bit phones only
#   scripts/app_release.sh play     an app bundle for the Play Store: 32- and 64-bit
#                                   phones, and Chromebooks (DECISIONS M.13)
#
# Anything after the mode goes to shorebird, e.g. `scripts/app_release.sh play
# --dry-run` to build and validate without publishing.
#
# Use it when a change can't go over the air: a new plugin, native code, a Flutter
# upgrade, or new images or fonts. Bump `version:` in mobile/pubspec.yaml first;
# the number after `+` is the build number the app reports to the version check.
# Every release needs its own version, so the tester APK and the Play bundle can't
# share one. Phones need the new build installed once; patches then apply to it.
#
# API_BASE_URL picks the server (staging by default).
set -euo pipefail

mode="${1:-apk}"
if [[ $# -gt 0 ]]; then shift; fi
needs_upload_key=false
case "${mode}" in
  apk)
    # Shared as a file, so kept small. A 32-bit phone may install it and then
    # fail to open it.
    artifact=apk
    platforms=android-arm64
    output=mobile/build/app/outputs/flutter-apk/app-release.apk
    ;;
  play)
    # The Play Store sends each device only its own CPU's code, so carrying 32-bit
    # and x86_64 (Chromebooks) costs 64-bit phones nothing, and the cheapest
    # phones can run the app.
    artifact=aab
    platforms=android-arm,android-arm64,android-x64
    output=mobile/build/app/outputs/bundle/release/app-release.aab
    needs_upload_key=true
    ;;
  *)
    echo "usage: scripts/app_release.sh [apk|play] [shorebird options]" >&2
    exit 2
    ;;
esac

cd "$(dirname "$0")/../mobile"
# Without it the build falls back to the debug key, which the Play Store refuses.
if [[ "${needs_upload_key}" == true && ! -f android/key.properties ]]; then
  echo "No upload key: mobile/android/key.properties is missing (DECISIONS M.14)." >&2
  exit 1
fi
# On PATH once the terminal has restarted after installing; else its usual home.
shorebird="$(command -v shorebird || echo "${HOME}/.shorebird/bin/shorebird")"
api="${API_BASE_URL:-https://myradius.chatara.co}"
version="$(grep -E '^version:' pubspec.yaml | awk '{print $2}')"
build="${version##*+}"

echo "Releasing ${version} (build ${build}) as ${artifact} for ${platforms}, against ${api}"
"${shorebird}" release android --artifact "${artifact}" --target-platform "${platforms}" \
  --dart-define=API_BASE_URL="${api}" --dart-define=APP_BUILD="${build}" "$@"

echo
echo "Built: ${output}"
echo "Then set APP_LATEST_BUILD=${build} on the server to offer it to older builds."
