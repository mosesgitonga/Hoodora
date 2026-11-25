<img src="../docs/brand/hoodora-icon.svg" alt="Hoodora" width="96">

# Hoodora app

The Flutter app for Hoodora, for Android (and iOS, which needs a Mac to build).
The backend is in the repository root; see `PROGRESS.md` for what each slice adds.

## Run it

With the backend running (`docker compose up` in the repository root):

```sh
flutter pub get
flutter run                                   # Android emulator: talks to 10.0.2.2:8000
flutter run --dart-define=API_BASE_URL=http://<your PC's Wi-Fi address>:8000   # a phone
```

Sign-in codes go nowhere in development: read them from the API's log,
`docker compose logs api | grep sms_not_sent`.

## Check it

```sh
flutter analyze
flutter test
```

## Ship it

From the repository root, after `shorebird login` (decision M.12):

```sh
scripts/app_patch.sh          # Dart-only changes, over the air to installed builds
scripts/app_release.sh        # a new build: a plugin, native code, new icons or fonts
```

A patch applies to the release whose `version:` is in `pubspec.yaml`, so leave it
alone between a release and its patches. Bump it for every release.

To try a build on a phone plugged in over USB, against staging:

```sh
flutter build apk --release --target-platform android-arm64   --dart-define=API_BASE_URL=https://myradius.chatara.co   --dart-define=APP_BUILD=<the number after + in pubspec.yaml>
adb install -r build/app/outputs/flutter-apk/app-release.apk
```

Without `API_BASE_URL` the build talks to `10.0.2.2:8000`, the emulator's name for
the PC, and on a phone it reaches nothing.

A release build needs `android/key.properties` and `android/app/google-services.json`,
which are kept out of the repository.
