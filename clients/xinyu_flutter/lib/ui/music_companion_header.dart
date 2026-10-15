import 'package:flutter/material.dart';

import '../state/companion_controller.dart';
import 'local_image.dart';
import 'music_style.dart';

class MusicCompanionHeader extends StatelessWidget {
  const MusicCompanionHeader({super.key, required this.controller});
  final CompanionController controller;
  @override
  Widget build(BuildContext context) {
    final c = controller;
    final avatar = c.settings['companion_avatar'] as String?;
    final large = MediaQuery.textScalerOf(context).scale(16) > 24;
    return Row(
      children: [
        if (!large) ...[
          ClipOval(
            child: SizedBox.square(
              dimension: 36,
              child: avatar == null
                  ? const ColoredBox(
                      color: Color(0x20ffffff),
                      child: Icon(Icons.person_outline_rounded, size: 22),
                    )
                  : LocalImage(
                      controller: c,
                      id: avatar,
                      fallback: const Icon(Icons.person_outline_rounded),
                    ),
            ),
          ),
          const SizedBox(width: 10),
        ],
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                c.companionDisplayName,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(
                  fontSize: 17,
                  fontWeight: FontWeight.w500,
                ),
              ),
              if (!large)
                Text(
                  c.music.quiet ? '安静陪着你' : '陪你一起听',
                  style: MusicStyle.note.copyWith(fontSize: 12),
                ),
            ],
          ),
        ),
        TextButton(
          key: const Key('music-quiet'),
          onPressed: c.music.busy || !c.music.active
              ? null
              : () => c.music.act('quiet', silent: !c.music.quiet),
          child: Text(
            c.music.quiet ? '可以说点话' : '安静陪我',
            style: const TextStyle(fontSize: 13),
          ),
        ),
        IconButton(
          tooltip: 'AI 能听到什么',
          onPressed: () => showDialog<void>(
            context: context,
            builder: (context) => AlertDialog(
              title: const Text('AI 能听到什么'),
              content: const SingleChildScrollView(
                child: Text(
                  '现在能看到歌名、歌手和播放状态。点歌词里的「聊聊这句」，可以把选中的歌词放进输入框。\n\n'
                  '当前没有采集或传送歌曲音频，所以不能分析实际听到的旋律、音色或演唱。'
                  '真正的音频理解需要另接音频采集和支持音频的模型。',
                ),
              ),
              actions: [
                TextButton(
                  onPressed: () => Navigator.pop(context),
                  child: const Text('知道了'),
                ),
              ],
            ),
          ),
          icon: const Icon(Icons.info_outline_rounded, size: 18),
        ),
      ],
    );
  }
}
