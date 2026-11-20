import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:share_plus/share_plus.dart';

import '../../core/ads/ad_service.dart';
import '../../core/ads/rewards.dart';
import '../../core/api_client.dart';
import '../../core/sealed.dart';
import '../../core/state.dart';
import '../../core/theme.dart';
import 'scorecard.dart';

enum _Phase { loading, question, feedback, revive, result }

/// Trivia arena. NO banner ads here (accidental-click risk = AdMob policy violation).
/// All scoring/timing is server-side; the on-screen timer is cosmetic.
class GameScreen extends ConsumerStatefulWidget {
  const GameScreen({super.key, this.topic = 'mixed', this.daily = false});

  /// Topic slug or 'mixed'. Ignored for the Daily Challenge (the server picks today's questions).
  final String topic;
  final bool daily;
  @override
  ConsumerState<GameScreen> createState() => _GameScreenState();
}

class _GameScreenState extends ConsumerState<GameScreen> with SingleTickerProviderStateMixin {
  late final AnimationController _shake =
      AnimationController(vsync: this, duration: const Duration(milliseconds: 450));
  final _cardKey = GlobalKey();

  _Phase _phase = _Phase.loading;
  late String _sid;
  List<Map<String, dynamic>> _boxes = const [];
  int _limit = 15;
  bool _ranked = true;
  int _index = 0;
  Question? _q;
  Question? _nextQ;
  int? _selected;
  Map<String, dynamic>? _last; // last server response
  Timer? _timer;
  double _remaining = 15;
  bool _sending = false;
  String _mode = 'SOLO';
  int? _fiftyPrice;
  bool _fiftyUsed = false;
  Set<int> _removed = {};
  int? _dailyNumber;
  final List<bool> _grid = []; // per-question correctness for the spoiler-free Daily share
  int _elapsedMs = 0;
  final List<String> _seen = []; // question texts, for "report a mistake"

  Api get _api => ref.read(apiProvider);

  @override
  void initState() {
    super.initState();
    _start();
  }

  @override
  void dispose() {
    _timer?.cancel();
    _shake.dispose();
    super.dispose();
  }

  Future<void> _start() async {
    try {
      final lang = ref.read(localeProvider).languageCode;
      final r = widget.daily ? await _api.startDaily(lang) : await _api.startGame(lang, topic: widget.topic);
      _sid = r['session_id'] as String;
      _mode = r['mode'] as String? ?? 'SOLO';
      _fiftyPrice = (r['fifty_price'] as num?)?.toInt();
      _dailyNumber = (r['daily_number'] as num?)?.toInt();
      _boxes = (r['questions'] as List).cast<Map<String, dynamic>>();
      _limit = (r['time_limit_s'] as num).toInt();
      _ranked = r['ranked'] as bool;
      await _show(0, r['first_key'] as String);
    } catch (e) {
      if (!mounted) return;
      showError(context, e);
      context.pop();
    }
  }

  Future<Question> _open(int index, String key) =>
      Sealed.open(keyB64: key, sessionId: _sid, index: index, box: _boxes[index]);

  Future<void> _show(int index, String key, {Question? preopened}) async {
    final q = preopened ?? await _open(index, key);
    if (!mounted) return;
    _seen.add(q.text);
    setState(() {
      _index = index;
      _q = q;
      _selected = null;
      _removed = {};
      _remaining = _limit.toDouble();
      _phase = _Phase.question;
    });
    _timer?.cancel();
    _timer = Timer.periodic(const Duration(milliseconds: 100), (t) {
      if (!mounted) return t.cancel();
      setState(() => _remaining = math.max(0, _remaining - 0.1));
      if (_remaining <= 0) {
        t.cancel();
        _answer(null);
      }
    });
  }

  Future<void> _answer(int? choice) async {
    if (_sending || _phase != _Phase.question) return;
    _sending = true;
    _timer?.cancel();
    setState(() => _selected = choice);
    try {
      final r = await _api.answer(_sid, _index, choice);
      final a = r['answer'] as Map<String, dynamic>;
      final next = r['next'] as Map<String, dynamic>?;
      _grid.add(a['correct'] == true);
      _elapsedMs += (a['elapsed_ms'] as num).toInt();
      // Decrypt the next question while the feedback animation plays.
      final pre = next == null ? null : _open((next['index'] as num).toInt(), next['key'] as String);
      setState(() {
        _last = r;
        _phase = _Phase.feedback;
      });
      if (a['correct'] == true) {
        HapticFeedback.lightImpact();
      } else {
        HapticFeedback.heavyImpact();
        _shake.forward(from: 0);
      }
      await Future<void>.delayed(const Duration(milliseconds: 1100));
      if (!mounted) return;
      if (next != null) {
        await _show((next['index'] as num).toInt(), next['key'] as String, preopened: await pre);
      } else if (r['status'] == 'AWAITING_REVIVE') {
        setState(() => _phase = _Phase.revive);
      } else {
        await _toResult(r);
      }
    } catch (e) {
      if (mounted) showError(context, e);
      await _endRound();
    } finally {
      _sending = false;
    }
  }

  Future<void> _revive() async {
    try {
      final res = await watchAdForReward(_api, 'REVIVE', ref: _sid);
      if (res != null && res.status == 'GRANTED') {
        final r = await _api.resume(_sid, res.intentId);
        final next = r['next'] as Map<String, dynamic>;
        await _show((next['index'] as num).toInt(), next['key'] as String);
        return;
      }
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(context.t.adNotReady)));
      }
    } catch (e) {
      if (mounted) showError(context, e);
    }
  }

  Future<void> _useFifty() async {
    if (_sending || _phase != _Phase.question) return;
    try {
      final r = await _api.fifty(_sid, _index);
      if (!mounted) return;
      setState(() {
        _removed = (r['remove'] as List).map((e) => (e as num).toInt()).toSet();
        _fiftyUsed = true;
        _ranked = false;
      });
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(context.t.fiftyNote)));
      ref.read(meProvider.notifier).refresh();
    } catch (e) {
      if (mounted) showError(context, e);
    }
  }

  Future<void> _report() async {
    final t = context.t;
    final pick = await showDialog<int>(
      context: context,
      builder: (c) => SimpleDialog(
        title: Text(t.reportMistake),
        children: [
          for (var i = 0; i < _seen.length; i++)
            SimpleDialogOption(
              onPressed: () => Navigator.pop(c, i),
              child: Text('${i + 1}. ${_seen[i]}', maxLines: 2, overflow: TextOverflow.ellipsis),
            ),
        ],
      ),
    );
    if (pick == null) return;
    try {
      await _api.reportQuestion(_sid, pick);
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(t.reported)));
    } catch (e) {
      if (mounted) showError(context, e);
    }
  }

  String _dailyShareText() {
    final correct = _grid.where((c) => c).length;
    final squares = _grid.map((c) => c ? '🟩' : '🟥').join();
    return 'KoraIQ #${_dailyNumber ?? ''} · $squares $correct/${_grid.length} · ${(_elapsedMs / 1000).round()}s';
  }

  Future<void> _endRound() async {
    try {
      await _toResult(await _api.finish(_sid));
    } catch (_) {
      if (mounted) context.pop();
    }
  }

  Future<void> _toResult(Map<String, dynamic> r) async {
    // Natural break -> interstitial (frequency-capped) BEFORE revealing the final score.
    await AdService.instance.maybeShowInterstitial();
    if (!mounted) return;
    setState(() {
      _last = r;
      _phase = _Phase.result;
    });
    ref.read(meProvider.notifier).refresh();
  }

  // ------------------------------------------------------------------ UI
  @override
  Widget build(BuildContext context) {
    final t = context.t;
    return PopScope(
      canPop: _phase == _Phase.result || _phase == _Phase.loading,
      child: Scaffold(
        appBar: AppBar(
          automaticallyImplyLeading: _phase == _Phase.result,
          title: switch (_phase) {
            _Phase.loading => null,
            _Phase.result => Text(t.roundOver),
            _ => Text(t.questionOf(_index + 1, _boxes.length)),
          },
        ),
        body: SafeArea(
          child: switch (_phase) {
            _Phase.loading => const Center(child: CircularProgressIndicator()),
            _Phase.result => _result(),
            _Phase.revive => _reviveView(),
            _ => _arena(),
          },
        ),
      ),
    );
  }

  Widget _arena() {
    final q = _q!;
    final answer = _phase == _Phase.feedback ? _last?['answer'] as Map<String, dynamic>? : null;
    return Padding(
      padding: const EdgeInsets.all(20),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          LinearProgressIndicator(
            value: _remaining / _limit,
            minHeight: 8,
            borderRadius: BorderRadius.circular(8),
            color: _remaining > 5 ? KoraColors.pitch : KoraColors.wrong,
          ),
          const SizedBox(height: 8),
          Row(children: [
            Text('${_remaining.ceil()}s', style: const TextStyle(fontWeight: FontWeight.w700)),
            const Spacer(),
            Text(context.t.points((_last?['round_score'] as num?)?.toInt() ?? 0)),
          ]),
          const SizedBox(height: 24),
          AnimatedBuilder(
            animation: _shake,
            builder: (_, child) => Transform.translate(
              offset: Offset(math.sin(_shake.value * math.pi * 6) * 12 * (1 - _shake.value), 0),
              child: child,
            ),
            child: Text(q.text,
                textAlign: TextAlign.center,
                style: Theme.of(context).textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w700)),
          ),
          const Spacer(),
          if (_mode == 'SOLO' && _fiftyPrice != null && !_fiftyUsed && _phase == _Phase.question)
            Align(
              alignment: AlignmentDirectional.centerEnd,
              child: TextButton.icon(
                onPressed: _useFifty,
                icon: const Icon(Icons.exposure_neg_2),
                label: Text(context.t.fiftyFifty(_fiftyPrice!)),
              ),
            ),
          for (var i = 0; i < q.options.length; i++)
            Padding(
              padding: const EdgeInsets.only(bottom: 12),
              child: _OptionButton(
                label: q.options[i],
                state: answer == null
                    ? (_selected == i ? _Opt.pending : _Opt.idle)
                    : i == answer['correct_option']
                        ? _Opt.correct
                        : i == _selected
                            ? _Opt.wrong
                            : _Opt.idle,
                removed: _removed.contains(i),
                onTap: _phase == _Phase.question && !_removed.contains(i) ? () => _answer(i) : null,
              ),
            ),
          if (answer?['timed_out'] == true)
            Text(context.t.timeUp, textAlign: TextAlign.center, style: const TextStyle(color: KoraColors.wrong)),
          if (answer?['correct'] == true)
            Text('+${answer!['points']}',
                textAlign: TextAlign.center,
                style: const TextStyle(color: KoraColors.correct, fontSize: 22, fontWeight: FontWeight.w900)),
        ],
      ),
    );
  }

  Widget _reviveView() => Padding(
        padding: const EdgeInsets.all(24),
        child: Column(mainAxisAlignment: MainAxisAlignment.center, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          const Icon(Icons.favorite, size: 72, color: KoraColors.wrong),
          const SizedBox(height: 16),
          Text(context.t.reviveTitle, textAlign: TextAlign.center, style: Theme.of(context).textTheme.headlineSmall),
          const SizedBox(height: 8),
          Text(context.t.reviveBody, textAlign: TextAlign.center),
          const SizedBox(height: 24),
          FilledButton.icon(onPressed: _revive, icon: const Icon(Icons.play_circle), label: Text(context.t.watchAdRevive)),
          const SizedBox(height: 12),
          OutlinedButton(onPressed: _endRound, child: Text(context.t.endRound)),
        ]),
      );

  Widget _result() {
    final t = context.t;
    final r = _last!;
    final me = ref.read(meProvider).valueOrNull ?? const {};
    final equipped = me['equipped'] as Map<String, dynamic>? ?? const {};
    final score = (r['round_score'] as num).toInt();
    final correct = (r['correct_count'] as num).toInt();
    final total = (r['total_questions'] as num).toInt();
    final rewards = r['rewards'] as Map<String, dynamic>?;
    final isDaily = _mode == 'DAILY';
    return ListView(
      padding: const EdgeInsets.all(20),
      children: [
        Scorecard(
          boundaryKey: _cardKey,
          nickname: (me['nickname'] as String?) ?? '',
          club: me['favorite_club'] as String?,
          score: score,
          correct: correct,
          total: total,
          frame: cosmeticColors(equipped['frame']),
          theme: cosmeticColors(equipped['theme']),
        ),
        if (_fiftyUsed)
          Padding(padding: const EdgeInsets.only(top: 12), child: Text(t.fiftyNote, textAlign: TextAlign.center))
        else if (!_ranked || r['ranked'] == false)
          Padding(padding: const EdgeInsets.only(top: 12), child: Text(t.unranked, textAlign: TextAlign.center)),
        if (rewards != null) _RewardsPanel(rewards),
        const SizedBox(height: 16),
        if (isDaily)
          FilledButton.icon(
            // Spoiler-free text grid: friends see how you did, not the answers.
            onPressed: () => Share.share(_dailyShareText()),
            icon: const Icon(Icons.share),
            label: Text(t.shareResult),
          )
        else
          FilledButton.icon(
            onPressed: () => shareScorecard(_cardKey, t.shareText(score)),
            icon: const Icon(Icons.share),
            label: Text(t.shareScore),
          ),
        const SizedBox(height: 12),
        if (!isDaily)
          OutlinedButton(
            style: OutlinedButton.styleFrom(minimumSize: const Size.fromHeight(52)),
            onPressed: () => context.pushReplacement('/play?topic=${widget.topic}'),
            child: Text(t.playAgain),
          ),
        TextButton.icon(onPressed: _report, icon: const Icon(Icons.flag_outlined), label: Text(t.reportMistake)),
        TextButton(onPressed: () => context.go('/'), child: Text(t.backHome)),
      ],
    );
  }
}

class _RewardsPanel extends StatelessWidget {
  const _RewardsPanel(this.r);
  final Map<String, dynamic> r;

  @override
  Widget build(BuildContext context) {
    final t = context.t;
    final xp = (r['xp'] as num?)?.toInt() ?? 0;
    final coins = (r['coins'] as num?)?.toInt() ?? 0;
    final before = (r['level_before'] as num?)?.toInt() ?? 1;
    final after = (r['level_after'] as num?)?.toInt() ?? before;
    final badges = (r['badges'] as List?)?.cast<Map<String, dynamic>>() ?? const [];
    if (xp == 0 && coins == 0 && badges.isEmpty) return const SizedBox.shrink();
    return Card(
      margin: const EdgeInsets.only(top: 16),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Text(t.rewards, style: Theme.of(context).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w800)),
          const SizedBox(height: 8),
          Wrap(spacing: 8, runSpacing: 8, children: [
            Chip(avatar: const Icon(Icons.star, color: KoraColors.gold), label: Text(t.xpGained(xp))),
            Chip(avatar: const Icon(Icons.monetization_on, color: KoraColors.gold), label: Text(t.coinsGained(coins))),
            if (r['streak'] != null)
              Chip(
                avatar: const Icon(Icons.local_fire_department, color: Colors.deepOrange),
                label: Text(t.streakDays((r['streak'] as num).toInt())),
              ),
          ]),
          if (after > before)
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: Text(t.levelUp(after), style: const TextStyle(fontWeight: FontWeight.w800, color: KoraColors.gold)),
            ),
          if (((r['freezes_used'] as num?) ?? 0) > 0)
            Padding(padding: const EdgeInsets.only(top: 4), child: Text(t.freezeUsed)),
          for (final b in badges)
            ListTile(
              contentPadding: EdgeInsets.zero,
              leading: Icon(iconFor(b['icon'] as String?), color: KoraColors.gold),
              title: Text(t.newBadge('${b[context.lang == 'ar' ? 'name_ar' : 'name_en']}')),
            ),
        ]),
      ),
    );
  }
}

enum _Opt { idle, pending, correct, wrong }

class _OptionButton extends StatelessWidget {
  const _OptionButton({required this.label, required this.state, required this.onTap, this.removed = false});
  final String label;
  final _Opt state;
  final VoidCallback? onTap;
  final bool removed;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final (bg, fg) = switch (state) {
      _Opt.correct => (KoraColors.correct, Colors.white),
      _Opt.wrong => (KoraColors.wrong, Colors.white),
      _Opt.pending => (scheme.secondaryContainer, scheme.onSecondaryContainer),
      _Opt.idle => (scheme.surfaceContainerHighest, scheme.onSurface),
    };
    return AnimatedOpacity(
      duration: const Duration(milliseconds: 200),
      opacity: removed ? 0.25 : 1,
      child: AnimatedContainer(
      duration: const Duration(milliseconds: 200),
      decoration: BoxDecoration(color: bg, borderRadius: BorderRadius.circular(16)),
      child: Material(
        type: MaterialType.transparency,
        child: InkWell(
          borderRadius: BorderRadius.circular(16),
          onTap: onTap,
          child: Padding(
            padding: const EdgeInsets.symmetric(vertical: 18, horizontal: 16),
            child: Text(label, textAlign: TextAlign.center, style: TextStyle(color: fg, fontSize: 17, fontWeight: FontWeight.w600)),
          ),
        ),
      ),
    ),
    );
  }
}
