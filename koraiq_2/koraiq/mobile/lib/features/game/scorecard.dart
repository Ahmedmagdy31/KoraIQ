import 'dart:io';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:path_provider/path_provider.dart';
import 'package:qr_flutter/qr_flutter.dart';
import 'package:share_plus/share_plus.dart';

import '../../core/config.dart';
import '../../core/state.dart';
import '../../core/theme.dart';

/// Shareable 4:5 card (fits WhatsApp, Facebook & Instagram Stories without cropping).
class Scorecard extends StatelessWidget {
  const Scorecard({
    super.key,
    required this.boundaryKey,
    required this.nickname,
    required this.club,
    required this.score,
    required this.correct,
    required this.total,
    this.frame,
    this.theme,
  });

  final GlobalKey boundaryKey;
  final String nickname;
  final String? club;
  final int score, correct, total;
  final List<Color>? frame; // equipped avatar frame
  final List<Color>? theme; // equipped scorecard theme (gradient)

  @override
  Widget build(BuildContext context) {
    final t = context.t;
    // Tier by share correct, so 5-question Daily rounds are judged fairly too.
    final ratio = total == 0 ? 0 : correct / total;
    final tier = ratio >= 0.9
        ? t.tierGenius
        : ratio >= 0.6
            ? t.tierPro
            : t.tierRookie;
    final clubColor = KoraColors.club[club] ?? KoraColors.pitch;
    final th = theme;
    final colors = th != null && th.length > 1
        ? th
        : [KoraColors.night, Color.lerp(KoraColors.pitch, clubColor, 0.35)!];
    return RepaintBoundary(
      key: boundaryKey,
      child: AspectRatio(
        aspectRatio: 4 / 5,
        child: Container(
          padding: const EdgeInsets.all(20),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(24),
            gradient: LinearGradient(
              begin: Alignment.topLeft,
              end: Alignment.bottomRight,
              colors: colors,
            ),
          ),
          child: Column(
            children: [
              Row(children: [
                ClubBadge(club, size: 44, frame: frame),
                const SizedBox(width: 10),
                Expanded(
                  child: Text(nickname,
                      style: const TextStyle(color: Colors.white, fontSize: 20, fontWeight: FontWeight.w800),
                      overflow: TextOverflow.ellipsis),
                ),
                Text(t.appTitle, style: const TextStyle(color: KoraColors.gold, fontWeight: FontWeight.w900)),
              ]),
              const Spacer(),
              Text('$correct/$total',
                  style: const TextStyle(color: Colors.white, fontSize: 72, fontWeight: FontWeight.w900, height: 1)),
              const SizedBox(height: 6),
              Text(tier,
                  textAlign: TextAlign.center,
                  style: const TextStyle(color: KoraColors.gold, fontSize: 22, fontWeight: FontWeight.w800)),
              const SizedBox(height: 4),
              Text(t.points(score), style: const TextStyle(color: Colors.white70, fontSize: 16)),
              const Spacer(),
              Row(
                crossAxisAlignment: CrossAxisAlignment.end,
                children: [
                  Expanded(
                    child: Text(t.tagline, style: const TextStyle(color: Colors.white70, fontSize: 13)),
                  ),
                  Container(
                    color: Colors.white,
                    padding: const EdgeInsets.all(4),
                    child: QrImageView(data: AppConfig.playStoreUrl, size: 76, padding: EdgeInsets.zero),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// Renders the RepaintBoundary to PNG locally (no server round-trip) and opens the share sheet.
Future<void> shareScorecard(GlobalKey key, String text) async {
  final boundary = key.currentContext?.findRenderObject() as RenderRepaintBoundary?;
  if (boundary == null) return;
  final image = await boundary.toImage(pixelRatio: 3);
  final bytes = await image.toByteData(format: ui.ImageByteFormat.png);
  if (bytes == null) return;
  final dir = await getTemporaryDirectory();
  final file = File('${dir.path}/koraiq_score.png');
  await file.writeAsBytes(bytes.buffer.asUint8List(), flush: true);
  await Share.shareXFiles([XFile(file.path, mimeType: 'image/png')], text: '$text\n${AppConfig.playStoreUrl}');
}
