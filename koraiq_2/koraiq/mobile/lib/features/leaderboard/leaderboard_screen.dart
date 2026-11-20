import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../core/ads/ad_service.dart';
import '../../core/api_client.dart';
import '../../core/state.dart';
import '../../core/theme.dart';
import '../home/home_screen.dart' show topicsProvider;

typedef _LbKey = ({String lang, String scope});

final leaderboardProvider = FutureProvider.autoDispose.family<Map<String, dynamic>, _LbKey>(
  (ref, k) => ref.read(apiProvider).leaderboard(k.lang, scope: k.scope),
);

class LeaderboardScreen extends ConsumerStatefulWidget {
  const LeaderboardScreen({super.key});
  @override
  ConsumerState<LeaderboardScreen> createState() => _LeaderboardScreenState();
}

class _LeaderboardScreenState extends ConsumerState<LeaderboardScreen> {
  Timer? _tick;
  DateTime? _endsAt;
  String _scope = 'all';

  @override
  void initState() {
    super.initState();
    _tick = Timer.periodic(const Duration(seconds: 1), (_) {
      if (mounted && _endsAt != null) setState(() {});
    });
  }

  @override
  void dispose() {
    _tick?.cancel();
    super.dispose();
  }

  String _countdown() {
    final d = _endsAt!.difference(DateTime.now());
    if (d.isNegative) return '0:00:00';
    final days = d.inDays, h = d.inHours % 24, m = d.inMinutes % 60, s = d.inSeconds % 60;
    String two(int n) => n.toString().padLeft(2, '0');
    return days > 0 ? '${days}d ${two(h)}:${two(m)}:${two(s)}' : '${two(h)}:${two(m)}:${two(s)}';
  }

  @override
  Widget build(BuildContext context) {
    final t = context.t;
    final lang = context.lang;
    final key = (lang: lang, scope: _scope);
    final data = ref.watch(leaderboardProvider(key));
    final topics = ref.watch(topicsProvider(lang)).valueOrNull;
    final topicList = (topics?['topics'] as List?)?.cast<Map<String, dynamic>>() ?? const [];
    return DefaultTabController(
      length: 2,
      child: Scaffold(
        appBar: AppBar(
          title: Text(t.weeklyLeaderboard),
          bottom: TabBar(tabs: [Tab(text: t.global), Tab(text: t.myClub)]),
        ),
        bottomNavigationBar: const BottomBanner(),
        body: Column(children: [
          // Scope chips: All + one board per topic.
          SizedBox(
            height: 52,
            child: ListView(
              scrollDirection: Axis.horizontal,
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 8),
              children: [
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 4),
                  child: ChoiceChip(
                    label: Text(t.global),
                    selected: _scope == 'all',
                    onSelected: (_) => setState(() => _scope = 'all'),
                  ),
                ),
                for (final tp in topicList)
                  Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 4),
                    child: ChoiceChip(
                      avatar: Icon(iconFor(tp['icon'] as String?), size: 18, color: hexColor(tp['color'] as String?)),
                      label: Text('${tp['name']}'),
                      selected: _scope == tp['slug'],
                      onSelected: (_) => setState(() => _scope = tp['slug'] as String),
                    ),
                  ),
              ],
            ),
          ),
          Expanded(
            child: data.when(
              loading: () => const Center(child: CircularProgressIndicator()),
              error: (e, _) =>
                  Center(child: TextButton(onPressed: () => ref.invalidate(leaderboardProvider(key)), child: Text(t.retry))),
              data: (lb) {
                final season = lb['season'] as Map<String, dynamic>;
                // Server-provided seconds_remaining avoids trusting the device clock/timezone.
                _endsAt ??= DateTime.now().add(Duration(seconds: (season['seconds_remaining'] as num).toInt()));
                final sponsor = season['sponsor'] as Map<String, dynamic>?;
                final me = lb['me'] as Map<String, dynamic>;
                return Column(children: [
                  if (sponsor != null) _SponsorCard(sponsor),
                  Padding(
                    padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
                    child: Text(t.resetsIn(_countdown()), style: const TextStyle(fontWeight: FontWeight.w700)),
                  ),
                  Padding(
                    padding: const EdgeInsets.fromLTRB(16, 2, 16, 8),
                    child: Text(t.weeklyRewardsNote,
                        textAlign: TextAlign.center, style: Theme.of(context).textTheme.bodySmall),
                  ),
                  if (me['is_guest'] == true)
                    MaterialBanner(content: Text(t.guestLinkWarning), actions: const [SizedBox.shrink()]),
                  Expanded(
                    child: TabBarView(children: [
                      _Board(rows: lb['global_top'] as List, myRank: me['rank'] as int?),
                      _Board(rows: lb['club_top'] as List, myRank: me['club_rank'] as int?),
                    ]),
                  ),
                  ListTile(
                    tileColor: Theme.of(context).colorScheme.primaryContainer,
                    leading: Text(me['rank'] == null ? '—' : '#${me['rank']}',
                        style: const TextStyle(fontWeight: FontWeight.w900)),
                    title: Text(t.you),
                    trailing: Text(t.points((me['points'] as num).toInt())),
                  ),
                ]);
              },
            ),
          ),
        ]),
      ),
    );
  }
}

class _Board extends StatelessWidget {
  const _Board({required this.rows, required this.myRank});
  final List rows;
  final int? myRank;

  @override
  Widget build(BuildContext context) {
    if (rows.isEmpty) return Center(child: Text(context.t.notRankedYet));
    return ListView.separated(
      itemCount: rows.length,
      separatorBuilder: (_, __) => const Divider(height: 1),
      itemBuilder: (_, i) {
        final r = rows[i] as Map<String, dynamic>;
        final rank = (r['rank'] as num).toInt();
        final medal = switch (rank) { 1 => '🥇', 2 => '🥈', 3 => '🥉', _ => '#$rank' };
        return ListTile(
          selected: rank == myRank,
          leading: SizedBox(
            width: 44,
            child: Center(child: Text(medal, style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w800))),
          ),
          title: Row(children: [
            ClubBadge(r['club'] as String?, size: 22),
            const SizedBox(width: 8),
            Flexible(child: Text('${r['nickname']}', overflow: TextOverflow.ellipsis)),
          ]),
          subtitle: Text(context.t.levelN((r['level'] as num?)?.toInt() ?? 1)),
          trailing: Text('${r['points']}', style: const TextStyle(fontWeight: FontWeight.w700)),
        );
      },
    );
  }
}

class _SponsorCard extends StatelessWidget {
  const _SponsorCard(this.s);
  final Map<String, dynamic> s;

  @override
  Widget build(BuildContext context) {
    final t = context.t;
    final logo = s['logo_url'] as String?;
    final click = s['click_url'] as String?;
    return Card(
      margin: const EdgeInsets.fromLTRB(12, 8, 12, 0),
      color: KoraColors.gold.withValues(alpha: 0.15),
      child: ListTile(
        leading: logo == null
            ? const Icon(Icons.campaign)
            : Image.network(logo, width: 48, height: 48, errorBuilder: (_, __, ___) => const Icon(Icons.campaign)),
        title: Text(t.sponsoredBy('${s['name']}'), style: const TextStyle(fontWeight: FontWeight.w800)),
        subtitle: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          if (s['message'] != null) Text('${s['message']}'),
          if (s['promo_code'] != null) SelectableText(t.promoCode('${s['promo_code']}')),
        ]),
        onTap: click == null ? null : () => launchUrl(Uri.parse(click), mode: LaunchMode.externalApplication),
      ),
    );
  }
}
