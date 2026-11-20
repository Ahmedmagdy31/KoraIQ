import 'package:firebase_auth/firebase_auth.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/ads/ad_service.dart';
import '../../core/api_client.dart';
import '../../core/integrity.dart';
import '../../core/state.dart';
import '../../core/theme.dart';

/// Push topics are per-language so the backend sends one localized message per topic (no fan-out).
Future<void> subscribeTopics(String lang) async {
  final fm = FirebaseMessaging.instance;
  await fm.requestPermission(); // Android 13+ runtime permission
  const topics = ['kickoff', 'season_results', 'daily_lives'];
  final other = lang == 'ar' ? 'en' : 'ar';
  for (final t in topics) {
    await fm.unsubscribeFromTopic('${t}_$other');
    await fm.subscribeToTopic('${t}_$lang');
  }
}

class SplashScreen extends ConsumerStatefulWidget {
  const SplashScreen({super.key});
  @override
  ConsumerState<SplashScreen> createState() => _SplashScreenState();
}

class _SplashScreenState extends ConsumerState<SplashScreen> {
  bool _busy = true;

  @override
  void initState() {
    super.initState();
    Integrity.warmUp();
    AdService.instance.init(); // consent form (if required) appears over the splash
    if (FirebaseAuth.instance.currentUser != null) {
      _enter();
    } else {
      _busy = false;
    }
  }

  Future<void> _signIn({required bool guest}) async {
    setState(() => _busy = true);
    try {
      if (guest) {
        await FirebaseAuth.instance.signInAnonymously();
      } else {
        await FirebaseAuth.instance.signInWithProvider(GoogleAuthProvider());
      }
      await _enter();
    } catch (e) {
      if (!mounted) return;
      setState(() => _busy = false);
      showError(context, e);
    }
  }

  Future<void> _enter() async {
    try {
      final me = await ref.read(apiProvider).sync();
      ref.read(meProvider.notifier).setData(me);
      final lang = (me['locale'] as String?) ?? 'ar';
      ref.read(localeProvider.notifier).set(Locale(lang));
      subscribeTopics(lang).ignore(); // best-effort; never block entry on push setup
      if (!mounted) return;
      context.go(me['needs_onboarding'] == true ? '/onboarding' : '/');
    } catch (e) {
      if (!mounted) return;
      setState(() => _busy = false);
      showError(context, e);
    }
  }

  @override
  Widget build(BuildContext context) {
    final t = context.t;
    return Scaffold(
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            children: [
              const Spacer(),
              const Icon(Icons.sports_soccer, size: 96, color: KoraColors.gold),
              const SizedBox(height: 16),
              Text(t.appTitle, style: Theme.of(context).textTheme.displaySmall?.copyWith(fontWeight: FontWeight.w900)),
              const SizedBox(height: 8),
              Text(t.tagline, textAlign: TextAlign.center),
              const Spacer(),
              if (_busy)
                const CircularProgressIndicator()
              else ...[
                FilledButton.icon(
                  onPressed: () => _signIn(guest: false),
                  icon: const Icon(Icons.login),
                  label: Text(t.signInGoogle),
                ),
                const SizedBox(height: 12),
                OutlinedButton(
                  style: OutlinedButton.styleFrom(minimumSize: const Size.fromHeight(52)),
                  onPressed: () => _signIn(guest: true),
                  child: Text(t.playAsGuest),
                ),
                const SizedBox(height: 8),
                Text(t.guestNote, textAlign: TextAlign.center, style: Theme.of(context).textTheme.bodySmall),
                TextButton(
                  onPressed: () => ref.read(localeProvider.notifier).set(
                        Locale(context.lang == 'ar' ? 'en' : 'ar'),
                      ),
                  child: Text(context.lang == 'ar' ? 'English' : 'العربية'),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}
