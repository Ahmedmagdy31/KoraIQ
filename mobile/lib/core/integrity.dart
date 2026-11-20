import 'dart:convert';
import 'dart:math';

import 'package:crypto/crypto.dart';
import 'package:flutter/services.dart';

import 'config.dart';

/// Play Integrity *Standard* request bridge (Kotlin side: MainActivity.kt).
/// Server contract: requestHash = sha256_hex("$action:$firebaseUid:$nonce").
class Integrity {
  static const _channel = MethodChannel('koraiq/integrity');
  static bool _prepared = false;

  static Future<void> warmUp() async {
    if (_prepared || AppConfig.cloudProjectNumber == 0) return;
    try {
      await _channel.invokeMethod('prepare', {'cloudProjectNumber': AppConfig.cloudProjectNumber});
      _prepared = true;
    } catch (_) {
      // Unsupported device / no Play Store: the server will treat actions as unranked (soft mode).
    }
  }

  /// Returns headers to attach, or an empty map if a token can't be produced.
  static Future<Map<String, String>> headers(String action, String uid) async {
    if (AppConfig.cloudProjectNumber == 0) return const {};
    await warmUp();
    final rnd = Random.secure();
    final nonce = List.generate(16, (_) => rnd.nextInt(256).toRadixString(16).padLeft(2, '0')).join();
    final hash = sha256.convert(utf8.encode('$action:$uid:$nonce')).toString();
    try {
      final token = await _channel.invokeMethod<String>('token', {'requestHash': hash});
      if (token == null) return const {};
      return {'X-Integrity-Token': token, 'X-Integrity-Nonce': nonce};
    } catch (_) {
      _prepared = false; // provider may have expired; re-prepare next time
      return const {};
    }
  }
}
