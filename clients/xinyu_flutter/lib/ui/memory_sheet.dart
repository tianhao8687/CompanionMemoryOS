import 'package:flutter/material.dart';

import '../state/companion_controller.dart';
import 'glass.dart';
import 'journal_sheet.dart';

Future<void> showMemories(
  BuildContext context,
  CompanionController controller,
) => controller.hasJournal
    ? showJournal(context, controller)
    : showDialog<void>(
        context: context,
        builder: (_) => MemorySheet(controller: controller),
      );

class MemorySheet extends StatefulWidget {
  const MemorySheet({super.key, required this.controller});
  final CompanionController controller;
  @override
  State<MemorySheet> createState() => _MemorySheetState();
}

class _MemorySheetState extends State<MemorySheet> {
  List<Map<String, dynamic>> records = [];
  bool busy = false;
  String? error;
  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    if (widget.controller.isDemo || widget.controller.active == null) return;
    setState(() {
      busy = true;
      error = null;
    });
    try {
      final data = await widget.controller.localConnection!.memories(
        widget.controller.active!,
      );
      if (mounted) {
        setState(() {
          records = (data['memories'] as List)
              .map((row) => Map<String, dynamic>.from(row as Map))
              .toList();
        });
      }
    } catch (e) {
      if (mounted) {
        setState(
          () => error = widget.controller.reportFailure(e, title: '记忆暂时无法读取'),
        );
      }
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> _change(
    Map<String, dynamic> record, {
    required bool forget,
  }) async {
    var content = record['content'] as String? ?? '';
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(forget ? '忘记这件事' : '更正记忆'),
        content: forget
            ? const Text('这条记忆和关联来源会按遗忘规则清理。你之前导出的备份不会一起删除。')
            : TextFormField(
                initialValue: content,
                onChanged: (value) => content = value,
                autofocus: true,
                maxLines: 5,
                maxLength: 2000,
                decoration: const InputDecoration(labelText: '现在应该记住的内容'),
              ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('取消'),
          ),
          FilledButton(
            onPressed: () {
              if (forget || content.trim().isNotEmpty) {
                Navigator.pop(context, true);
              }
            },
            child: Text(forget ? '确认遗忘' : '保存更正'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    setState(() {
      busy = true;
      error = null;
    });
    try {
      final repository = widget.controller.localConnection!;
      if (forget) {
        await repository.forgetMemory(record['id'] as String);
      } else {
        await repository.editMemory(
          record['id'] as String,
          content.trim(),
          widget.controller.active!,
        );
      }
      // Reload history too: forgetting can redact source turns visible behind this sheet.
      await widget.controller.initialize();
      if (mounted) await _load();
    } catch (e) {
      if (mounted) {
        setState(
          () => error = widget.controller.reportFailure(e, title: '记忆修改未完成'),
        );
      }
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => PopScope(
    canPop: !busy,
    child: Dialog(
      backgroundColor: Colors.transparent,
      elevation: 0,
      insetPadding: const EdgeInsets.all(16),
      child: ConstrainedBox(
        constraints: BoxConstraints(
          maxWidth: 650,
          maxHeight: MediaQuery.sizeOf(context).height * .85,
        ),
        child: BackdropGroup(
          child: GlassSurface(
            radius: XinYuShapes.panelRadius,
            blur: 28,
            tint: const Color(0xd4faf9f5),
            padding: const EdgeInsets.all(22),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    const Expanded(
                      child: Text(
                        '记住的小事',
                        style: TextStyle(
                          fontSize: 22,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                    ),
                    IconButton(
                      tooltip: '刷新记忆',
                      onPressed: busy ? null : _load,
                      icon: const Icon(Icons.refresh_rounded),
                    ),
                    IconButton(
                      tooltip: '关闭记忆',
                      onPressed: busy ? null : () => Navigator.pop(context),
                      icon: const Icon(Icons.close_rounded),
                    ),
                  ],
                ),
                const SizedBox(height: 8),
                const Text(
                  '这里展示当前对话可以使用的记忆。你可以更正，也可以让 TA 忘记。',
                  style: TextStyle(color: XinYuColors.muted, height: 1.6),
                ),
                const SizedBox(height: 14),
                if (busy) const LinearProgressIndicator(),
                if (error != null)
                  Padding(
                    padding: const EdgeInsets.symmetric(vertical: 12),
                    child: Text(error!),
                  ),
                Flexible(
                  child: records.isEmpty
                      ? Padding(
                          padding: const EdgeInsets.symmetric(vertical: 40),
                          child: Text(
                            widget.controller.isDemo
                                ? '演示空间没有保存记忆。'
                                : '还没有记下的小事，我们可以慢慢聊。',
                          ),
                        )
                      : ListView.separated(
                          shrinkWrap: true,
                          itemCount: records.length,
                          separatorBuilder: (_, _) => const Divider(height: 24),
                          itemBuilder: (_, index) {
                            final record = records[index];
                            return Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                SelectableText(
                                  record['content'] as String? ?? '',
                                  style: const TextStyle(height: 1.7),
                                ),
                                const SizedBox(height: 6),
                                Row(
                                  mainAxisAlignment: MainAxisAlignment.end,
                                  children: [
                                    TextButton.icon(
                                      onPressed: busy
                                          ? null
                                          : () =>
                                                _change(record, forget: false),
                                      icon: const Icon(
                                        Icons.edit_outlined,
                                        size: 17,
                                      ),
                                      label: const Text('更正'),
                                    ),
                                    TextButton.icon(
                                      onPressed: busy
                                          ? null
                                          : () => _change(record, forget: true),
                                      icon: const Icon(
                                        Icons.delete_outline_rounded,
                                        size: 17,
                                      ),
                                      label: const Text('遗忘'),
                                    ),
                                  ],
                                ),
                              ],
                            );
                          },
                        ),
                ),
              ],
            ),
          ),
        ),
      ),
    ),
  );
}
