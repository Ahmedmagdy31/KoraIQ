import 'package:firebase_auth/firebase_auth.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../core/ads/ad_service.dart';
import '../../core/api_client.dart';
import '../../core/config.dart';
import '../../core/state.dart';
import '../../core/theme.dart';
import '../auth/splash_screen.dart' show subscribeTopics;

class ProfileScreen extends ConsumerStatefulWidget {
  const ProfileScreen({super.key});
  @override
  ConsumerState<ProfileScreen> createState() => _ProfileScreenState();
}

class _ProfileScreenState extends ConsumerState<ProfileScreen> {
  bool _privacyOptions = false;

  @override
  void initState() {
    super.initState();
    AdService.instance.privacyOptionsRequired().then((v) {
      if (mounted) setState(() => _privacyOptions = v);
    });
  }

  Future<void> _setLang(String lang) async {
    ref.read(localeProvider.notifier).set(Locale(lang));
    try {
      await ref.read(apiProvider).setLocale(lang); // server sends pushes / content in this language
      await subscribeTopics(lang);
    } catch (_) {}
  }

  Future<void> _linkGoogle() async {
    try {
      await FirebaseAuth.instance.currentUser!.linkWithProvider(GoogleAuthProvider());
      await FirebaseAuth.instance.currentUser!.getIdToken(true); // new token => sign_in_provider=google.com
      ref.read(meProvider.notifier).setData(await ref.read(apiProvider).sync());
    } catch (e) {
      if (mounted) showError(context, e);
    }
  }

  Future<void> _delete() async {
    final t = context.t;
    final ok = await showDialog<bool>(
      context: context,
      builder: (c) => AlertDialog(
        title: Text(t.deleteConfirmTitle),
        content: Text(t.deleteConfirmBody),
        actions: [
          TextButton(onPressed: () => Navigator.pop(c, false), child: Text(t.cancel)),
          FilledButton(
            style: FilledButton.styleFrom(backgroundColor: KoraColors.wrong, minimumSize: const Size(88, 44)),
            onPressed: () => Navigator.pop(c, true),
            child: Text(t.delete),
          ),
        ],
      ),
    );
    if (ok != true) return;
    try {
      await ref.read(apiProvider).deleteAccount(); // server also deletes the Firebase Auth user
      await FirebaseAuth.instance.signOut();
      ref.invalidate(meProvider);
      if (mounted) context.go('/splash');
    } catch (e) {
      if (mounted) showError(context, e);
    }
  }

  Future<void> _signOut() async {
    await FirebaseAuth.instance.signOut();
    ref.invalidate(meProvider);
    if (mounted) context.go('/splash');
  }

  @override
  Widget build(BuildContext context) {
    final t = context.t;
    final me = ref.watch(meProvider).valueOrNull ?? const {};
    return Scaffold(
      appBar: AppBar(title: Text(t.profile)),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          ListTile(
            leading: ClubBadge(me['favorite_club'] as String?),
            title: Text('${me['nickname'] ?? ''}', style: Theme.of(context).textTheme.titleLarge),
            subtitle: Text(clubName(t, me['favorite_club'] as String?)),
          ),
          const Divider(),
          ListTile(
            title: Text(t.language),
            trailing: SegmentedButton<String>(
              segments: const [ButtonSegment(value: 'ar', label: Text('عربي')), ButtonSegment(value: 'en', label: Text('EN'))],
              selected: {context.lang},
              onSelectionChanged: (s) => _setLang(s.first),
            ),
          ),
          if (me['is_guest'] == true)
            ListTile(
              leading: const Icon(Icons.link),
              title: Text(t.linkGoogle),
              subtitle: Text(t.guestLinkWarning),
              onTap: _linkGoogle,
            ),
          ListTile(
            leading: const Icon(Icons.privacy_tip_outlined),
            title: Text(t.privacyPolicy),
            onTap: () => launchUrl(Uri.parse(AppConfig.privacyUrl)),
          ),
          ListTile(
            leading: const Icon(Icons.description_outlined),
            title: Text(t.termsOfService),
            onTap: () => launchUrl(Uri.parse(AppConfig.termsUrl)),
          ),
          if (_privacyOptions)
            ListTile(
              leading: const Icon(Icons.tune),
              title: Text(t.privacySettings),
              onTap: AdService.instance.showPrivacyOptions,
            ),
          ListTile(leading: const Icon(Icons.logout), title: Text(t.signOut), onTap: _signOut),
          const Divider(),
          ListTile(
            leading: const Icon(Icons.delete_forever, color: KoraColors.wrong),
            title: Text(t.deleteAccount, style: const TextStyle(color: KoraColors.wrong, fontWeight: FontWeight.w700)),
            onTap: _delete,
          ),
        ],
      ),
    );
  }
}
