import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import '../../core/state.dart';
import '../../core/theme.dart';

final progressProvider = FutureProvider.autoDispose.family<Map<String, dynamic>, String>(
  (ref, lang) => ref.read(apiProvider).progress(lang),
);

class ProgressScreen extends ConsumerWidget {
  const ProgressScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final t = context.t;
    final data = ref.watch(progressProvider(context.lang));
    return Scaffold(
      appBar: AppBar(title: Text(t.myProgress)),
      body: data.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => Center(
          child: TextButton(onPressed: () => ref.invalidate(progressProvider(context.lang)), child: Text(t.retry)),
        ),
        data: (p) {
          final level = (p['level'] as num).toInt();
          final xp = (p['xp'] as num).toInt();
          final lo = (p['xp_level_start'] as num).toInt();
          final hi = (p['xp_next_level'] as num).toInt();
          final mastery = (p['mastery'] as List).cast<Map<String, dynamic>>();
          final badges = (p['badges'] as List).cast<Map<String, dynamic>>();
          return ListView(
            padding: const EdgeInsets.all(16),
            children: [
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(16),
                  child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                    Text(t.levelN(level), style: Theme.of(context).textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w900)),
                    const SizedBox(height: 8),
                    LinearProgressIndicator(
                      value: hi > lo ? (xp - lo) / (hi - lo) : 0,
                      minHeight: 10,
                      borderRadius: BorderRadius.circular(8),
                    ),
                    const SizedBox(height: 4),
                    Text(t.xpToNext(hi - xp, level + 1)),
                    const Divider(height: 24),
                    Row(children: [
                      const Icon(Icons.local_fire_department, color: Colors.deepOrange),
                      const SizedBox(width: 6),
                      Text(t.streakDays((p['streak_days'] as num).toInt())),
                      const Spacer(),
                      const Icon(Icons.ac_unit, color: Colors.lightBlue),
                      const SizedBox(width: 4),
                      Text('${p['streak_freezes']}'),
                      const SizedBox(width: 16),
                      const Icon(Icons.monetization_on, color: KoraColors.gold),
                      const SizedBox(width: 4),
                      Text('${p['coins']}'),
                    ]),
                  ]),
                ),
              ),
              const SizedBox(height: 8),
              Text(t.topics, style: Theme.of(context).textTheme.titleLarge?.copyWith(fontWeight: FontWeight.w800)),
              for (final m in mastery) _MasteryTile(m),
              const SizedBox(height: 16),
              Text(t.badges, style: Theme.of(context).textTheme.titleLarge?.copyWith(fontWeight: FontWeight.w800)),
              const SizedBox(height: 8),
              GridView.count(
                crossAxisCount: 3,
                shrinkWrap: true,
                physics: const NeverScrollableScrollPhysics(),
                mainAxisSpacing: 8,
                crossAxisSpacing: 8,
                childAspectRatio: 0.85,
                children: [for (final b in badges) _BadgeTile(b)],
              ),
            ],
          );
        },
      ),
    );
  }
}

class _MasteryTile extends StatelessWidget {
  const _MasteryTile(this.m);
  final Map<String, dynamic> m;

  @override
  Widget build(BuildContext context) {
    final t = context.t;
    final correct = (m['correct'] as num).toInt();
    final next = m['next'] as List?; // [tier, threshold] or null at the top tier
    final color = hexColor(m['color'] as String?);
    final tier = m['tier'] as String?;
    return Card(
      child: ListTile(
        leading: CircleAvatar(backgroundColor: color, child: Icon(iconFor(m['icon'] as String?), color: Colors.white)),
        title: Text('${m['name']}', style: const TextStyle(fontWeight: FontWeight.w700)),
        subtitle: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(tier == null ? t.correctAnswers(correct) : '${tierName(t, tier)} · ${t.correctAnswers(correct)}'),
          if (next != null) ...[
            const SizedBox(height: 4),
            LinearProgressIndicator(value: (correct / (next[1] as num)).clamp(0, 1).toDouble(), color: color),
            Text(t.nextTierAt(tierName(t, next[0] as String), (next[1] as num).toInt()),
                style: Theme.of(context).textTheme.bodySmall),
          ],
        ]),
      ),
    );
  }
}

class _BadgeTile extends StatelessWidget {
  const _BadgeTile(this.b);
  final Map<String, dynamic> b;

  @override
  Widget build(BuildContext context) {
    final earned = b['earned'] == true;
    return Tooltip(
      message: '${b['description']}',
      triggerMode: TooltipTriggerMode.tap,
      child: Opacity(
        opacity: earned ? 1 : 0.35,
        child: Card(
          child: Padding(
            padding: const EdgeInsets.all(8),
            child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
              Icon(iconFor(b['icon'] as String?), size: 36, color: earned ? KoraColors.gold : null),
              const SizedBox(height: 6),
              Text('${b['name']}',
                  textAlign: TextAlign.center, maxLines: 2, overflow: TextOverflow.ellipsis, style: const TextStyle(fontSize: 12)),
            ]),
          ),
        ),
      ),
    );
  }
}
