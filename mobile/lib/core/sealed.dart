import 'dart:convert';

import 'package:cryptography/cryptography.dart';

/// A question decrypted with the per-question key the server releases when its timer starts.
class Question {
  Question(this.text, this.options, this.category, this.difficulty);
  final String text;
  final List<String> options;
  final String category;
  final int difficulty;
}

/// Mirror of backend/app/services/sealing.py: AES-256-GCM, 12-byte nonce, 16-byte tag appended,
/// AAD = "$sessionId:$index".
class Sealed {
  static final _aes = AesGcm.with256bits();

  static Future<Question> open({
    required String keyB64,
    required String sessionId,
    required int index,
    required Map<String, dynamic> box,
  }) async {
    final ct = base64.decode(box['ciphertext'] as String);
    final secretBox = SecretBox(
      ct.sublist(0, ct.length - 16),
      nonce: base64.decode(box['nonce'] as String),
      mac: Mac(ct.sublist(ct.length - 16)),
    );
    final clear = await _aes.decrypt(
      secretBox,
      secretKey: SecretKey(base64.decode(keyB64)),
      aad: utf8.encode('$sessionId:$index'),
    );
    final j = jsonDecode(utf8.decode(clear)) as Map<String, dynamic>;
    return Question(
      j['q'] as String,
      (j['o'] as List).cast<String>(),
      j['c'] as String,
      j['d'] as int,
    );
  }
}
