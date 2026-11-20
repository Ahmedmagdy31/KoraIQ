import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../l10n/app_localizations.dart';
import 'api_client.dart';

extension L10nX on BuildContext {
  AppLocalizations get t => AppLocalizations.of(this);
  String get lang => Localizations.localeOf(this).languageCode;
}

class LocaleNotifier extends Notifier<Locale> {
  @override
  Locale build() => const Locale('ar'); // Egyptian Arabic first
  void set(Locale l) => state = l;
}

final localeProvider = NotifierProvider<LocaleNotifier, Locale>(LocaleNotifier.new);

/// The signed-in player's profile (GET /users/me). Refresh after every game/prediction/reward.
class MeNotifier extends AsyncNotifier<Map<String, dynamic>> {
  @override
  Future<Map<String, dynamic>> build() => ref.read(apiProvider).me();

  Future<void> refresh() async {
    state = await AsyncValue.guard(() => ref.read(apiProvider).me());
  }

  void setData(Map<String, dynamic> me) => state = AsyncData(me);
}

final meProvider = AsyncNotifierProvider<MeNotifier, Map<String, dynamic>>(MeNotifier.new);

String clubName(AppLocalizations t, String? code) => switch (code) {
      'AHLY' => t.clubAHLY,
      'ZAMALEK' => t.clubZAMALEK,
      'PYRAMIDS' => t.clubPYRAMIDS,
      'ISMAILY' => t.clubISMAILY,
      'ITTIHAD' => t.clubITTIHAD,
      'MASRY' => t.clubMASRY,
      _ => t.clubOTHER,
    };

String tierName(AppLocalizations t, String? tier) => switch (tier) {
      'BRONZE' => t.tierBRONZE,
      'SILVER' => t.tierSILVER,
      'GOLD' => t.tierGOLD,
      'DIAMOND' => t.tierDIAMOND,
      _ => '',
    };

String errorText(AppLocalizations t, Object e) {
  if (e is ApiError) {
    switch (e.code) {
      case 'nickname_taken':
        return t.errorNicknameTaken;
      case 'nickname_length' || 'nickname_charset' || 'nickname_blocked':
        return t.errorNicknameInvalid;
      case 'prediction_locked':
        return t.errorLocked;
      case 'rate_limited':
        return t.errorRateLimited;
      case 'under_minimum_age':
        return t.underAge;
      case 'insufficient_coins':
        return t.errorNoCoins;
      case 'daily_already_played':
        return t.errorDailyPlayed;
    }
  }
  return t.errorGeneric;
}

void showError(BuildContext context, Object e) {
  ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(errorText(context.t, e))));
}
