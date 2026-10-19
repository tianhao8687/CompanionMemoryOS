import 'dart:async';

import 'package:flutter/material.dart';

import '../data/speech_models.dart';
import 'glass.dart';

class SpeechModelCard extends StatelessWidget {
  const SpeechModelCard({
    super.key,
    required this.models,
    required this.active,
  });
  final SpeechModels models;
  final bool active;

  @override
  Widget build(BuildContext context) {
    final downloading = models.phase == SpeechModelPhase.downloading;
    final checking =
        models.phase == SpeechModelPhase.checking ||
        models.phase == SpeechModelPhase.unchecked;
    final size = (models.total / 1048576).ceil();
    return Padding(
      padding: const EdgeInsets.only(top: 12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text(
            models.ready
                ? '离线语音已就绪 · 中英文'
                : checking
                ? '正在检查本地语音资源…'
                : '准备离线语音',
            style: const TextStyle(fontSize: 14, color: XinYuColors.accent),
          ),
          if (!models.ready && !checking) ...[
            const SizedBox(height: 6),
            Text(
              '首次需联网下载约 $size MiB，建议使用 Wi-Fi。下载完成后无需联网或账号，不收取识别费用。',
              style: const TextStyle(fontSize: 12, color: XinYuColors.muted),
            ),
          ],
          if (downloading) ...[
            const SizedBox(height: 8),
            LinearProgressIndicator(
              value: models.total > 0 ? models.received / models.total : null,
              semanticsLabel: '语音资源下载进度',
            ),
            Text(
              '${(models.received / 1048576).toStringAsFixed(1)} / $size MiB',
              style: const TextStyle(fontSize: 12),
            ),
            TextButton(
              onPressed: () => unawaited(models.cancelDownload()),
              child: const Text('取消下载'),
            ),
          ] else if (!models.ready && !checking) ...[
            const SizedBox(height: 8),
            OutlinedButton.icon(
              key: const Key('voice-download'),
              style: OutlinedButton.styleFrom(
                minimumSize: const Size.fromHeight(48),
              ),
              onPressed: active ? null : () => unawaited(models.download()),
              icon: const Icon(Icons.download_rounded),
              label: Text(
                models.phase == SpeechModelPhase.error ? '重试下载' : '下载免费语音资源',
              ),
            ),
          ],
          if (models.message.isNotEmpty)
            Semantics(
              liveRegion: true,
              child: Text(
                models.message,
                style: const TextStyle(fontSize: 13, color: XinYuColors.ink),
              ),
            ),
        ],
      ),
    );
  }
}
