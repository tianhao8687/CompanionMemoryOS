import 'package:flutter/material.dart';

import '../state/floating_chat.dart';
import 'glass.dart';

Future<void> showFloatingChat(BuildContext context, FloatingChat chat) async {
  await chat.refresh();
  if (!context.mounted) return;
  await showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    useSafeArea: true,
    builder: (_) => FloatingChatSheet(chat: chat),
  );
}

class FloatingChatSheet extends StatefulWidget {
  const FloatingChatSheet({super.key, required this.chat});
  final FloatingChat chat;
  @override
  State<FloatingChatSheet> createState() => _FloatingChatSheetState();
}

class _FloatingChatSheetState extends State<FloatingChatSheet>
    with WidgetsBindingObserver {
  bool working = false;
  String? error;
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) widget.chat.refresh();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  Future<void> act() async {
    setState(() {
      working = true;
      error = null;
    });
    try {
      final chat = widget.chat;
      if (chat.running) {
        await chat.stop();
      } else if (!chat.permitted) {
        await chat.permission();
      } else {
        await chat.start();
        if (mounted && chat.running) Navigator.pop(context);
      }
    } catch (_) {
      if (mounted) error = '小窗未能开启，请检查悬浮窗权限后重试。';
    } finally {
      if (mounted) setState(() => working = false);
    }
  }

  @override
  Widget build(BuildContext context) => ListenableBuilder(
    listenable: widget.chat,
    builder: (context, _) {
      final chat = widget.chat;
      return SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  const Expanded(
                    child: Text('悬浮陪聊', style: TextStyle(fontSize: 20)),
                  ),
                  IconButton(
                    tooltip: '关闭',
                    onPressed: () => Navigator.pop(context),
                    icon: const Icon(Icons.close_rounded),
                  ),
                ],
              ),
              const SizedBox(height: 12),
              const Text('把心隅留在旁边，接着这段对话聊。'),
              const SizedBox(height: 8),
              const Text(
                '屏幕边上留一个小点，点开就能看回复、接着聊。再点小点或窗口外收起；拖动小点可以换边、换位置。只有点输入框时才使用键盘。',
                style: TextStyle(color: XinYuColors.muted, height: 1.6),
              ),
              const SizedBox(height: 12),
              SwitchListTile.adaptive(
                contentPadding: EdgeInsets.zero,
                title: const Text('点开时看当前屏幕'),
                subtitle: const Text(
                  '读取当前页面文字，交给当前对话模型理解；支持识图时也会带上画面。只在点开时读取。',
                ),
                value: chat.readScreen,
                onChanged: working || !chat.supported
                    ? null
                    : (value) async {
                        try {
                          await chat.setReadScreen(value);
                        } catch (_) {
                          if (mounted) setState(() => error = '读屏设置未保存，请重试。');
                        }
                      },
              ),
              if (chat.readScreen && !chat.screenPermitted)
                TextButton(
                  onPressed: working || !chat.supported
                      ? null
                      : () async {
                          try {
                            await chat.screenPermission();
                          } catch (_) {
                            if (mounted) {
                              setState(() => error = '请在系统设置中开启心隅的无障碍服务。');
                            }
                          }
                        },
                  child: const Text('开启读屏权限'),
                ),
              if (error != null)
                Padding(
                  padding: const EdgeInsets.only(top: 12),
                  child: Semantics(liveRegion: true, child: Text(error!)),
                ),
              const SizedBox(height: 20),
              SizedBox(
                width: double.infinity,
                child: FilledButton(
                  onPressed: working || !chat.supported ? null : act,
                  child: Text(
                    !chat.supported
                        ? '当前设备暂不支持'
                        : working
                        ? '正在处理…'
                        : chat.running
                        ? '关闭悬浮陪聊'
                        : chat.permitted
                        ? '开启小窗'
                        : '授予悬浮窗权限',
                  ),
                ),
              ),
            ],
          ),
        ),
      );
    },
  );
}
