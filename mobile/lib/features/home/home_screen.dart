import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/ads/ad_service.dart';
import '../../core/ads/rewards.dart';
import '../../core/api_client.dart';
import '../../core/state.dart';
import '../../core/theme.dart';

final topicsProvider = FutureProvider.autoDispose.family<Map<String, dynamic>, String>(
  (ref, lang) => ref.read(apiProvider).topics(lang),
);
final dailyProvider = FutureProvider.autoDispose.family<Map<String, dynamic>, String>(
  (ref, lang) => ref.read(apiProvider).daily(lang),
);

class HomeScreen extends ConsumerWidget {
  const HomeScreen({super.key});

  void _refreshAll(WidgetRef ref, String lang) {
    ref.read(meProvider.notifier).refresh();
    ref.invalidate(topicsProvider(lang));
    ref.invalidate(dailyProvider(lang));
  }

  Future<void> _play(BuildContext context, WidgetRef ref, int lives, String topic) async {
    final lang = context.lang;
    if (lives > 0) {
      await context.push('/play?topic=$topic');
      _refreshAll(ref, lang);
      return;
    }
    final t = context.t;
    final watch = await showDialog<bool>(
      context: context,
      builder: (c) => AlertDialog(
        title: Text(t.noLivesTitle),
        content: Text(t.noLivesBody),
        actions: [
          TextButton(onPressed: () => Navigator.pop(c, false), child: Text(t.cancel)),
          TextButton(
            onPressed: () {
              Navigator.pop(c, false);
              context.push('/shop');
            },
            child: Text(t.shop),
          ),
          FilledButton(
            style: FilledButton.styleFrom(minimumSize: const Size(64, 40)),
            onPressed: () => Navigator.pop(c, true),
            child: Text(t.watchAdForLife),
          ),
        ],
      ),
    );
    if (watch != true || !context.mounted) return;
    if (!AdService.instance.rewardedReady) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(t.adNotReady)));
      return;
    }
    try {
      await watchAdForReward(ref.read(apiProvider), 'EXTRA_LIFE');
      await ref.read(meProvider.notifier).refresh();
    } catch (e) {
      if (context.mounted) showError(context, e);
    }
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final t = context.t;
    final lang = context.lang;
    final me = ref.watch(meProvider);
    return Scaffold(
      appBar: AppBar(
        title: Text(t.appTitle, style: const TextStyle(fontWeight: FontWeight.w900)),
        actions: [
          IconButton(tooltip: t.shop, onPressed: () => context.push('/shop'), icon: const Icon(Icons.storefront_outlined)),
          IconButton(tooltip: t.myProgress, onPressed: () => context.push('/progress'), icon: const Icon(Icons.insights)),
          IconButton(tooltip: t.profile, onPressed: () => context.push('/profile'), icon: const Icon(Icons.person_outline)),
        ],
      ),
      bottomNavigationBar: const BottomBanner(),
      body: me.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => Center(
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            Text(errorText(t, e)),
            TextButton(onPressed: () => ref.read(meProvider.notifier).refresh(), child: Text(t.retry)),
          ]),
        ),
        data: (m) {
          final lives = (m['lives'] as num).toInt();
          return RefreshIndicator(
            onRefresh: () async => _refreshAll(ref, lang),
            child: ListView(
              padding: const EdgeInsets.all(16),
              children: [
                _StatsCard(m),
                const SizedBox(height: 12),
                _DailyCard(onPlay: () async {
                  await context.push('/play?mode=daily');
                  _refreshAll(ref, lang);
                }),
                const SizedBox(height: 16),
                Text(t.topics, style: Theme.of(context).textTheme.titleLarge?.copyWith(fontWeight: FontWeight.w800)),
                const SizedBox(height: 8),
                _TopicGrid(onPick: (slug) => _play(context, ref, lives, slug)),
                const SizedBox(height: 16),
                _Cta(
                  icon: Icons.sports_soccer,
                  title: t.matchPredictor,
                  subtitle: t.matchPredictorSub,
                  color: const Color(0xFF1D4ED8),
                  onTap: () => context.push('/predictor'),
                ),
                _Cta(
                  icon: Icons.emoji_events,
                  title: t.weeklyLeaderboard,
                  subtitle: m['season_rank'] == null ? t.notRankedYet : '#${m['season_rank']}',
                  color: const Color(0xFFB45309),
                  onTap: () => context.push('/leaderboard'),
                ),
              ],
            ),
          );
        },
      ),
    );
  }
}

class _StatsCard extends StatelessWidget {
  const _StatsCard(this.m);
  final Map<String, dynamic> m;

  @override
  Widget build(BuildContext context) {
    final t = context.t;
    final level = (m['level'] as num).toInt();
    final xp = (m['xp'] as num).toInt();
    final lo = (m['xp_level_start'] as num).toInt();
    final hi = (m['xp_next_level'] as num).toInt();
    final equipped = m['equipped'] as Map<String, dynamic>? ?? const {};
    final title = equipped['title'] as Map<String, dynamic>?;
    final streak = (m['streak_days'] as num).toInt();
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Row(children: [
            ClubBadge(m['favorite_club'] as String?, size: 44, frame: cosmeticColors(equipped['frame'])),
            const SizedBox(width: 12),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text('${m['nickname'] ?? ''}', style: Theme.of(context).textTheme.titleLarge),
                Text(title == null ? t.levelN(level) : '${t.levelN(level)} · ${title[context.lang == 'ar' ? 'name_ar' : 'name_en']}'),
              ]),
            ),
            _Pill(icon: Icons.local_fire_department, color: Colors.deepOrange, text: '$streak'),
            const SizedBox(width: 6),
            _Pill(icon: Icons.monetization_on, color: KoraColors.gold, text: '${m['coins']}'),
          ]),
          const SizedBox(height: 12),
          LinearProgressIndicator(
            value: hi > lo ? (xp - lo) / (hi - lo) : 0,
            minHeight: 8,
            borderRadius: BorderRadius.circular(8),
          ),
          const SizedBox(height: 4),
          Text(t.xpToNext(hi - xp, level + 1), style: Theme.of(context).textTheme.bodySmall),
          const Divider(height: 24),
          Row(children: [
            _stat(context, t.lives, '${m['lives']}'),
            _stat(context, t.weeklyRank, m['season_rank'] == null ? '—' : '#${m['season_rank']}'),
            _stat(context, t.weeklyPoints, '${m['season_points']}'),
            _stat(context, t.totalPoints, '${m['all_time_points']}'),
          ]),
        ]),
      ),
    );
  }

  Widget _stat(BuildContext context, String label, String value) => Expanded(
        child: Column(children: [
          Text(value, style: Theme.of(context).textTheme.titleLarge?.copyWith(fontWeight: FontWeight.w800)),
          Text(label, style: Theme.of(context).textTheme.bodySmall, textAlign: TextAlign.center),
        ]),
      );
}

class _Pill extends StatelessWidget {
  const _Pill({required this.icon, required this.color, required this.text});
  final IconData icon;
  final Color color;
  final String text;

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
        decoration: BoxDecoration(color: color.withValues(alpha: 0.15), borderRadius: BorderRadius.circular(20)),
        child: Row(mainAxisSize: MainAxisSize.min, children: [
          Icon(icon, size: 18, color: color),
          const SizedBox(width: 4),
          Text(text, style: const TextStyle(fontWeight: FontWeight.w800)),
        ]),
      );
}

class _DailyCard extends ConsumerWidget {
  const _DailyCard({required this.onPlay});
  final VoidCallback onPlay;

  String _hms(int s) => '${s ~/ 3600}:${((s % 3600) ~/ 60).toString().padLeft(2, '0')}';

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final t = context.t;
    final d = ref.watch(dailyProvider(context.lang)).valueOrNull;
    if (d == null) return const SizedBox.shrink();
    final topic = d['topic'] as Map<String, dynamic>?;
    final played = d['played'] == true;
    final result = d['result'] as Map<String, dynamic>?;
    final grid = (result?['grid'] as List?)?.map((c) => c == true ? '🟩' : '🟥').join() ?? '';
    return Card(
      color: hexColor(topic?['color'] as String?).withValues(alpha: 0.18),
      child: ListTile(
        contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
        leading: Icon(iconFor(topic?['icon'] as String?), size: 36),
        title: Text('${t.dailyChallenge} · ${t.dailyNumber((d['number'] as num).toInt())}',
            style: const TextStyle(fontWeight: FontWeight.w800)),
        subtitle: Text(played
            ? '$grid\n${t.dailyDone(_hms((d['seconds_until_next'] as num).toInt()))}'
            : '${topic?['name'] ?? ''} · ${t.dailySub}'),
        trailing: played ? null : const Icon(Icons.play_circle_fill, size: 36),
        onTap: played ? null : onPlay,
      ),
    );
  }
}

class _TopicGrid extends ConsumerWidget {
  const _TopicGrid({required this.onPick});
  final void Function(String slug) onPick;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final t = context.t;
    final data = ref.watch(topicsProvider(context.lang)).valueOrNull;
    if (data == null) return const Center(child: Padding(padding: EdgeInsets.all(16), child: CircularProgressIndicator()));
    final topics = (data['topics'] as List).cast<Map<String, dynamic>>();
    final tiles = <Widget>[
      _TopicTile(
        icon: Icons.shuffle,
        color: KoraColors.pitch,
        name: t.mixed,
        sub: t.mixedSub,
        onTap: () => onPick(data['mixed_slug'] as String),
      ),
      for (final tp in topics)
        _TopicTile(
          icon: iconFor(tp['icon'] as String?),
          color: hexColor(tp['color'] as String?),
          name: '${tp['name']}',
          sub: () {
            final mastery = tp['mastery'] as Map<String, dynamic>;
            final tier = mastery['tier'] as String?;
            final c = (mastery['correct'] as num).toInt();
            return tier == null ? t.correctAnswers(c) : '${tierName(t, tier)} · ${t.correctAnswers(c)}';
          }(),
          onTap: () => onPick(tp['slug'] as String),
        ),
    ];
    return GridView.count(
      crossAxisCount: 2,
      shrinkWrap: true,
      physics: const NeverScrollableScrollPhysics(),
      mainAxisSpacing: 10,
      crossAxisSpacing: 10,
      childAspectRatio: 1.45,
      children: tiles,
    );
  }
}

class _TopicTile extends StatelessWidget {
  const _TopicTile({required this.icon, required this.color, required this.name, required this.sub, required this.onTap});
  final IconData icon;
  final Color color;
  final String name, sub;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) => Material(
        color: color,
        borderRadius: BorderRadius.circular(20),
        child: InkWell(
          borderRadius: BorderRadius.circular(20),
          onTap: onTap,
          child: Padding(
            padding: const EdgeInsets.all(12),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
              Icon(icon, color: Colors.white, size: 30),
              Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(name,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w800, fontSize: 16)),
                Text(sub, maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(color: Colors.white70, fontSize: 12)),
              ]),
            ]),
          ),
        ),
      );
}

class _Cta extends StatelessWidget {
  const _Cta({required this.icon, required this.title, required this.subtitle, required this.color, required this.onTap});
  final IconData icon;
  final String title, subtitle;
  final Color color;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) => Card(
        color: color,
        margin: const EdgeInsets.only(bottom: 12),
        child: ListTile(
          contentPadding: const EdgeInsets.symmetric(horizontal: 20, vertical: 12),
          leading: Icon(icon, color: Colors.white, size: 36),
          title: Text(title, style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w800, fontSize: 18)),
          subtitle: Text(subtitle, style: const TextStyle(color: Colors.white70)),
          trailing: const Icon(Icons.chevron_right, color: Colors.white),
          onTap: onTap,
        ),
      );
}
