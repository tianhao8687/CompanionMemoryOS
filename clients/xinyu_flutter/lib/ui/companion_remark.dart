import 'package:flutter/material.dart';

import '../state/companion_controller.dart';
import 'glass.dart';

Future<void> showCompanionRemark(
  BuildContext context,
  CompanionController controller,
) => showDialog<void>(
  context: context,
  builder: (_) => _RemarkEditor(controller: controller),
);

class _RemarkEditor extends StatefulWidget {
  const _RemarkEditor({required this.controller});
  final CompanionController controller;
  @override
  State<_RemarkEditor> createState() => _RemarkEditorState();
}

class _RemarkEditorState extends State<_RemarkEditor> {
  late final name = TextEditingController(
    text: widget.controller.settings['companion_remark'] as String? ?? '',
  );
  late final note = TextEditingController(
    text: widget.controller.settings['companion_note'] as String? ?? '',
  );
  bool saving = false;
  String? error;

  Future<void> _save() async {
    setState(() {
      saving = true;
      error = null;
    });
    try {
      await widget.controller.save({
        ...widget.controller.settingsCopy(),
        'companion_remark': name.text.trim(),
        'companion_note': note.text.trim(),
      });
      if (mounted) Navigator.pop(context);
    } catch (e) {
      if (mounted) {
        setState(
          () => error = widget.controller.reportFailure(e, title: '备注未保存'),
        );
      }
    } finally {
      if (mounted) setState(() => saving = false);
    }
  }

  @override
  void dispose() {
    name.dispose();
    note.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => PopScope(
    canPop: !saving,
    child: Dialog(
      backgroundColor: Colors.transparent,
      insetPadding: const EdgeInsets.all(16),
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 440),
        child: GlassSurface(
          grouped: false,
          tint: XinYuColors.sheet,
          padding: const EdgeInsets.all(20),
          child: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Row(
                  children: [
                    const Expanded(
                      child: Text(
                        '设置备注',
                        style: TextStyle(
                          fontSize: 20,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                    ),
                    IconButton(
                      tooltip: '取消备注',
                      onPressed: saving ? null : () => Navigator.pop(context),
                      icon: const Icon(Icons.close_rounded),
                    ),
                  ],
                ),
                const SizedBox(height: 16),
                TextField(
                  key: const Key('companion-remark'),
                  controller: name,
                  enabled: !saving,
                  maxLength: 24,
                  autofocus: true,
                  decoration: InputDecoration(
                    labelText: '备注名',
                    hintText: widget.controller.companionName,
                    helperText: '留空时显示原来的称呼',
                  ),
                ),
                const SizedBox(height: 14),
                TextField(
                  key: const Key('companion-note'),
                  controller: note,
                  enabled: !saving,
                  minLines: 2,
                  maxLines: 3,
                  maxLength: 200,
                  decoration: const InputDecoration(
                    labelText: '备注（选填）',
                    hintText: '记下一点关于 TA 的事',
                  ),
                ),
                const SizedBox(height: 8),
                const Text(
                  '备注只用于你的界面，不改变 TA 的人物设定。',
                  style: TextStyle(
                    fontSize: 12,
                    height: 1.5,
                    color: XinYuColors.muted,
                  ),
                ),
                if (error != null)
                  Padding(
                    padding: const EdgeInsets.only(top: 12),
                    child: Text(
                      error!,
                      style: TextStyle(
                        color: Theme.of(context).colorScheme.error,
                      ),
                    ),
                  ),
                const SizedBox(height: 18),
                Row(
                  children: [
                    TextButton(
                      onPressed: saving
                          ? null
                          : () {
                              name.clear();
                              note.clear();
                            },
                      child: const Text('清空备注'),
                    ),
                    const Spacer(),
                    FilledButton(
                      key: const Key('save-remark'),
                      onPressed: saving ? null : _save,
                      child: Text(saving ? '保存中…' : '保存'),
                    ),
                  ],
                ),
              ],
            ),
          ),
        ),
      ),
    ),
  );
}
