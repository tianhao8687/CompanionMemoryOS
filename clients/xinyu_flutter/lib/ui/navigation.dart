import 'package:flutter/material.dart';

import '../state/companion_controller.dart';
import 'glass.dart';

class CompanionNavigation extends StatelessWidget {
  const CompanionNavigation({
    super.key,
    required this.controller,
    required this.openSettings,
    this.close,
  });
  final CompanionController controller;
  final VoidCallback openSettings;
  final VoidCallback? close;
  @override
  Widget build(BuildContext context) => GlassSurface(
    padding: const EdgeInsets.fromLTRB(20, 26, 20, 18),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Container(
              width: 44,
              height: 44,
              decoration: BoxDecoration(
                color: const Color(0x60fff6e9),
                borderRadius: BorderRadius.circular(15),
                border: Border.all(color: const Color(0xbfffffff)),
              ),
              child: const Icon(
                Icons.favorite_border_rounded,
                color: Color(0xffae7762),
                size: 25,
              ),
            ),
            const SizedBox(width: 12),
            const Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    '心隅',
                    style: TextStyle(
                      fontSize: 24,
                      fontWeight: FontWeight.w600,
                      letterSpacing: 4,
                    ),
                  ),
                  Text(
                    'A LITTLE CLOSER',
                    style: TextStyle(
                      fontSize: 9,
                      letterSpacing: 1.4,
                      color: XinYuColors.muted,
                    ),
                  ),
                ],
              ),
            ),
            if (close != null)
              IconButton(
                tooltip: '收起对话列表',
                onPressed: close,
                icon: const Icon(Icons.close_rounded),
              ),
          ],
        ),
        const SizedBox(height: 24),
        const Text(
          '给日常，留一个温柔的角落。',
          style: TextStyle(fontSize: 12, color: XinYuColors.muted),
        ),
        const SizedBox(height: 24),
        SizedBox(
          width: double.infinity,
          child: FilledButton.tonalIcon(
            key: const Key('new-conversation'),
            onPressed: controller.busy
                ? null
                : () {
                    controller.newConversation();
                    close?.call();
                  },
            style: FilledButton.styleFrom(
              backgroundColor: const Color(0x80ffffff),
            ),
            icon: const Icon(Icons.add_rounded, size: 20),
            label: const Text('开始一段新对话', style: TextStyle(fontSize: 13)),
          ),
        ),
        const SizedBox(height: 30),
        Row(
          children: [
            const Expanded(
              child: Text(
                '最近的对话',
                style: TextStyle(
                  fontSize: 11,
                  letterSpacing: 1,
                  color: XinYuColors.muted,
                ),
              ),
            ),
            Text(
              '${controller.conversations.length}',
              style: const TextStyle(color: XinYuColors.muted, fontSize: 11),
            ),
          ],
        ),
        const SizedBox(height: 12),
        Expanded(
          child: ListView.separated(
            padding: EdgeInsets.zero,
            itemCount: controller.conversations.length,
            separatorBuilder: (_, _) => const SizedBox(height: 5),
            itemBuilder: (_, i) {
              final item = controller.conversations[i];
              final selected = item.id == controller.active;
              return Material(
                color: selected ? const Color(0x80ffffff) : Colors.transparent,
                borderRadius: BorderRadius.circular(16),
                child: InkWell(
                  borderRadius: BorderRadius.circular(16),
                  onTap: controller.busy
                      ? null
                      : () {
                          controller.select(item.id);
                          close?.call();
                        },
                  child: Padding(
                    padding: const EdgeInsets.symmetric(
                      horizontal: 13,
                      vertical: 16,
                    ),
                    child: Row(
                      children: [
                        Icon(
                          selected
                              ? Icons.chat_bubble_outline_rounded
                              : Icons.chat_outlined,
                          size: 17,
                          color: XinYuColors.muted,
                        ),
                        const SizedBox(width: 10),
                        Expanded(
                          child: Text(
                            item.title,
                            maxLines: 2,
                            overflow: TextOverflow.ellipsis,
                            style: TextStyle(
                              fontSize: 12,
                              height: 1.5,
                              fontWeight: selected
                                  ? FontWeight.w600
                                  : FontWeight.normal,
                            ),
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
              );
            },
          ),
        ),
        const SizedBox(height: 18),
        const Padding(
          padding: EdgeInsets.symmetric(horizontal: 7),
          child: Row(
            children: [
              Icon(Icons.spa_outlined, size: 19, color: XinYuColors.muted),
              SizedBox(width: 10),
              Expanded(
                child: Text(
                  '慢慢来，就很好。\n每个平常的日子，都值得被听见。',
                  style: TextStyle(
                    fontSize: 11,
                    height: 1.8,
                    color: XinYuColors.muted,
                  ),
                ),
              ),
            ],
          ),
        ),
        const SizedBox(height: 20),
        SizedBox(
          width: double.infinity,
          child: TextButton.icon(
            onPressed: openSettings,
            style: TextButton.styleFrom(
              backgroundColor: const Color(0x60ffffff),
              padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 16),
              alignment: Alignment.centerLeft,
            ),
            icon: const Icon(Icons.tune_rounded, size: 19),
            label: Text(
              controller.userName.isEmpty
                  ? '我的陪伴设置'
                  : '${controller.userName}的陪伴设置',
              style: const TextStyle(fontSize: 13),
            ),
          ),
        ),
      ],
    ),
  );
}
