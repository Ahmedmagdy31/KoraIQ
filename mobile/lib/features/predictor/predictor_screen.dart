import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/ads/ad_service.dart';
import '../../core/ads/rewards.dart';
import '../../core/api_client.dart';
import '../../core/state.dart';
import '../../core/theme.dart';

final fixturesProvider = FutureProvider.autoDispose.family<List<dynamic>, String>(
  (ref, lang) => ref.read(apiProvider).fixtures(lang),
);

class PredictorScreen extends ConsumerStatefulWidget {
  const PredictorScreen({super.key});
  @override
  ConsumerState<PredictorScreen> createState() => _PredictorScreenState();
}

class _PredictorScreenState extends ConsumerState<PredictorScreen> {
  bool _savedAny = false;

  @override
  Widget build(BuildContext context) {
    final t = context.t;
    final lang = context.lang;
    final fixtures = ref.watch(fixturesProvider(lang));
    return PopScope(
      canPop: false,
      onPopInvokedWithResult: (didPop, _) async {
        if (didPop) return;
        if (_savedAny) await AdService.instance.maybeShowInterstitial(); // natural break after predicting
        if (context.mounted) Navigator.of(context).pop();
      },
      child: Scaffold(
        appBar: AppBar(title: Text(t.matchPredictor)),
        bottomNavigationBar: const BottomBanner(),
        body: fixtures.when(
          loading: () => const Center(child: CircularProgressIndicator()),
          error: (e, _) => Center(
            child: TextButton(onPressed: () => ref.invalidate(fixturesProvider(lang)), child: Text(t.retry)),
          ),
          data: (list) => list.isEmpty
              ? Center(child: Padding(padding: const EdgeInsets.all(32), child: Text(t.noFixtures, textAlign: TextAlign.center)))
              : RefreshIndicator(
                  onRefresh: () => ref.refresh(fixturesProvider(lang).future),
                  child: ListView.builder(
                    padding: const EdgeInsets.all(12),
                    itemCount: list.length,
                    itemBuilder: (_, i) => _FixtureCard(
                      initial: list[i] as Map<String, dynamic>,
                      onSaved: () => _savedAny = true,
                    ),
                  ),
                ),
        ),
      ),
    );
  }
}

class _FixtureCard extends ConsumerStatefulWidget {
  const _FixtureCard({required this.initial, required this.onSaved});
  final Map<String, dynamic> initial;
  final VoidCallback onSaved;
  @override
  ConsumerState<_FixtureCard> createState() => _FixtureCardState();
}

class _FixtureCardState extends ConsumerState<_FixtureCard> {
  late Map<String, dynamic> f = widget.initial;
  String? _outcome;
  bool _exact = false;
  int _home = 1, _away = 0;
  bool _busy = false;

  Map<String, dynamic>? get _pred => f['my_prediction'] as Map<String, dynamic>?;

  @override
  void initState() {
    super.initState();
    final p = _pred;
    if (p != null) {
      _outcome = p['outcome'] as String;
      if (p['home_goals'] != null) {
        _exact = true;
        _home = (p['home_goals'] as num).toInt();
        _away = (p['away_goals'] as num).toInt();
      }
    }
  }

  String _derived() => _home > _away ? 'HOME' : (_away > _home ? 'AWAY' : 'DRAW');

  Future<void> _save() async {
    setState(() => _busy = true);
    try {
      final out = _exact ? _derived() : _outcome!;
      final r = await ref.read(apiProvider).predict(context.lang, f['id'] as int, out, _exact ? _home : null, _exact ? _away : null);
      if (!mounted) return;
      setState(() {
        f = r;
        _outcome = out;
      });
      widget.onSaved();
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(context.t.saved)));
    } catch (e) {
      if (mounted) showError(context, e);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _double() async {
    if (!AdService.instance.rewardedReady) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(context.t.adNotReady)));
      return;
    }
    try {
      final api = ref.read(apiProvider);
      final lang = context.lang;
      final res = await watchAdForReward(api, 'DOUBLE_PREDICTION', ref: '${f['id']}');
      if (res?.status == 'CONSUMED') {
        final all = await api.fixtures(lang);
        final updated = all.cast<Map<String, dynamic>>().firstWhere((x) => x['id'] == f['id'], orElse: () => f);
        if (mounted) setState(() => f = updated);
      }
    } catch (e) {
      if (mounted) showError(context, e);
    }
  }

  @override
  Widget build(BuildContext context) {
    final t = context.t;
    final ml = MaterialLocalizations.of(context);
    final kickoff = DateTime.parse(f['kickoff_time'] as String).toLocal();
    final locks = DateTime.parse(f['locks_at'] as String).toLocal();
    final locked = f['locked'] == true;
    final p = _pred;
    final settled = f['status'] == 'FINISHED';
    final sel = _exact ? _derived() : _outcome;
    String fmt(DateTime d) => '${ml.formatShortDate(d)} ${ml.formatTimeOfDay(TimeOfDay.fromDateTime(d))}';

    return Card(
      margin: const EdgeInsets.only(bottom: 12),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Row(children: [
            Expanded(child: Text(f['home_team'] as String, textAlign: TextAlign.center, style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 16))),
            Text(settled ? '${f['home_goals']} - ${f['away_goals']}' : 'VS', style: const TextStyle(fontWeight: FontWeight.w900, color: KoraColors.gold)),
            Expanded(child: Text(f['away_team'] as String, textAlign: TextAlign.center, style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 16))),
          ]),
          const SizedBox(height: 4),
          Text(fmt(kickoff), textAlign: TextAlign.center, style: Theme.of(context).textTheme.bodySmall),
          const SizedBox(height: 12),
          SegmentedButton<String>(
            segments: [
              ButtonSegment(value: 'HOME', label: Text(t.homeWin)),
              ButtonSegment(value: 'DRAW', label: Text(t.draw)),
              ButtonSegment(value: 'AWAY', label: Text(t.awayWin)),
            ],
            emptySelectionAllowed: true,
            selected: {if (sel != null) sel},
            onSelectionChanged: locked || _exact ? null : (s) => setState(() => _outcome = s.isEmpty ? null : s.first),
          ),
          if (!locked) ...[
            SwitchListTile(
              contentPadding: EdgeInsets.zero,
              title: Text(t.exactScore, style: Theme.of(context).textTheme.bodyMedium),
              value: _exact,
              onChanged: (v) => setState(() => _exact = v),
            ),
            if (_exact)
              Row(mainAxisAlignment: MainAxisAlignment.center, children: [
                _Stepper(value: _home, onChanged: (v) => setState(() => _home = v)),
                const Padding(padding: EdgeInsets.symmetric(horizontal: 16), child: Text('-', style: TextStyle(fontSize: 24))),
                _Stepper(value: _away, onChanged: (v) => setState(() => _away = v)),
              ]),
            const SizedBox(height: 8),
            FilledButton(
              onPressed: _busy || (!_exact && _outcome == null) ? null : _save,
              child: Text(t.submitPrediction),
            ),
            if (p != null && p['is_double_points'] != true)
              TextButton.icon(onPressed: _double, icon: const Icon(Icons.play_circle_outline), label: Text(t.doublePoints)),
            Text(t.locksAt(fmt(locks)), textAlign: TextAlign.center, style: Theme.of(context).textTheme.bodySmall),
          ] else
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: Text(
                settled && p != null ? t.earned((p['points_earned'] as num).toInt()) : t.lockedLabel,
                textAlign: TextAlign.center,
                style: const TextStyle(fontWeight: FontWeight.w700),
              ),
            ),
          if (p != null && p['is_double_points'] == true)
            Center(child: Chip(label: Text(t.doubled), avatar: const Icon(Icons.bolt, color: KoraColors.gold))),
        ]),
      ),
    );
  }
}

class _Stepper extends StatelessWidget {
  const _Stepper({required this.value, required this.onChanged});
  final int value;
  final ValueChanged<int> onChanged;

  @override
  Widget build(BuildContext context) => Row(mainAxisSize: MainAxisSize.min, children: [
        IconButton(onPressed: value > 0 ? () => onChanged(value - 1) : null, icon: const Icon(Icons.remove_circle_outline)),
        Text('$value', style: const TextStyle(fontSize: 24, fontWeight: FontWeight.w800)),
        IconButton(onPressed: value < 20 ? () => onChanged(value + 1) : null, icon: const Icon(Icons.add_circle_outline)),
      ]);
}
