import 'package:flutter/foundation.dart';

import '../api_client.dart';
import '../config.dart';
import 'ad_service.dart';

/// Result of a rewarded-ad attempt. `status` is the SERVER's verdict (GRANTED / CONSUMED / REJECTED / PENDING).
typedef RewardResult = ({String intentId, String status});

/// intent (server) -> rewarded ad with SSV options -> Google signs callback to backend -> poll verdict.
Future<RewardResult?> watchAdForReward(Api api, String purpose, {String? ref}) async {
  final intent = await api.createIntent(purpose, ref);
  final id = intent['intent_id'] as String;
  final watched = await AdService.instance.showRewarded(
    ssvUserId: intent['ssv_user_id'] as String,
    ssvCustomData: intent['ssv_custom_data'] as String,
  );
  if (!watched) return null;
  // Google's demo ad units never call OUR SSV URL: in debug builds, ask the dev backend to simulate it.
  if (kDebugMode && AppConfig.usingTestAds) {
    await api.devSimulateSsv(id);
  }
  for (var i = 0; i < 12; i++) {
    final status = await api.intentStatus(id);
    if (status != 'PENDING') return (intentId: id, status: status);
    await Future<void>.delayed(const Duration(milliseconds: 800));
  }
  return (intentId: id, status: 'PENDING');
}
