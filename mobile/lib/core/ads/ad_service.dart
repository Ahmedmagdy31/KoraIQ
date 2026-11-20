import 'dart:async';

import 'package:flutter/material.dart';
import 'package:google_mobile_ads/google_mobile_ads.dart';

import '../config.dart';

/// AdMob policy-safe wrapper:
///  * UMP consent gathered BEFORE any ad request (required for EEA/UK/Swiss users; harmless elsewhere).
///  * Max content rating T (13+ audience).
///  * Interstitials: only at natural breaks, never in the first round of an app session, max 1 per 3 min.
///  * Rewarded: preloaded; SSV userId/customData set right before show; the client NEVER grants rewards.
class AdService {
  AdService._();
  static final instance = AdService._();

  bool _canRequestAds = false;
  DateTime? _lastInterstitial;
  int _roundsThisSession = 0;
  InterstitialAd? _interstitial;
  RewardedAd? _rewarded;

  Future<void> init() async {
    final consentDone = Completer<void>();
    void done() {
      if (!consentDone.isCompleted) consentDone.complete();
    }

    ConsentInformation.instance.requestConsentInfoUpdate(
      ConsentRequestParameters(),
      () => ConsentForm.loadAndShowConsentFormIfRequired((_) => done()),
      (_) => done(),
    );
    await consentDone.future.timeout(const Duration(seconds: 10), onTimeout: () {});
    _canRequestAds = await ConsentInformation.instance.canRequestAds();
    if (!_canRequestAds) return;
    await MobileAds.instance.initialize();
    await MobileAds.instance.updateRequestConfiguration(
      RequestConfiguration(maxAdContentRating: MaxAdContentRating.t),
    );
    _loadInterstitial();
    _loadRewarded();
  }

  Future<bool> privacyOptionsRequired() async =>
      await ConsentInformation.instance.getPrivacyOptionsRequirementStatus() ==
      PrivacyOptionsRequirementStatus.required;

  void showPrivacyOptions() => ConsentForm.showPrivacyOptionsForm((_) {});

  // ---------------------------------------------------------------- interstitial
  void _loadInterstitial() {
    if (!_canRequestAds) return;
    InterstitialAd.load(
      adUnitId: AppConfig.interstitialUnit,
      request: const AdRequest(),
      adLoadCallback: InterstitialAdLoadCallback(
        onAdLoaded: (ad) => _interstitial = ad,
        onAdFailedToLoad: (_) => _interstitial = null,
      ),
    );
  }

  /// Call at the end of a round / after predictions. Resolves when the ad (if any) is closed.
  Future<void> maybeShowInterstitial() async {
    _roundsThisSession++;
    final ad = _interstitial;
    final recent = _lastInterstitial != null && DateTime.now().difference(_lastInterstitial!) < const Duration(minutes: 3);
    if (ad == null || recent || _roundsThisSession < 2) return;
    final closed = Completer<void>();
    ad.fullScreenContentCallback = FullScreenContentCallback(
      onAdDismissedFullScreenContent: (ad) {
        ad.dispose();
        closed.complete();
      },
      onAdFailedToShowFullScreenContent: (ad, _) {
        ad.dispose();
        closed.complete();
      },
    );
    _interstitial = null;
    _lastInterstitial = DateTime.now();
    await ad.show();
    await closed.future;
    _loadInterstitial();
  }

  // ---------------------------------------------------------------- rewarded
  void _loadRewarded() {
    if (!_canRequestAds) return;
    RewardedAd.load(
      adUnitId: AppConfig.rewardedUnit,
      request: const AdRequest(),
      rewardedAdLoadCallback: RewardedAdLoadCallback(
        onAdLoaded: (ad) => _rewarded = ad,
        onAdFailedToLoad: (_) => _rewarded = null,
      ),
    );
  }

  bool get rewardedReady => _rewarded != null;
  bool get canRequestAds => _canRequestAds;

  /// Shows a rewarded ad bound to a server intent. Returns true if the user watched to completion
  /// (the actual grant still arrives via Google's signed SSV callback to the backend).
  Future<bool> showRewarded({required String ssvUserId, required String ssvCustomData}) async {
    final ad = _rewarded;
    if (ad == null) {
      _loadRewarded();
      return false;
    }
    _rewarded = null;
    await ad.setServerSideOptions(ServerSideVerificationOptions(userId: ssvUserId, customData: ssvCustomData));
    var earned = false;
    final closed = Completer<void>();
    ad.fullScreenContentCallback = FullScreenContentCallback(
      onAdDismissedFullScreenContent: (ad) {
        ad.dispose();
        closed.complete();
      },
      onAdFailedToShowFullScreenContent: (ad, _) {
        ad.dispose();
        closed.complete();
      },
    );
    await ad.show(onUserEarnedReward: (_, __) => earned = true);
    await closed.future;
    _loadRewarded();
    return earned;
  }
}

/// Anchored adaptive banner for NON-gameplay screens only (never inside the trivia arena).
class BottomBanner extends StatefulWidget {
  const BottomBanner({super.key});
  @override
  State<BottomBanner> createState() => _BottomBannerState();
}

class _BottomBannerState extends State<BottomBanner> {
  BannerAd? _ad;
  bool _loaded = false;
  bool _requested = false;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (!_requested) {
      _requested = true;
      _load();
    }
  }

  Future<void> _load() async {
    if (!AdService.instance.canRequestAds) return;
    final width = MediaQuery.sizeOf(context).width.truncate();
    final size = await AdSize.getCurrentOrientationAnchoredAdaptiveBannerAdSize(width);
    if (!mounted || size == null) return;
    _ad = BannerAd(
      adUnitId: AppConfig.bannerUnit,
      size: size,
      request: const AdRequest(),
      listener: BannerAdListener(
        onAdLoaded: (_) {
          if (mounted) setState(() => _loaded = true);
        },
        onAdFailedToLoad: (ad, _) => ad.dispose(),
      ),
    )..load();
  }

  @override
  void dispose() {
    _ad?.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final ad = _ad;
    if (!_loaded || ad == null) return const SizedBox.shrink();
    return SafeArea(
      top: false,
      child: SizedBox(width: ad.size.width.toDouble(), height: ad.size.height.toDouble(), child: AdWidget(ad: ad)),
    );
  }
}
