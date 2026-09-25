import 'package:flutter/material.dart';

import '../state/companion_controller.dart';
import '../state/frame_probe.dart';
import 'chat.dart';
import 'glass.dart';
import 'navigation.dart';
import 'settings_sheet.dart';
import 'memory_sheet.dart';

class XinYuHome extends StatefulWidget {
  const XinYuHome({super.key, required this.controller, required this.probe});
  final CompanionController controller;
  final FrameProbe probe;
  @override
  State<XinYuHome> createState() => _XinYuHomeState();
}

class _XinYuHomeState extends State<XinYuHome> {
  final scaffold = GlobalKey<ScaffoldState>();
  void _settings() => showCompanionSettings(context, widget.controller);
  @override
  Widget build(BuildContext context) => ListenableBuilder(
    listenable: widget.controller,
    builder: (context, _) {
      final controller = widget.controller;
      final compact = MediaQuery.sizeOf(context).width < 880;
      return Stack(
        children: [
          const Positioned.fill(child: XinYuWallpaper()),
          Scaffold(
            key: scaffold,
            backgroundColor: Colors.transparent,
            resizeToAvoidBottomInset: true,
            drawerScrimColor: const Color(0x303e4842),
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
                            controller: controller,
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
                padding: EdgeInsets.all(compact ? 12 : 22),
                child: BackdropGroup(
                  child: Row(
                    children: [
                      if (!compact) ...[
                        SizedBox(
                          width: 246,
                          child: CompanionNavigation(
                            controller: controller,
                            openSettings: _settings,
                          ),
                        ),
                        const SizedBox(width: 22),
                      ],
                      Expanded(
                        child: Column(
                          children: [
                            _header(compact),
                            const SizedBox(height: 10),
                            if (controller.error != null) _error(controller),
                            Expanded(
                              child: Center(
                                child: ConstrainedBox(
                                  constraints: const BoxConstraints(
                                    maxWidth: 1040,
                                  ),
                                  child: ConversationView(
                                    controller: controller,
                                  ),
                                ),
                              ),
                            ),
                            Center(
                              child: ConstrainedBox(
                                constraints: const BoxConstraints(
                                  maxWidth: 1040,
                                ),
                                child: Composer(
                                  controller: controller,
                                  openSettings: _settings,
                                ),
                              ),
                            ),
                            if (MediaQuery.viewInsetsOf(context).bottom == 0)
                              Padding(
                                padding: const EdgeInsets.only(top: 9),
                                child: Text(
                                  controller.isDemo
                                      ? '界面原型 · 示例对话不会写入记忆'
                                      : '${controller.companionName}是 AI 伙伴 · 重要的事，也和身边的人聊聊',
                                  textAlign: TextAlign.center,
                                  style: const TextStyle(
                                    fontSize: 10,
                                    color: XinYuColors.muted,
                                  ),
                                ),
                              ),
                          ],
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
            child: _FramePanel(probe: widget.probe, controller: controller),
          ),
        ],
      );
    },
  );

  Widget _header(bool compact) => GlassSurface(
    radius: 25,
    padding: EdgeInsets.symmetric(horizontal: compact ? 9 : 20, vertical: 10),
    child: Row(
      children: [
        if (compact)
          IconButton(
            tooltip: '打开对话列表',
            onPressed: () => scaffold.currentState!.openDrawer(),
            icon: const Icon(Icons.menu_rounded, size: 22),
          ),
        if (!compact) ...[
          CompanionAvatar(
            size: 43,
            label: widget.controller.companionName.characters.last,
          ),
          const SizedBox(width: 13),
        ],
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                widget.controller.companionName,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(
                  fontSize: 17,
                  fontWeight: FontWeight.w600,
                ),
              ),
              const SizedBox(height: 5),
              Row(
                children: [
                  Container(
                    width: 5,
                    height: 5,
                    decoration: const BoxDecoration(
                      shape: BoxShape.circle,
                      color: Color(0xff689277),
                    ),
                  ),
                  const SizedBox(width: 6),
                  Flexible(
                    child: Text(
                      widget.controller.isDemo
                          ? '演示空间'
                          : widget.controller.loading
                          ? '正在连接'
                          : widget.controller.connected
                          ? '记忆保存在本机'
                          : '本机引擎未连接',
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                        fontSize: 10,
                        color: XinYuColors.muted,
                      ),
                    ),
                  ),
                ],
              ),
            ],
          ),
        ),
        IconButton(
          key: const Key('open-memories'),
          tooltip: '查看记忆',
          onPressed: widget.controller.busy || !widget.controller.connected
              ? null
              : () => showMemories(context, widget.controller),
          icon: const Icon(Icons.auto_awesome_outlined, size: 21),
        ),
        if (widget.controller.isDemo ||
            const bool.fromEnvironment('XINYU_DEVELOPMENT'))
          IconButton(
            tooltip: '显示性能面板',
            onPressed: widget.probe.toggle,
            icon: const Icon(Icons.speed_rounded, size: 21),
          ),
        IconButton(
          key: const Key('open-settings'),
          tooltip: '陪伴设置',
          onPressed: _settings,
          icon: const Icon(Icons.tune_rounded, size: 21),
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
          borderRadius: BorderRadius.circular(15),
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
        borderRadius: BorderRadius.circular(18),
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
                        style: TextStyle(fontWeight: FontWeight.w600),
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
