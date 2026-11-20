import 'package:flutter_test/flutter_test.dart';
import 'package:koraiq/core/sealed.dart';

/// Cross-language contract: this vector was produced by backend/app/services/sealing.py.
/// If either side changes the wire format, this test fails in CI.
void main() {
  const key = 'AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8=';
  const sid = '11111111-2222-3333-4444-555555555555';
  const box = {
    'nonce': 'T+LLG43zAwJmWI25',
    'ciphertext':
        '01z4mDnxG7rs+iVt3odw2swjSNJVYMD6EKfINJzRA2L/9IAQOvQalsy8hikvIHURCXI8pCpg2UX+KP7jDWO1KArfnmNnYr+j8z6RV4qglg4vqHwM86GtJmzjgb4dG+0VooZcvygbMg==',
  };

  test('decrypts a question sealed by the Python backend', () async {
    final q = await Sealed.open(keyB64: key, sessionId: sid, index: 3, box: box);
    expect(q.text, 'مين سجّل؟');
    expect(q.options, ['أ', 'ب', 'ج', 'د']);
    expect(q.category, 'national_team');
    expect(q.difficulty, 2);
  });

  test('rejects the ciphertext in another slot (AAD binding)', () async {
    expect(() => Sealed.open(keyB64: key, sessionId: sid, index: 4, box: box), throwsA(anything));
  });
}
