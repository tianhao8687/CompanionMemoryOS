import 'package:flutter/material.dart';

import '../state/companion_controller.dart';
import 'connected_apps.dart';
import 'focus_screen.dart';
import 'glass.dart';
import 'music_screen.dart';
import 'persona_import_sheet.dart';
import 'settings_sheet.dart';
import 'ui_standard.dart';

Future<void> showAppExperience(
  BuildContext context,
  CompanionController controller,
) => showXinYuPage<void>(
  context,
  (_) => XinYuPage(
    title: '在心隅，慢慢体验',
    child: ListenableBuilder(
      listenable: controller,
      builder: (context, _) => ListView(
        padding: const EdgeInsets.all(20),
        children: [
          GlassSurface(
            blur: 0,
            tint: const Color(0x75e0ebf6),
            padding: const EdgeInsets.all(20),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text('已经帮你准备好', style: XinYuLayout.section),
                const SizedBox(height: 12),
                for (final entry in const {
                  'natural_chat': '自然聊天',
                  'stickers_enabled': '表情互动',
                  'nook_enabled': '记忆小屋',
                  'proactive_enabled': '主动陪伴',
                }.entries)
                  Padding(
                    padding: const EdgeInsets.symmetric(vertical: 5),
                    child: Row(
                      children: [
                        Icon(
                          controller.settings[entry.key] == true
                              ? Icons.check_circle_outline
                              : Icons.circle_outlined,
                          size: 18,
                          color: XinYuColors.accent,
                        ),
                        const SizedBox(width: 10),
                        Expanded(
                          child: Text(
                            '${entry.value} · ${controller.settings[entry.key] == true ? "已开启" : "未开启"}',
                            style: XinYuLayout.body(context),
                          ),
                        ),
                      ],
                    ),
                  ),
              ],
            ),
          ),
          const SizedBox(height: 24),
          const Text('从你感兴趣的开始', style: XinYuLayout.section),
          const SizedBox(height: 12),
          SettingsRow(
            title: '导入人设',
            subtitle: '选卡片或粘贴文字，就能开始',
            icon: Icons.badge_outlined,
            onTap: () => showPersonaImport(context, controller),
          ),
          SettingsRow(
            title: '一起听',
            subtitle: '打开音乐陪伴，核对网易云连接',
            icon: Icons.headphones_rounded,
            onTap: () => showMusicScreen(context, controller),
          ),
          SettingsRow(
            title: '陪我专注',
            subtitle: '选好时长后，再开始计时',
            icon: Icons.timelapse_rounded,
            onTap: () => showFocusScreen(context, controller),
          ),
          const SizedBox(height: 24),
          const Text('还需要系统帮忙的部分', style: XinYuLayout.section),
          const SizedBox(height: 12),
          SettingsRow(
            title: '音乐连接与权限',
            subtitle: '系统媒体权限需要你亲自允许',
            icon: Icons.link_rounded,
            onTap: () => showConnectedApps(context, controller),
          ),
          SettingsRow(
            title: '通知与免打扰',
            subtitle: '保留你的免打扰时间；后台送达取决于系统权限',
            icon: Icons.notifications_none_rounded,
            onTap: () =>
                showCompanionSettings(context, controller, initialTab: 0),
          ),
          const SizedBox(height: 20),
          const Text(
            '随时可以说“关闭主动陪伴”“字体大一点”或“撤销刚才的设置”。',
            style: XinYuLayout.note,
          ),
        ],
      ),
    ),
  ),
);
