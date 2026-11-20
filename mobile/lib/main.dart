import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import 'core/state.dart';
import 'core/theme.dart';
import 'features/auth/onboarding_screen.dart';
import 'features/auth/splash_screen.dart';
import 'features/game/game_screen.dart';
import 'features/home/home_screen.dart';
import 'features/leaderboard/leaderboard_screen.dart';
import 'features/predictor/predictor_screen.dart';
import 'features/profile/profile_screen.dart';
import 'features/progress/progress_screen.dart';
import 'features/shop/shop_screen.dart';
import 'l10n/app_localizations.dart';

@pragma('vm:entry-point')
Future<void> _bgMessage(RemoteMessage message) async {
  // Notification payloads are displayed by the OS; nothing to do in the background isolate.
}

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  // Requires android/app/google-services.json (FlutterFire CLI: `flutterfire configure`).
  await Firebase.initializeApp();
  FirebaseMessaging.onBackgroundMessage(_bgMessage);
  runApp(const ProviderScope(child: KoraApp()));
}

final _router = GoRouter(
  initialLocation: '/splash',
  routes: [
    GoRoute(path: '/splash', builder: (_, __) => const SplashScreen()),
    GoRoute(path: '/onboarding', builder: (_, __) => const OnboardingScreen()),
    GoRoute(path: '/', builder: (_, __) => const HomeScreen()),
    GoRoute(
      path: '/play',
      builder: (_, state) => GameScreen(
        topic: state.uri.queryParameters['topic'] ?? 'mixed',
        daily: state.uri.queryParameters['mode'] == 'daily',
      ),
    ),
    GoRoute(path: '/shop', builder: (_, __) => const ShopScreen()),
    GoRoute(path: '/progress', builder: (_, __) => const ProgressScreen()),
    GoRoute(path: '/predictor', builder: (_, __) => const PredictorScreen()),
    GoRoute(path: '/leaderboard', builder: (_, __) => const LeaderboardScreen()),
    GoRoute(path: '/profile', builder: (_, __) => const ProfileScreen()),
  ],
);

class KoraApp extends ConsumerWidget {
  const KoraApp({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return MaterialApp.router(
      onGenerateTitle: (c) => c.t.appTitle,
      debugShowCheckedModeBanner: false,
      locale: ref.watch(localeProvider),
      supportedLocales: AppLocalizations.supportedLocales,
      localizationsDelegates: const [
        AppLocalizations.delegate,
        GlobalMaterialLocalizations.delegate,
        GlobalWidgetsLocalizations.delegate, // provides RTL Directionality for Arabic
        GlobalCupertinoLocalizations.delegate,
      ],
      theme: buildTheme(Brightness.light),
      darkTheme: buildTheme(Brightness.dark),
      themeMode: ThemeMode.system,
      routerConfig: _router,
    );
  }
}
