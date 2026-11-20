import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../core/api_client.dart';
import '../../core/config.dart';
import '../../core/state.dart';
import '../../core/theme.dart';

class OnboardingScreen extends ConsumerStatefulWidget {
  const OnboardingScreen({super.key});
  @override
  ConsumerState<OnboardingScreen> createState() => _OnboardingScreenState();
}

class _OnboardingScreenState extends ConsumerState<OnboardingScreen> {
  final _nick = TextEditingController();
  String? _club;
  DateTime? _birth;
  bool _terms = false;
  bool _busy = false;
  bool _blocked = false; // neutral age gate: once under-age, the form stays locked this session

  @override
  void initState() {
    super.initState();
    final me = ref.read(meProvider).valueOrNull;
    _nick.text = (me?['nickname'] as String?) ?? '';
    _club = me?['favorite_club'] as String?;
  }

  @override
  void dispose() {
    _nick.dispose();
    super.dispose();
  }

  Future<void> _pickBirth() async {
    final now = DateTime.now();
    final d = await showDatePicker(
      context: context,
      firstDate: DateTime(now.year - 100),
      lastDate: now,
      initialDate: DateTime(now.year - 20), // neutral default: does not hint at the cutoff
      initialEntryMode: DatePickerEntryMode.input,
    );
    if (d != null) setState(() => _birth = d);
  }

  bool get _valid => _nick.text.trim().length >= 3 && _club != null && _birth != null && _terms && !_blocked;

  Future<void> _submit() async {
    setState(() => _busy = true);
    try {
      final me = await ref.read(apiProvider).onboard(
            nickname: _nick.text.trim(),
            club: _club!,
            birthDate: _birth!,
            locale: context.lang,
          );
      ref.read(meProvider.notifier).setData(me);
      if (mounted) context.go('/');
    } catch (e) {
      if (!mounted) return;
      if (e is ApiError && e.code == 'under_minimum_age') setState(() => _blocked = true);
      showError(context, e);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final t = context.t;
    if (_blocked) {
      return Scaffold(body: Center(child: Padding(padding: const EdgeInsets.all(32), child: Text(t.underAge))));
    }
    final clubLocked = ref.read(meProvider).valueOrNull?['favorite_club'] != null;
    return Scaffold(
      appBar: AppBar(title: Text(t.onboardingTitle)),
      body: ListView(
        padding: const EdgeInsets.all(20),
        children: [
          TextField(
            controller: _nick,
            maxLength: 20,
            decoration: InputDecoration(labelText: t.nicknameLabel, helperText: t.nicknameHint, border: const OutlineInputBorder()),
            onChanged: (_) => setState(() {}),
          ),
          const SizedBox(height: 16),
          Text(t.chooseClub, style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 8),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              for (final c in AppConfig.clubs)
                ChoiceChip(
                  avatar: ClubBadge(c, size: 22),
                  label: Text(clubName(t, c)),
                  selected: _club == c,
                  onSelected: clubLocked ? null : (_) => setState(() => _club = c),
                ),
            ],
          ),
          const SizedBox(height: 20),
          ListTile(
            contentPadding: EdgeInsets.zero,
            leading: const Icon(Icons.cake_outlined),
            title: Text(t.birthDateLabel),
            subtitle: Text(_birth == null ? t.birthDatePick : MaterialLocalizations.of(context).formatMediumDate(_birth!)),
            onTap: _pickBirth,
          ),
          CheckboxListTile(
            contentPadding: EdgeInsets.zero,
            value: _terms,
            onChanged: (v) => setState(() => _terms = v ?? false),
            title: Text(t.acceptTerms),
            controlAffinity: ListTileControlAffinity.leading,
          ),
          Wrap(spacing: 12, children: [
            TextButton(onPressed: () => launchUrl(Uri.parse(AppConfig.termsUrl)), child: Text(t.termsOfService)),
            TextButton(onPressed: () => launchUrl(Uri.parse(AppConfig.privacyUrl)), child: Text(t.privacyPolicy)),
          ]),
          const SizedBox(height: 16),
          FilledButton(
            onPressed: _valid && !_busy ? _submit : null,
            child: _busy ? const CircularProgressIndicator() : Text(t.continueBtn),
          ),
        ],
      ),
    );
  }
}
