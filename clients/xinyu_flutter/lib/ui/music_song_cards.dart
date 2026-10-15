import 'package:flutter/material.dart';

import '../state/companion_controller.dart';

String songReceipt(String? state) => switch (state) {
  'pending' => '等待确认播放',
  'running' => '正在交给网易云',
  'requested' => '已交给网易云 · 播放待确认',
  'verified' => '已确认开始播放',
  'metadata_matched' => '已匹配播放器中的歌曲信息',
  'failed' => '未能打开歌曲',
  'denied' => '已取消播放',
  'uncertain' => '结果待核对，请先查看网易云',
  _ => '',
};

class MusicSongCards extends StatelessWidget {
  const MusicSongCards({
    super.key,
    required this.cards,
    required this.controller,
    this.interactive = true,
    this.onTogether,
  });
  final List<Map<String, dynamic>> cards;
  final CompanionController controller;
  final bool interactive;
  final VoidCallback? onTogether;

  @override
  Widget build(BuildContext context) => SizedBox(
    width: 340,
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        for (final card in cards.take(3))
          _SongCard(
            key: ValueKey('song-${card['search_action_id']}-${card['id']}'),
            card: card,
            controller: controller,
            interactive: interactive,
          ),
        if (onTogether != null && interactive)
          Align(
            alignment: Alignment.centerLeft,
            child: TextButton.icon(
              onPressed: controller.busy ? null : onTogether,
              icon: const Icon(Icons.headphones_rounded, size: 18),
              label: const Text('一起听'),
            ),
          ),
      ],
    ),
  );
}

class _SongCard extends StatefulWidget {
  const _SongCard({
    super.key,
    required this.card,
    required this.controller,
    required this.interactive,
  });
  final Map<String, dynamic> card;
  final CompanionController controller;
  final bool interactive;
  @override
  State<_SongCard> createState() => _SongCardState();
}

class _SongCardState extends State<_SongCard> {
  bool submitting = false;
  String? error;
  Future<void> _play() async {
    final c = widget.controller, card = widget.card;
    final conversation = c.active;
    if (submitting || c.busy || conversation == null) return;
    setState(() {
      submitting = true;
      error = null;
    });
    final pending = card['pending_action_id'] as String?;
    if (pending != null) {
      await c.automation.decide(pending, 'approve');
    } else {
      await c.automation.pickSong(conversation, card);
    }
    if (mounted) {
      setState(() {
        submitting = false;
        error = c.automation.error;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final card = widget.card,
        theme = Theme.of(context),
        colors = theme.colorScheme;
    final artists = (card['artists'] as List? ?? []).whereType<String>().join(
      ' / ',
    );
    final cover = card['cover_url'] as String?;
    final uri = Uri.tryParse(cover ?? '');
    final validCover =
        uri?.scheme == 'https' &&
        RegExp(r'^p[1-9]\.music\.126\.net$').hasMatch(uri?.host ?? '');
    final receipt = submitting
        ? '正在交给网易云…'
        : songReceipt(card['state'] as String?);
    final pending = card['pending_action_id'] != null;
    final blocked = card['state'] == 'uncertain' || card['state'] == 'running';
    return Container(
      margin: const EdgeInsets.only(top: 8),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: colors.surfaceContainerLow,
        border: Border.all(color: colors.outlineVariant),
        borderRadius: BorderRadius.circular(12),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              ExcludeSemantics(
                child: ClipRRect(
                  borderRadius: BorderRadius.circular(8),
                  child: SizedBox(
                    width: 48,
                    height: 48,
                    child: validCover
                        ? Image.network(
                            cover!,
                            fit: BoxFit.cover,
                            errorBuilder: (_, _, _) =>
                                const Icon(Icons.album_outlined, size: 32),
                          )
                        : const Icon(Icons.album_outlined, size: 32),
                  ),
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      card['name'] as String? ?? '歌曲',
                      style: theme.textTheme.bodyLarge?.copyWith(
                        fontWeight: FontWeight.w500,
                      ),
                    ),
                    const SizedBox(height: 4),
                    Text(artists, style: theme.textTheme.bodyMedium),
                    if ((card['album'] as String? ?? '').isNotEmpty)
                      Text(
                        card['album'] as String,
                        style: theme.textTheme.bodySmall,
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                      ),
                  ],
                ),
              ),
            ],
          ),
          if (receipt.isNotEmpty || card['lyric_match'] == true) ...[
            const SizedBox(height: 8),
            Text(
              receipt.isEmpty ? '歌词片段匹配' : receipt,
              style: theme.textTheme.bodySmall,
            ),
          ],
          if (error != null)
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: Text(
                error!,
                style: theme.textTheme.bodySmall?.copyWith(color: colors.error),
              ),
            ),
          if (widget.interactive)
            Align(
              alignment: Alignment.centerRight,
              child: TextButton.icon(
                key: ValueKey('play-song-${card['id']}'),
                style: TextButton.styleFrom(minimumSize: const Size(48, 48)),
                onPressed: widget.controller.busy || submitting || blocked
                    ? null
                    : _play,
                icon: const Icon(Icons.play_arrow_rounded, size: 20),
                label: Text(pending ? '确认播放' : '播放这首'),
              ),
            ),
        ],
      ),
    );
  }
}
