import 'package:flutter/material.dart';

/// Pitch green + trophy gold. Club accents are colors only: no official crests (trademarks).
class KoraColors {
  static const pitch = Color(0xFF0B8F4D);
  static const gold = Color(0xFFF4B400);
  static const night = Color(0xFF0E1512);
  static const correct = Color(0xFF22C55E);
  static const wrong = Color(0xFFEF4444);

  static const club = <String, Color>{
    'AHLY': Color(0xFFC8102E),
    'ZAMALEK': Color(0xFFF5F5F5),
    'PYRAMIDS': Color(0xFF1E3A8A),
    'ISMAILY': Color(0xFFFFD100),
    'ITTIHAD': Color(0xFF15803D),
    'MASRY': Color(0xFF16A34A),
    'OTHER': Color(0xFF9CA3AF),
  };
}

ThemeData buildTheme(Brightness b) {
  final scheme = ColorScheme.fromSeed(seedColor: KoraColors.pitch, brightness: b, secondary: KoraColors.gold);
  return ThemeData(
    useMaterial3: true,
    colorScheme: scheme,
    scaffoldBackgroundColor: b == Brightness.dark ? KoraColors.night : null,
    fontFamily: 'Roboto', // Android falls back to Noto Sans Arabic for Arabic glyphs
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        minimumSize: const Size.fromHeight(56),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
        textStyle: const TextStyle(fontSize: 17, fontWeight: FontWeight.w700),
      ),
    ),
    cardTheme: CardThemeData(shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20))),
  );
}

/// '#RRGGBB' -> Color (server-provided topic/cosmetic colors).
Color hexColor(String? hex, [Color fallback = KoraColors.pitch]) {
  if (hex == null || hex.length != 7 || !hex.startsWith('#')) return fallback;
  final v = int.tryParse(hex.substring(1), radix: 16);
  return v == null ? fallback : Color(0xFF000000 | v);
}

/// Colors of an equipped cosmetic ({"asset": {"colors": [...]}}) or null.
List<Color>? cosmeticColors(Object? equipped) {
  if (equipped is! Map) return null;
  final asset = equipped['asset'];
  final colors = asset is Map ? asset['colors'] : null;
  if (colors is! List || colors.isEmpty) return null;
  return [for (final c in colors) hexColor(c as String?)];
}

/// Material icon names the server may send for topics/badges.
IconData iconFor(String? name) => switch (name) {
      'sports_soccer' => Icons.sports_soccer,
      'explore' => Icons.explore,
      'restaurant' => Icons.restaurant,
      'record_voice_over' => Icons.record_voice_over,
      'workspace_premium' => Icons.workspace_premium,
      'bolt' => Icons.bolt,
      'today' => Icons.today,
      'local_fire_department' => Icons.local_fire_department,
      'public' => Icons.public,
      'stadium' => Icons.stadium,
      'nightlight' => Icons.nightlight,
      'emoji_events' => Icons.emoji_events,
      'military_tech' => Icons.military_tech,
      'shuffle' => Icons.shuffle,
      _ => Icons.quiz,
    };

/// Circular club badge built from club colors (no copyrighted logos), optionally inside an equipped frame.
class ClubBadge extends StatelessWidget {
  const ClubBadge(this.club, {super.key, this.size = 40, this.frame});
  final String? club;
  final double size;
  final List<Color>? frame;

  @override
  Widget build(BuildContext context) {
    final c = KoraColors.club[club] ?? KoraColors.club['OTHER']!;
    final fg = c.computeLuminance() > 0.5 ? Colors.black87 : Colors.white;
    final badge = Container(
      width: size,
      height: size,
      alignment: Alignment.center,
      decoration: BoxDecoration(color: c, shape: BoxShape.circle, border: Border.all(color: KoraColors.gold, width: 2)),
      child: Icon(Icons.shield, color: fg, size: size * 0.55),
    );
    final f = frame;
    if (f == null) return badge;
    return Container(
      padding: EdgeInsets.all(size * 0.08),
      decoration: BoxDecoration(
        shape: BoxShape.circle,
        gradient: LinearGradient(colors: f.length > 1 ? f : [f.first, f.first]),
      ),
      child: badge,
    );
  }
}
