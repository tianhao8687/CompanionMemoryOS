import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../data/persona_import.dart';
import '../state/companion_controller.dart';
import 'glass.dart';
import 'ui_standard.dart';

Future<bool?> showPersonaImport(
  BuildContext context,
  CompanionController controller,
) => showXinYuPage<bool>(
  context,
  (_) => PersonaImportSheet(controller: controller),
);

class PersonaImportSheet extends StatefulWidget {
  const PersonaImportSheet({super.key, required this.controller});
  final CompanionController controller;
  @override
  State<PersonaImportSheet> createState() => _PersonaImportSheetState();
}

class _PersonaImportSheetState extends State<PersonaImportSheet> {
  final text = TextEditingController();
  final name = TextEditingController();
  final description = TextEditingController();
  final examples = TextEditingController();
  final form = GlobalKey<FormState>();
  PersonaDraft? draft;
  String? error;
  bool working = false;
  late bool _controllerBusy;

  @override
  void initState() {
    super.initState();
    _controllerBusy = widget.controller.busy;
    widget.controller.addListener(_busyChanged);
  }

  void _busyChanged() {
    if (mounted && _controllerBusy != widget.controller.busy) {
      setState(() => _controllerBusy = widget.controller.busy);
    }
  }

  @override
  void dispose() {
    widget.controller.removeListener(_busyChanged);
    for (final controller in [text, name, description, examples]) {
      controller.dispose();
    }
    super.dispose();
  }

  Future<void> _read(bool file) async {
    setState(() {
      working = true;
      error = null;
    });
    try {
      PersonaDraft result;
      if (file) {
        final bytes = await const MethodChannel('xinyu/local-files')
            .invokeMethod<Uint8List>('pickPersona');
        if (bytes == null) return;
        result = await compute(parsePersonaBytes, bytes);
      } else {
        result = await compute(parsePersonaText, text.text);
      }
      if (!mounted) return;
      setState(() {
        draft = result;
        name.text = result.name.isEmpty
            ? widget.controller.companionName
            : result.name;
        description.text = result.description;
        examples.text = result.examples;
      });
      FocusManager.instance.primaryFocus?.unfocus();
    } catch (e) {
      if (mounted) {
        setState(
          () => error = e is FormatException ? e.message : '无法读取角色卡，请重新选择文件。',
        );
      }
    } finally {
      if (mounted) setState(() => working = false);
    }
  }

  Future<void> _save() async {
    if (!form.currentState!.validate()) return;
    setState(() {
      working = true;
      error = null;
    });
    try {
      await widget.controller.save({
        ...widget.controller.settingsCopy(),
        'companion_name': name.text.trim(),
        'style': 'custom',
        'custom_style': description.text.trim(),
        'custom_style_examples': examples.text.trim(),
        'custom_style_avoid': '',
        'persona_notes': '',
      });
      if (mounted) Navigator.pop(context, true);
    } catch (e) {
      if (mounted) {
        setState(
          () => error = widget.controller.reportFailure(e, title: '人设尚未保存'),
        );
      }
    } finally {
      if (mounted) setState(() => working = false);
    }
  }

  Widget _field(
    String label,
    TextEditingController controller,
    int limit, {
    int lines = 1,
    bool required = false,
  }) => Padding(
    padding: const EdgeInsets.only(bottom: 18),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text(label, style: XinYuLayout.body(context)),
        const SizedBox(height: 8),
        Semantics(
          label: label,
          child: TextFormField(
            controller: controller,
            minLines: lines,
            maxLines: lines + 4,
            maxLength: limit,
            maxLengthEnforcement: MaxLengthEnforcement.none,
            decoration: const InputDecoration(counterText: ''),
            validator: (value) => (required && (value ?? '').trim().isEmpty)
                ? '请填写$label'
                : (value ?? '').runes.length > limit
                ? '$label最多 $limit 字，请精简后再保存。'
                : null,
          ),
        ),
      ],
    ),
  );

  @override
  Widget build(BuildContext context) => XinYuPage(
    title: draft == null ? '导入人设' : '认识新的 TA',
    canClose: !working,
    footer: FilledButton.icon(
      onPressed: working || widget.controller.busy
          ? null
          : draft == null
          ? () => _read(false)
          : _save,
      icon: Icon(
        draft == null ? Icons.auto_awesome_outlined : Icons.check_rounded,
        size: 20,
      ),
      label: Text(
        working
            ? '正在整理…'
            : draft == null
            ? '整理人设'
            : '使用这份人设',
      ),
    ),
    child: Form(
      key: form,
      child: ListView(
        padding: const EdgeInsets.all(20),
        children: [
          if (draft == null) ...[
            GlassSurface(
              blur: 0,
              tint: const Color(0x65ffffff),
              padding: const EdgeInsets.all(20),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  const Icon(
                    Icons.badge_outlined,
                    size: 32,
                    color: XinYuColors.accent,
                  ),
                  const SizedBox(height: 12),
                  const Text(
                    '把 TA 的故事带进心隅',
                    textAlign: TextAlign.center,
                    style: XinYuLayout.section,
                  ),
                  const SizedBox(height: 8),
                  const Text(
                    '选一张角色卡，或粘贴一段人设。整理好后可以直接使用，也可以继续微调。',
                    style: XinYuLayout.note,
                  ),
                  const SizedBox(height: 16),
                  OutlinedButton.icon(
                    key: const Key('pick-persona'),
                    onPressed: working ? null : () => _read(true),
                    icon: const Icon(Icons.file_open_outlined),
                    label: const Text('选择角色卡 · PNG / JSON / TXT'),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 24),
            Text('也可以直接粘贴', style: XinYuLayout.body(context)),
            const SizedBox(height: 8),
            TextField(
              key: const Key('persona-paste'),
              controller: text,
              minLines: 6,
              maxLines: 12,
              maxLength: 32000,
              decoration: const InputDecoration(
                hintText: '角色的名字、性格、背景，或完整的人设文字…',
                counterText: '',
              ),
            ),
          ] else ...[
            const Text(
              '将替换当前角色的称呼、设定和示例。聊天记录与“我的资料”会保留，之后仍可在陪伴设置中修改。',
              style: XinYuLayout.note,
            ),
            const SizedBox(height: 20),
            _field('角色称呼', name, 24, required: true),
            _field('角色设定', description, 6000, lines: 5, required: true),
            _field('对话示例', examples, 2000, lines: 3),
            for (final note in draft!.notes)
              Padding(
                padding: const EdgeInsets.only(bottom: 12),
                child: Text(note, style: XinYuLayout.note),
              ),
            TextButton(
              onPressed: working ? null : () => setState(() => draft = null),
              child: const Text('重新选择'),
            ),
          ],
          if (error != null)
            Padding(
              padding: const EdgeInsets.only(top: 16),
              child: Semantics(
                liveRegion: true,
                child: Text(
                  error!,
                  style: const TextStyle(
                    color: Color(0xff9a423d),
                    fontSize: 14,
                  ),
                ),
              ),
            ),
        ],
      ),
    ),
  );
}
