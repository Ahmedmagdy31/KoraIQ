# KoraIQ mobile (Flutter, Android-first)

Requires Flutter **≥ 3.32** (gen-l10n writes to `lib/l10n`).

## One-time setup

```bash
cd mobile
flutter create --org com.koraiq --project-name koraiq --platforms android .   # generates android/ scaffolding; keeps lib/
# then re-apply our two Android files (flutter create does not overwrite existing files, but verify):
#   android/app/src/main/AndroidManifest.xml
#   android/app/src/main/kotlin/com/koraiq/app/MainActivity.kt
# and merge android/app/build.gradle.kts.additions into android/app/build.gradle.kts
dart pub global activate flutterfire_cli && flutterfire configure   # google-services.json + gms plugin
flutter pub get && flutter gen-l10n && flutter test
```

## Run against the local backend (emulator)

```bash
flutter run --dart-define=API_BASE_URL=http://10.0.2.2:8080
```
Debug builds use Google's **test** ad units. Because demo units never call your SSV URL, debug builds ask the
dev backend (`/api/v1/dev/ssv-simulate`, not mounted in staging/production) to simulate the signed callback.

## Release

```bash
ADMOB_APP_ID=ca-app-pub-XXXX~YYYY flutter build appbundle --release \
  --dart-define=API_BASE_URL=https://api.koraiq.app \
  --dart-define=CLOUD_PROJECT_NUMBER=<gcp project number linked in Play Console> \
  --dart-define=ADMOB_BANNER_ID=ca-app-pub-XXXX/1111 \
  --dart-define=ADMOB_INTERSTITIAL_ID=ca-app-pub-XXXX/2222 \
  --dart-define=ADMOB_REWARDED_ID=ca-app-pub-XXXX/3333
```

## Where things live

| Concern | File |
|---|---|
| API client (JWT, retries, integrity headers) | `lib/core/api_client.dart` |
| Sealed-question decryption (AES-256-GCM) | `lib/core/sealed.dart` |
| Play Integrity bridge | `lib/core/integrity.dart` + `android/.../MainActivity.kt` |
| Ads: UMP consent, caps, rewarded+SSV, banner | `lib/core/ads/` |
| Screens | `lib/features/{auth,home,game,predictor,leaderboard,profile}` |
| Strings (Egyptian Arabic default + English) | `lib/l10n/app_ar.arb`, `app_en.arb` |
