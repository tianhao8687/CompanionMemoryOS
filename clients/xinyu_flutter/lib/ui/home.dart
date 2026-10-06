import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../state/companion_controller.dart';
import '../state/frame_probe.dart';
import 'chat.dart';
import 'glass.dart';
import 'local_image.dart';
import 'navigation.dart';
import 'settings_sheet.dart';
import 'memory_sheet.dart';
import 'nook_sheet.dart';
import 'chat_search.dart';
import 'character_home.dart';
import 'companion_remark.dart';
import 'problem_dialog.dart';

class XinYuHome extends StatefulWidget {
  const XinYuHome({super.key, required this.controller, required this.probe});
  final CompanionController controller;
  final FrameProbe probe;
  @override
  State<XinYuHome> createState() => _XinYuHomeState();
}

class _XinYuHomeState extends State<XinYuHome> with WidgetsBindingObserver {
  final scaffold = GlobalKey<ScaffoldState>();
  bool _problemVisible = false;
  bool _problemScheduled = false;
  @override
  void initState() {
    super.initState();
    widget.controller.problem.addListener(_problemChanged);
    _problemChanged();
  }

  void _problemChanged() {
    if (!mounted ||
        _problemVisible ||
        _problemScheduled ||
        widget.controller.problem.value == null) {
      return;
    }
    _problemScheduled = true;
    WidgetsBinding.instance.addPostFrameCallback((_) async {
      _problemScheduled = false;
      if (!mounted || widget.controller.problem.value == null) return;
      _problemVisible = true;
      final openSettings = await showProblemDialog(
        context,
        widget.controller.problem,
      );
      if (!mounted) return;
      widget.controller.problem.value = null;
      _problemVisible = false;
      if (openSettings == true) {
        await showCompanionSettings(context, widget.controller, initialTab: 1);
      }
    });
    WidgetsBinding.instance.ensureVisualUpdate();
  }

  @override
  void didUpdateWidget(covariant XinYuHome oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.controller != widget.controller) {
      oldWidget.controller.problem.removeListener(_problemChanged);
      widget.controller.problem.addListener(_problemChanged);
      _problemChanged();
    }
  }

  @override
  void dispose() {
    widget.controller.problem.removeListener(_problemChanged);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) =>
      widget.controller.setForeground(state == AppLifecycleState.resumed);

  void _settings() => showCompanionSettings(context, widget.controller);

  @override
  Widget build(BuildContext context) => ListenableBuilder(
    listenable: widget.controller,
    builder: (context, _) {
      final c = widget.controller;
      final compact = MediaQuery.sizeOf(context).width < 880;
      return AnnotatedRegion<SystemUiOverlayStyle>(
        value: SystemUiOverlayStyle.dark.copyWith(
          statusBarColor: Colors.transparent,
          systemNavigationBarColor: XinYuColors.canvas,
          systemNavigationBarIconBrightness: Brightness.dark,
        ),
        child: Stack(
          children: [
            const Positioned.fill(child: XinYuWallpaper()),
            if (c.settings['background_image'] case final String id) ...[
              Positioned.fill(
                child: LocalImage(
                  controller: c,
                  id: id,
                  fallback: const XinYuWallpaper(),
                ),
              ),
              const Positioned.fill(
                child: ColoredBox(color: Color(0x70f5f4f1)),
              ),
            ],
            Scaffold(
              key: scaffold,
              backgroundColor: Colors.transparent,
              resizeToAvoidBottomInset: true,
              drawerScrimColor: const Color(0x30333c48),
              drawer: compact
                  ? Drawer(
                      backgroundColor: Colors.transparent,
                      elevation: 0,
                      width: 310,
                      child: SafeArea(
                        child: Padding(
                          padding: const EdgeInsets.all(12),
                          child: BackdropGroup(
                            child: CompanionNavigation(
                              controller: c,
                              close: () => Navigator.pop(context),
                              openSettings: () {
                                Navigator.pop(context);
                                _settings();
                              },
                            ),
                          ),
                        ),
                      ),
                    )
                  : null,
              body: SafeArea(
                child: Padding(
                  padding: compact
                      ? const EdgeInsets.all(8)
                      : const EdgeInsets.fromLTRB(24, 20, 24, 20),
                  child: BackdropGroup(
                    child: Row(
                      children: [
                        if (!compact) ...[
                          SizedBox(
                            width: (MediaQuery.sizeOf(context).width * .225)
                                .clamp(252, 356),
                            child: CompanionNavigation(
                              controller: c,
                              openSettings: _settings,
                            ),
                          ),
                          const SizedBox(width: 14),
                        ],
                        Expanded(
                          child: compact
                              ? _chatPane(true)
                              : GlassSurface(
                                  // The container does not sample another blur over its
                                  // non-overlapping header, messages and composer.
                                  blur: 0,
                                  radius: 24,
                                  tint: const Color(0x70ffffff),
                                  child: _chatPane(false),
                                ),
                        ),
                      ],
                    ),
                  ),
                ),
              ),
            ),
            Positioned(
              right: 24,
              top: MediaQuery.paddingOf(context).top + 98,
              child: _FramePanel(probe: widget.probe, controller: c),
            ),
          ],
        ),
      );
    },
  );

  Widget _chatPane(bool compact) => Column(
    children: [
      _header(compact),
      if (widget.controller.error != null) _error(widget.controller),
      Expanded(
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 1040),
            child: ConversationView(controller: widget.controller),
          ),
        ),
      ),
      Padding(
        padding: EdgeInsets.fromLTRB(
          compact ? 0 : 14,
          0,
          compact ? 0 : 14,
          compact ? 0 : 14,
        ),
        child: Center(child: Composer(controller: widget.controller)),
      ),
    ],
  );

  Widget _header(bool compact) => GlassSurface(
    radius: compact ? 0 : 24,
    outlined: !compact,
    elevated: false,
    tint: compact ? Colors.transparent : const Color(0x38ffffff),
    padding: EdgeInsets.fromLTRB(
      compact ? 0 : 28,
      compact ? 8 : 12,
      compact ? 0 : 20,
      compact ? 8 : 12,
    ),
    child: Row(
      children: [
        if (compact)
          IconButton(
            key: const Key('open-conversations'),
            tooltip: '打开对话列表',
            onPressed: () => scaffold.currentState!.openDrawer(),
            icon: const Icon(Icons.menu_rounded),
          ),
        InkWell(
          borderRadius: BorderRadius.circular(12),
          onTap: () => showCharacterHome(context, widget.controller),
          child: ProfileAvatar(
            controller: widget.controller,
            size: compact ? 36 : 56,
          ),
        ),
        SizedBox(width: compact ? 8 : 18),
        Expanded(
          child: Row(
            children: [
              Flexible(
                child: InkWell(
                  key: const Key('open-character-home'),
                  borderRadius: BorderRadius.circular(10),
                  onTap: () => showCharacterHome(context, widget.controller),
                  onLongPress: widget.controller.busy
                      ? null
                      : () => showCompanionRemark(context, widget.controller),
                  child: Padding(
                    padding: const EdgeInsets.symmetric(vertical: 12),
                    child: Text(
                      widget.controller.companionDisplayName,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(
                        fontSize: compact ? 18 : 24,
                        fontWeight: FontWeight.w500,
                      ),
                    ),
                  ),
                ),
              ),
              if (!compact)
                TextButton.icon(
                  key: const Key('edit-companion-remark'),
                  onPressed: widget.controller.busy
                      ? null
                      : () => showCompanionRemark(context, widget.controller),
                  icon: const Icon(Icons.edit_outlined, size: 17),
                  label: const Text('备注', style: TextStyle(fontSize: 13)),
                ),
            ],
          ),
        ),
        if (widget.controller.hasChatFeatures || !compact)
          IconButton(
            key: const Key('open-search'),
            tooltip: '搜索聊天',
            onPressed: widget.controller.hasChatFeatures
                ? () => showChatSearch(context, widget.controller)
                : null,
            icon: const Icon(Icons.search_rounded),
          ),
        if (widget.controller.capabilities['nook_features'] == true)
          IconButton(
            key: const Key('open-nook'),
            tooltip: '回忆小窝',
            onPressed: () => showMemoryNook(context, widget.controller),
            icon: const Icon(Icons.cottage_outlined),
          ),
        IconButton(
          key: const Key('open-memories'),
          tooltip: '记忆手账',
          onPressed: widget.controller.busy || !widget.controller.connected
              ? null
              : () => showMemories(context, widget.controller),
          icon: const Icon(Icons.assignment_outlined),
        ),
        if (const bool.fromEnvironment('XINYU_DEVELOPMENT'))
          IconButton(
            tooltip: '显示性能面板',
            onPressed: widget.probe.toggle,
            icon: const Icon(Icons.speed_rounded),
          ),
        IconButton(
          key: const Key('open-settings'),
          tooltip: '陪伴设置',
          onPressed: _settings,
          icon: const Icon(Icons.more_vert_rounded),
        ),
      ],
    ),
  );

  Widget _error(CompanionController controller) => Padding(
    padding: const EdgeInsets.symmetric(vertical: 4),
    child: Semantics(
      liveRegion: true,
      child: Container(
        padding: const EdgeInsets.fromLTRB(14, 9, 8, 9),
        decoration: BoxDecoration(
          color: const Color(0xd0fff5e8),
          borderRadius: XinYuShapes.fieldCorners,
        ),
        child: Row(
          children: [
            const Icon(
              Icons.info_outline_rounded,
              size: 17,
              color: Color(0xff865c43),
            ),
            const SizedBox(width: 9),
            Expanded(
              child: Text(
                controller.error!,
                style: const TextStyle(
                  fontSize: 12,
                  height: 1.5,
                  color: Color(0xff865c43),
                ),
              ),
            ),
            if (controller.canRetry)
              TextButton(onPressed: controller.retry, child: const Text('重试')),
            if (!controller.connected && !controller.busy)
              TextButton(
                onPressed: () async {
                  try {
                    await controller.useLocal();
                  } catch (_) {
                    /* Error is shown above. */
                  }
                },
                child: const Text('重新连接'),
              ),
          ],
        ),
      ),
    ),
  );
}

class _FramePanel extends StatelessWidget {
  const _FramePanel({required this.probe, required this.controller});
  final FrameProbe probe;
  final CompanionController controller;
  @override
  Widget build(BuildContext context) => ListenableBuilder(
    listenable: probe,
    builder: (context, _) {
      if (!probe.visible) return const SizedBox.shrink();
      final summary = probe.summary();
      // The optional measurement panel uses a solid surface so it does not add a
      // new animated backdrop to the scene being measured.
      return Material(
        color: const Color(0xf5f7f7f0),
        elevation: 3,
        borderRadius: XinYuShapes.fieldCorners,
        child: SizedBox(
          width: 266,
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    const Expanded(
                      child: Text(
                        '渲染记录',
                        style: TextStyle(fontWeight: FontWeight.w500),
                      ),
                    ),
                    IconButton(
                      tooltip: '关闭性能面板',
                      onPressed: probe.toggle,
                      icon: const Icon(Icons.close_rounded, size: 18),
                    ),
                  ],
                ),
                Text(
                  '${summary['mode']} · 最近 ${summary['frames']} 帧',
                  style: const TextStyle(
                    fontSize: 11,
                    color: XinYuColors.muted,
                  ),
                ),
                const SizedBox(height: 12),
                Text(
                  '构建 P95    ${(summary['build_p95_ms'] as double).toStringAsFixed(2)} ms\n光栅 P95    ${(summary['raster_p95_ms'] as double).toStringAsFixed(2)} ms\n超过 16.67 ms    ${summary['over_16_67_ms']} 帧',
                  style: const TextStyle(fontSize: 12, height: 1.9),
                ),
                const SizedBox(height: 10),
                const Text(
                  '统计构建与光栅耗时，并非屏幕实际 FPS。开启面板会带来少量额外开销。',
                  style: TextStyle(
                    fontSize: 10,
                    height: 1.6,
                    color: XinYuColors.muted,
                  ),
                ),
                Wrap(
                  spacing: 4,
                  children: [
                    TextButton(
                      onPressed: probe.reset,
                      child: const Text('清空记录'),
                    ),
                    if (controller.isDemo)
                      TextButton(
                        key: const Key('load-benchmark'),
                        onPressed: controller.busy
                            ? null
                            : controller.benchmark,
                        child: const Text('载入 200 条示例'),
                      ),
                  ],
                ),
              ],
            ),
          ),
        ),
      );
    },
  );
}
