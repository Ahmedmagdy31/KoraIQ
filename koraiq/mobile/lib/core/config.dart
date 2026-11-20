/// Build-time configuration via --dart-define (never hard-code production IDs).
///
/// flutter run --dart-define=API_BASE_URL=http://10.0.2.2:8080 --dart-define=CLOUD_PROJECT_NUMBER=123
/// Release: pass real AdMob unit IDs with --dart-define-from-file=env/prod.json
class AppConfig {
  static const apiBaseUrl = String.fromEnvironment('API_BASE_URL', defaultValue: 'http://10.0.2.2:8080');
  static const cloudProjectNumber = int.fromEnvironment('CLOUD_PROJECT_NUMBER', defaultValue: 0);
  static const playStoreUrl = String.fromEnvironment(
    'PLAY_STORE_URL',
    defaultValue: 'https://play.google.com/store/apps/details?id=com.koraiq.app&referrer=utm_source%3Dscorecard',
  );
  static const privacyUrl = String.fromEnvironment('PRIVACY_URL', defaultValue: 'https://koraiq.app/privacy');
  static const termsUrl = String.fromEnvironment('TERMS_URL', defaultValue: 'https://koraiq.app/terms');
  static const termsVersion = '2026-11';

  // Google's official *test* ad units (safe in development; replaced via dart-define in release).
  static const bannerUnit =
      String.fromEnvironment('ADMOB_BANNER_ID', defaultValue: 'ca-app-pub-3940256099942544/6300978111');
  static const interstitialUnit =
      String.fromEnvironment('ADMOB_INTERSTITIAL_ID', defaultValue: 'ca-app-pub-3940256099942544/1033173712');
  static const rewardedUnit =
      String.fromEnvironment('ADMOB_REWARDED_ID', defaultValue: 'ca-app-pub-3940256099942544/5224354917');
  static const usingTestAds = !bool.hasEnvironment('ADMOB_REWARDED_ID');

  static const clubs = ['AHLY', 'ZAMALEK', 'PYRAMIDS', 'ISMAILY', 'ITTIHAD', 'MASRY', 'OTHER'];
}
