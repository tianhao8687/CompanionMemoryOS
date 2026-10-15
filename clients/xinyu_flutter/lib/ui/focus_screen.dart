import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../data/focus.dart';
import '../data/focus_interaction.dart';
import '../state/companion_controller.dart';
import 'focus_break.dart';
import 'focus_chat.dart';
import 'focus_header.dart';
import 'focus_panel.dart';
import 'focus_presence.dart';
import 'focus_records.dart';
import 'focus_reply.dart';
import 'focus_setup.dart';
import 'focus_style.dart';

Future<void> showFocusScreen(
  BuildContext context,
  CompanionController controller,
) {
  FocusManager.instance.primaryFocus?.unfocus();
  return Navigator.of(context).push<void>(
    MaterialPageRoute(
      settings: const RouteSettings(name: '/focus'),
      builder: (_) => FocusScreen(controller: controller),
    ),
  );
}

/// A full-window companion surface; the controller owns the clock beyond this route.
class FocusScreen extends StatefulWidget {
  const FocusScreen({super.key, required this.controller});
  final CompanionController controller;
  @override
  State<FocusScreen> createState() => _FocusScreenState();
}

class _FocusScreenState extends State<FocusScreen> {
  bool preparing = false;
  bool interacting = false;

  Future<void> _company(BuildContext context, {required bool chat}) async {
    if (interacting) return;
    setState(() => interacting = true);
    try {
      if (!await widget.controller.focus.pauseForCompany() ||
          !context.mounted) {
        return;
      }
      if (chat) {
        await showFocusChat(context, widget.controller);
      } else {
        unawaited(
          widget.controller.interactWithFocus(FocusInteraction.breathe),
        );
        await Navigator.of(context).push<void>(
          MaterialPageRoute(
            settings: const RouteSettings(name: '/focus/break'),
            builder: (_) => FocusBreak(controller: widget.controller),
          ),
        );
      }
    } finally {
      if (mounted) setState(() => interacting = false);
    }
  }

  String _message(FocusSession? session) {
    if (session == null || (preparing && session.settled)) return '留一段专注的时间';
    if (session.paused) return '计时已暂停';
    return switch (session.phase) {
      'focus_done' => '这一段时间到了',
      'rest' => '休息时间',
      'done' || 'ended' => '这一段已结束',
      _ => '专注于眼前这一小步',
    };
  }

  Widget _header(BuildContext context) {
    final compact = MediaQuery.sizeOf(context).width < 600;
    final menuWidth = (MediaQuery.textScalerOf(context).scale(96) + 80)
        .clamp(224.0, MediaQuery.sizeOf(context).width - 32)
        .toDouble();
    return FocusPageHeader(
      title: '陪伴专注',
      backLabel: '返回聊天',
      backKey: const Key('focus-back'),
      actions: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          if (!compact)
            IconButton(
              tooltip: '活动记录',
              onPressed: () => showFocusRecords(context, widget.controller),
              icon: const Icon(Icons.history_rounded),
            ),
          MenuAnchor(
            crossAxisUnconstrained: false,
            alignmentOffset: Offset(48 - menuWidth, 8),
            reservedPadding: const EdgeInsets.all(16),
            style: Theme.of(context).menuTheme.style?.copyWith(
              alignment: Alignment.bottomLeft,
              fixedSize: WidgetStatePropertyAll(Size.fromWidth(menuWidth)),
            ),
            menuChildren: [
              if (widget.controller.focus.session?.closed == true)
                MenuItemButton(
                  onPressed: () =>
                      showFocusProgress(context, widget.controller),
                  leadingIcon: const Icon(Icons.edit_note_rounded),
                  child: Text('留下一点进展'),
                ),
              MenuItemButton(
                onPressed: () => showFocusRecords(context, widget.controller),
                leadingIcon: const Icon(Icons.history_rounded),
                child: const Text('活动记录'),
              ),
              MenuItemButton(
                onPressed: () =>
                    showFocusNoticeSettings(context, widget.controller),
                leadingIcon: const Icon(Icons.notifications_none_rounded),
                child: const Text('提醒设置'),
              ),
            ],
            builder: (_, menu, _) => SizedBox(
              width: 48,
              child: IconButton(
                tooltip: '更多专注操作',
                onPressed: () => menu.isOpen ? menu.close() : menu.open(),
                icon: const Icon(Icons.more_horiz_rounded),
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _actions(BuildContext context, FocusSession session) {
    final focus = widget.controller.focus;
    if (session.settled) {
      return Wrap(
        alignment: WrapAlignment.center,
        spacing: 16,
        runSpacing: 12,
        children: [
          FilledButton(
            key: const Key('focus-primary'),
            onPressed: focus.busy
                ? null
                : () => setState(() => preparing = true),
            child: const Text('再来一段'),
          ),
          OutlinedButton(
            onPressed: () => showFocusProgress(context, widget.controller),
            child: const Text('留下一点进展'),
          ),
        ],
      );
    }
    final arrived = session.phase == 'focus_done';
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        Wrap(
          alignment: WrapAlignment.center,
          spacing: 16,
          runSpacing: 12,
          children: [
            FilledButton.icon(
              key: const Key('focus-primary'),
              onPressed: focus.busy ? null : () => focus.act(session.action),
              icon: Icon(
                arrived
                    ? Icons.coffee_outlined
                    : session.paused
                    ? Icons.play_arrow_rounded
                    : Icons.pause_rounded,
                size: 20,
              ),
              label: Text(session.actionLabel),
            ),
            OutlinedButton(
              key: Key(arrived ? 'focus-extend' : 'focus-finish'),
              onPressed: focus.busy
                  ? null
                  : () => focus.act(arrived ? 'extend' : 'finish'),
              child: Text(arrived ? '再加五分钟' : '结束'),
            ),
          ],
        ),
        if (arrived)
          TextButton(
            key: const Key('focus-finish'),
            onPressed: focus.busy ? null : () => focus.act('finish'),
            child: const Text('先到这里'),
          ),
      ],
    );
  }

  Widget _content(BuildContext context) {
    final focus = widget.controller.focus, session = focus.session;
    final setup = session == null || (preparing && session.settled);
    final compact = MediaQuery.sizeOf(context).width < 600;
    return LayoutBuilder(
      builder: (context, constraints) => SingleChildScrollView(
        key: const Key('focus-content'),
        padding: EdgeInsets.fromLTRB(
          compact ? 24 : 40,
          24,
          compact ? 24 : 40,
          40,
        ),
        child: ConstrainedBox(
          constraints: BoxConstraints(
            minHeight: (constraints.maxHeight - 64).clamp(0, double.infinity),
          ),
          child: Align(
            alignment: const Alignment(0, -.15),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 520),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  FocusCompanionAvatar(
                    controller: widget.controller,
                    size: setup
                        ? 72
                        : compact
                        ? 80
                        : 92,
                  ),
                  const SizedBox(height: 12),
                  Text(
                    '${widget.controller.companionDisplayName}陪着你',
                    textAlign: TextAlign.center,
                    style: FocusStyle.caption,
                  ),
                  SizedBox(
                    height: setup
                        ? 20
                        : compact
                        ? 24
                        : 32,
                  ),
                  FocusReply(
                    controller: widget.controller,
                    placeholder: _message(session),
                  ),
                  if (setup) ...[
                    const SizedBox(height: 28),
                    ConstrainedBox(
                      constraints: const BoxConstraints(maxWidth: 400),
                      child: FocusSetup(
                        key: const ValueKey('fullscreen-focus-setup'),
                        controller: widget.controller,
                        onStarted: () => setState(() => preparing = false),
                      ),
                    ),
                  ] else ...[
                    if (const {
                      'focus',
                      'focus_paused',
                    }.contains(session.phase)) ...[
                      const SizedBox(height: 24),
                      FocusStepCard(controller: widget.controller),
                    ],
                    if (session.intention.isNotEmpty) ...[
                      const SizedBox(height: 24),
                      Text(
                        session.intention,
                        textAlign: TextAlign.center,
                        style: FocusStyle.body.copyWith(
                          color: FocusStyle.muted,
                        ),
                      ),
                    ],
                    const SizedBox(height: 20),
                    if (!session.settled)
                      Semantics(
                        label:
                            '${session.label}，剩余 ${focusTime(focus.seconds)}',
                        child: ExcludeSemantics(
                          child: FittedBox(
                            fit: BoxFit.scaleDown,
                            child: Text(
                              focusTime(focus.seconds),
                              key: const Key('focus-clock'),
                              style: FocusStyle.timer.copyWith(
                                fontSize: compact ? 56 : 64,
                              ),
                            ),
                          ),
                        ),
                      ),
                    const SizedBox(height: 8),
                    Text(
                      session.phase == 'focus'
                          ? '这一段 · ${session.minutes} 分钟'
                          : session.label,
                      textAlign: TextAlign.center,
                      style: FocusStyle.caption,
                    ),
                    const SizedBox(height: 24),
                    _actions(context, session),
                    if (!session.settled) ...[
                      const SizedBox(height: 24),
                      Wrap(
                        alignment: WrapAlignment.center,
                        spacing: 16,
                        runSpacing: 8,
                        children: [
                          TextButton.icon(
                            key: const Key('focus-breathe'),
                            onPressed:
                                focus.busy ||
                                    interacting ||
                                    widget.controller.busy
                                ? null
                                : () => _company(context, chat: false),
                            icon: const Icon(Icons.air_rounded, size: 20),
                            label: const Text('一起缓缓'),
                          ),
                          TextButton.icon(
                            key: const Key('focus-stuck'),
                            onPressed:
                                focus.busy ||
                                    interacting ||
                                    widget.controller.busy
                                ? null
                                : () => _company(context, chat: true),
                            icon: const Icon(
                              Icons.chat_bubble_outline_rounded,
                              size: 20,
                            ),
                            label: const Text('我卡住了'),
                          ),
                        ],
                      ),
                    ],
                    if (focus.error case final String error)
                      Padding(
                        padding: const EdgeInsets.only(top: 16),
                        child: Semantics(
                          liveRegion: true,
                          child: Text(
                            error,
                            textAlign: TextAlign.center,
                            style: FocusStyle.body.copyWith(
                              color: Theme.of(context).colorScheme.error,
                            ),
                          ),
                        ),
                      ),
                  ],
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) => Theme(
    data: FocusStyle.theme(context),
    child: Builder(
      builder: (context) => Shortcuts(
        shortcuts: const {
          SingleActivator(LogicalKeyboardKey.escape): DismissIntent(),
        },
        child: Actions(
          actions: {
            DismissIntent: CallbackAction<DismissIntent>(
              onInvoke: (_) {
                Navigator.maybePop(context);
                return null;
              },
            ),
          },
          child: Focus(
            autofocus: true,
            child: Scaffold(
              key: const Key('focus-screen'),
              backgroundColor: const Color(0xffc2d0e6),
              body: Stack(
                fit: StackFit.expand,
                children: [
                  ExcludeSemantics(
                    child: Image.asset(
                      FocusStyle.background,
                      fit: BoxFit.cover,
                      alignment: const Alignment(.1, 0),
                      filterQuality: FilterQuality.medium,
                    ),
                  ),
                  SafeArea(
                    child: ListenableBuilder(
                      listenable: Listenable.merge([
                        widget.controller,
                        widget.controller.focus,
                        widget.controller.focus.presence,
                      ]),
                      builder: (context, _) => Column(
                        children: [
                          _header(context),
                          Expanded(child: _content(context)),
                        ],
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    ),
  );
}
