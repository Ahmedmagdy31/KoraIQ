import 'package:dio/dio.dart';
import 'package:firebase_auth/firebase_auth.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'config.dart';
import 'integrity.dart';

class ApiError implements Exception {
  ApiError(this.status, this.code);
  final int? status;
  final String code;
  @override
  String toString() => 'ApiError($status, $code)';
}

/// Thin typed wrapper over the FastAPI backend. Identity always comes from the Firebase ID token.
class Api {
  Api() {
    _dio.interceptors.add(InterceptorsWrapper(onRequest: (options, handler) async {
      final user = FirebaseAuth.instance.currentUser;
      if (user != null) {
        options.headers['Authorization'] = 'Bearer ${await user.getIdToken()}';
      }
      handler.next(options);
    }));
  }

  final _dio = Dio(BaseOptions(
    baseUrl: '${AppConfig.apiBaseUrl}/api/v1',
    connectTimeout: const Duration(seconds: 8),
    receiveTimeout: const Duration(seconds: 10),
  ));

  Future<dynamic> _send(String method, String path,
      {Object? body, Map<String, dynamic>? query, Map<String, String>? headers, int retries = 1}) async {
    for (var attempt = 0;; attempt++) {
      try {
        final r = await _dio.request<dynamic>(path,
            data: body, queryParameters: query, options: Options(method: method, headers: headers));
        return r.data;
      } on DioException catch (e) {
        final status = e.response?.statusCode;
        // Retry only transport failures (flaky 3G); every mutating endpoint is idempotent server-side.
        if (status == null && attempt < retries) {
          await Future<void>.delayed(Duration(milliseconds: 400 * (attempt + 1)));
          continue;
        }
        final data = e.response?.data;
        throw ApiError(status, data is Map && data['detail'] is String ? data['detail'] as String : 'network');
      }
    }
  }

  Future<Map<String, dynamic>> _withIntegrity(String action, String path, Object body) async {
    final uid = FirebaseAuth.instance.currentUser?.uid ?? '';
    final h = await Integrity.headers(action, uid);
    return (await _send('POST', path, body: body, headers: h)) as Map<String, dynamic>;
  }

  // ---- users
  Future<Map<String, dynamic>> sync() async => (await _send('POST', '/auth/sync')) as Map<String, dynamic>;
  Future<Map<String, dynamic>> me() async => (await _send('GET', '/users/me')) as Map<String, dynamic>;
  Future<Map<String, dynamic>> onboard({
    required String nickname,
    required String club,
    required DateTime birthDate,
    required String locale,
  }) async =>
      (await _send('POST', '/users/me/onboarding', body: {
        'nickname': nickname,
        'favorite_club': club,
        'birth_date': birthDate.toIso8601String().substring(0, 10),
        'accept_terms_version': AppConfig.termsVersion,
        'locale': locale,
      })) as Map<String, dynamic>;
  Future<void> setLocale(String locale) => _send('PATCH', '/users/me', body: {'locale': locale});
  Future<void> deleteAccount() => _send('DELETE', '/users/me', retries: 0);

  // ---- game (answers retried: the server replays the stored result for a duplicate index)
  Future<Map<String, dynamic>> startGame(String lang, {String topic = 'mixed'}) =>
      _withIntegrity('game_start', '/game/start', {'lang': lang, 'topic': topic});
  Future<Map<String, dynamic>> fifty(String sid, int index) async =>
      (await _send('POST', '/game/$sid/fifty', body: {'index': index})) as Map<String, dynamic>;
  Future<void> reportQuestion(String sid, int index) =>
      _send('POST', '/questions/report', body: {'session_id': sid, 'index': index});

  // ---- topics, daily, progression, shop
  Future<Map<String, dynamic>> topics(String lang) async =>
      (await _send('GET', '/topics', query: {'lang': lang})) as Map<String, dynamic>;
  Future<Map<String, dynamic>> daily(String lang) async =>
      (await _send('GET', '/daily', query: {'lang': lang})) as Map<String, dynamic>;
  Future<Map<String, dynamic>> startDaily(String lang) => _withIntegrity('daily_start', '/daily/start', {'lang': lang});
  Future<Map<String, dynamic>> progress(String lang) async =>
      (await _send('GET', '/me/progress', query: {'lang': lang})) as Map<String, dynamic>;
  Future<Map<String, dynamic>> shop(String lang) async =>
      (await _send('GET', '/shop', query: {'lang': lang})) as Map<String, dynamic>;
  Future<Map<String, dynamic>> buy(String item) async =>
      (await _send('POST', '/shop/buy', body: {'item': item}, retries: 0)) as Map<String, dynamic>;
  Future<void> equip(String kind, String? code) => _send('POST', '/me/equip', body: {'kind': kind, 'code': code});
  Future<Map<String, dynamic>> answer(String sid, int index, int? selected) async =>
      (await _send('POST', '/game/$sid/answer', body: {'index': index, 'selected': selected}, retries: 2))
          as Map<String, dynamic>;
  Future<Map<String, dynamic>> resume(String sid, String intentId) async =>
      (await _send('POST', '/game/$sid/resume', body: {'intent_id': intentId})) as Map<String, dynamic>;
  Future<Map<String, dynamic>> finish(String sid) async =>
      (await _send('POST', '/game/$sid/finish', retries: 2)) as Map<String, dynamic>;

  // ---- predictions
  Future<List<dynamic>> fixtures(String lang) async =>
      (await _send('GET', '/fixtures', query: {'lang': lang})) as List<dynamic>;
  Future<Map<String, dynamic>> predict(String lang, int fixtureId, String outcome, int? home, int? away) async {
    final uid = FirebaseAuth.instance.currentUser?.uid ?? '';
    final h = await Integrity.headers('prediction_submit', uid);
    return (await _send('POST', '/predictions',
        query: {'lang': lang},
        headers: h,
        body: {
          'fixture_id': fixtureId,
          'outcome': outcome,
          if (home != null && away != null) 'home_goals': home,
          if (home != null && away != null) 'away_goals': away,
        })) as Map<String, dynamic>;
  }

  // ---- leaderboard
  Future<Map<String, dynamic>> leaderboard(String lang, {String scope = 'all'}) async =>
      (await _send('GET', '/leaderboard/weekly', query: {'lang': lang, 'scope': scope})) as Map<String, dynamic>;

  // ---- rewarded ads
  Future<Map<String, dynamic>> createIntent(String purpose, [String? ref]) async =>
      (await _send('POST', '/rewards/intents', body: {'purpose': purpose, 'ref': ref})) as Map<String, dynamic>;
  Future<void> devSimulateSsv(String intentId) => _send('POST', '/dev/ssv-simulate', body: {'intent_id': intentId});
  Future<String> intentStatus(String id) async =>
      ((await _send('GET', '/rewards/intents/$id')) as Map<String, dynamic>)['status'] as String;
}

final apiProvider = Provider<Api>((ref) => Api());
