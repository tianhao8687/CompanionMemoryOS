import 'dart:async';

import 'package:flutter/material.dart';

import '../state/companion_controller.dart';
import 'connected_app_actions.dart';
import 'connected_netease.dart';
import 'ui_standard.dart';

Future<void> showConnectedApps(
  BuildContext context,
  CompanionController controller,
) => showXinYuPage<void>(
  context,
  (_) => ConnectedAppsSheet(controller: controller),
);

class ConnectedAppsSheet extends StatefulWidget {
  const ConnectedAppsSheet({super.key, required this.controller});
  final CompanionController controller;
  @override
  State<ConnectedAppsSheet> createState() => _ConnectedAppsSheetState();
}

class _ConnectedAppsSheetState extends State<ConnectedAppsSheet> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) unawaited(widget.controller.automation.refresh());
    });
  }

  @override
  Widget build(BuildContext context) => XinYuPage(
    title: '连接的应用',
    actions: [
      IconButton(
        tooltip: '刷新连接与操作',
        onPressed: widget.controller.automation.refresh,
        icon: const Icon(Icons.refresh_rounded),
      ),
    ],
    child: SingleChildScrollView(
      key: const Key('connected-apps-scroll'),
      padding: EdgeInsets.all(XinYuLayout.inset(context)),
      child: ConnectedAppsPanel(controller: widget.controller),
    ),
  );
}

class ConnectedAppsPanel extends StatelessWidget {
  const ConnectedAppsPanel({super.key, required this.controller});
  final CompanionController controller;

  @override
  Widget build(BuildContext context) => ListenableBuilder(
    listenable: controller.automation,
    builder: (context, _) {
      final automation = controller.automation;
      final state = automation.state;
      final disabled = controller.busy || automation.loading || automation.busy;
      return Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          if (automation.loading || automation.busy)
            const LinearProgressIndicator(minHeight: 2),
          if (automation.error != null || automation.notice != null)
            Padding(
              padding: const EdgeInsets.only(bottom: 16),
              child: Semantics(
                liveRegion: true,
                child: Text(
                  automation.error ?? automation.notice!,
                  style: XinYuLayout.note,
                ),
              ),
            ),
          if (controller.isDemo)
            const Padding(
              padding: EdgeInsets.only(bottom: 16),
              child: Text('打开本机数据后，可以连接这台设备上的应用。', style: XinYuLayout.note),
            ),
          if (state?.config['loop'] is Map)
            SwitchListTile.adaptive(
              contentPadding: EdgeInsets.zero,
              title: Text('使用连接的应用', style: XinYuLayout.body(context)),
              subtitle: const Text('每项操作仍遵循应用权限', style: XinYuLayout.note),
              value: state!.config['loop']['enabled'] == true,
              onChanged: disabled || controller.isDemo
                  ? null
                  : automation.setToolsEnabled,
            ),
          NeteaseConnectionCard(
            controller: automation,
            disabled: disabled || controller.isDemo,
          ),
          if (state != null && state.pending.isNotEmpty) ...[
            const SizedBox(height: 24),
            const Text('等待你确认', style: XinYuLayout.section),
            for (final action in state.pending)
              ConnectedAppAction(
                controller: automation,
                action: action,
                disabled: disabled,
              ),
          ],
          if (state != null &&
              state.actions.any((a) => a['status'] != 'pending'))
            Padding(
              padding: const EdgeInsets.only(top: 16),
              child: ExpansionTile(
                tilePadding: EdgeInsets.zero,
                title: Text('最近操作', style: XinYuLayout.body(context)),
                children: [
                  for (final action
                      in state.actions
                          .where((a) => a['status'] != 'pending')
                          .take(20))
                    ConnectedAppAction(
                      controller: automation,
                      action: action,
                      disabled: disabled,
                    ),
                ],
              ),
            ),
        ],
      );
    },
  );
}

class PendingAppActions extends StatelessWidget {
  const PendingAppActions({super.key, required this.controller});
  final CompanionController controller;

  @override
  Widget build(BuildContext context) => ListenableBuilder(
    listenable: controller.automation,
    builder: (context, _) {
      final count = controller.automation.state?.pending.length ?? 0;
      if (count == 0) return const SizedBox.shrink();
      return Semantics(
        liveRegion: true,
        child: Padding(
          padding: const EdgeInsets.only(bottom: 8),
          child: OutlinedButton.icon(
            key: const Key('pending-app-actions'),
            onPressed: () => showConnectedApps(context, controller),
            icon: const Icon(Icons.touch_app_outlined, size: 18),
            label: Text('$count 个应用操作等你确认 · 查看详情'),
          ),
        ),
      );
    },
  );
}
