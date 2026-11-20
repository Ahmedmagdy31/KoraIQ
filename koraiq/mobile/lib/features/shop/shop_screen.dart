import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/ads/ad_service.dart';
import '../../core/ads/rewards.dart';
import '../../core/api_client.dart';
import '../../core/state.dart';
import '../../core/theme.dart';

final shopProvider = FutureProvider.autoDispose.family<Map<String, dynamic>, String>(
  (ref, lang) => ref.read(apiProvider).shop(lang),
);

/// Coins are earned by playing (or rewarded videos), never bought: no payments anywhere in this screen.
class ShopScreen extends ConsumerWidget {
  const ShopScreen({super.key});

  Future<void> _run(BuildContext context, WidgetRef ref, Future<void> Function() action) async {
    final lang = context.lang;
    try {
      await action();
    } catch (e) {
      if (context.mounted) showError(context, e);
    }
    ref.invalidate(shopProvider(lang));
    ref.read(meProvider.notifier).refresh();
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final t = context.t;
    final api = ref.read(apiProvider);
    final data = ref.watch(shopProvider(context.lang));
    return Scaffold(
      appBar: AppBar(title: Text(t.shop)),
      bottomNavigationBar: const BottomBanner(),
      body: data.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => Center(
          child: TextButton(onPressed: () => ref.invalidate(shopProvider(context.lang)), child: Text(t.retry)),
        ),
        data: (s) {
          final items = (s['items'] as List).cast<Map<String, dynamic>>();
          final cosmetics = (s['cosmetics'] as List).cast<Map<String, dynamic>>();
          final freeze = items.firstWhere((i) => i['code'] == 'STREAK_FREEZE');
          final life = items.firstWhere((i) => i['code'] == 'EXTRA_LIFE');
          Widget section(String title, String kind) {
            final list = cosmetics.where((c) => c['kind'] == kind).toList();
            if (list.isEmpty) return const SizedBox.shrink();
            return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Padding(
                padding: const EdgeInsets.fromLTRB(4, 16, 4, 8),
                child: Text(title, style: Theme.of(context).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w800)),
              ),
              for (final c in list)
                _CosmeticTile(
                  c,
                  onBuy: () => _run(context, ref, () => api.buy(c['code'] as String)),
                  onEquip: () => _run(
                    context,
                    ref,
                    () => api.equip(kind, c['equipped'] == true ? null : c['code'] as String),
                  ),
                ),
            ]);
          }

          return ListView(
            padding: const EdgeInsets.all(16),
            children: [
              Card(
                child: ListTile(
                  leading: const Icon(Icons.monetization_on, color: KoraColors.gold, size: 36),
                  title: Text('${s['coins']}', style: Theme.of(context).textTheme.headlineSmall),
                  subtitle: Text(t.coins),
                  trailing: TextButton(
                    onPressed: () {
                      if (!AdService.instance.rewardedReady) {
                        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(t.adNotReady)));
                        return;
                      }
                      _run(context, ref, () => watchAdForReward(api, 'COIN_BONUS'));
                    },
                    child: Text(t.watchAdCoins),
                  ),
                ),
              ),
              _ItemTile(
                icon: Icons.ac_unit,
                title: t.streakFreeze,
                subtitle: t.streakFreezeDesc((freeze['owned'] as num).toInt(), (freeze['max'] as num).toInt()),
                price: (freeze['price'] as num).toInt(),
                enabled: (freeze['owned'] as num) < (freeze['max'] as num),
                onBuy: () => _run(context, ref, () => api.buy('STREAK_FREEZE')),
              ),
              _ItemTile(
                icon: Icons.favorite,
                title: t.extraLife,
                subtitle: t.extraLifeDesc((life['bought_today'] as num).toInt(), (life['max'] as num).toInt()),
                price: (life['price'] as num).toInt(),
                enabled: (life['bought_today'] as num) < (life['max'] as num),
                onBuy: () => _run(context, ref, () => api.buy('EXTRA_LIFE')),
              ),
              section(t.frames, 'FRAME'),
              section(t.themes, 'THEME'),
              section(t.titles, 'TITLE'),
            ],
          );
        },
      ),
    );
  }
}

class _ItemTile extends StatelessWidget {
  const _ItemTile({
    required this.icon,
    required this.title,
    required this.subtitle,
    required this.price,
    required this.enabled,
    required this.onBuy,
  });
  final IconData icon;
  final String title, subtitle;
  final int price;
  final bool enabled;
  final VoidCallback onBuy;

  @override
  Widget build(BuildContext context) => Card(
        child: ListTile(
          leading: Icon(icon, size: 32),
          title: Text(title, style: const TextStyle(fontWeight: FontWeight.w700)),
          subtitle: Text(subtitle),
          trailing: FilledButton.tonal(
            style: FilledButton.styleFrom(minimumSize: const Size(88, 40)),
            onPressed: enabled ? onBuy : null,
            child: Text('$price'),
          ),
        ),
      );
}

class _CosmeticTile extends StatelessWidget {
  const _CosmeticTile(this.c, {required this.onBuy, required this.onEquip});
  final Map<String, dynamic> c;
  final VoidCallback onBuy, onEquip;

  @override
  Widget build(BuildContext context) {
    final t = context.t;
    final colors = cosmeticColors(c);
    final owned = c['owned'] == true;
    final equipped = c['equipped'] == true;
    final Widget preview = switch (c['kind']) {
      'FRAME' => ClubBadge(null, size: 36, frame: colors),
      'THEME' => Container(
          width: 44,
          height: 44,
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(10),
            gradient: LinearGradient(colors: colors ?? const [KoraColors.night, KoraColors.pitch]),
          ),
        ),
      _ => const Icon(Icons.badge_outlined, size: 32),
    };
    return Card(
      child: ListTile(
        leading: preview,
        title: Text('${c['name']}', style: const TextStyle(fontWeight: FontWeight.w700)),
        subtitle: c['exclusive'] == true ? Text(t.exclusive) : null,
        trailing: owned
            ? OutlinedButton(onPressed: onEquip, child: Text(equipped ? t.unequip : t.equip))
            : FilledButton.tonal(
                style: FilledButton.styleFrom(minimumSize: const Size(88, 40)),
                onPressed: onBuy,
                child: Text('${c['price']}'),
              ),
      ),
    );
  }
}
