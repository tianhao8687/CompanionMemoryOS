import 'package:flutter/material.dart';

import '../state/companion_controller.dart';
import '../data/models.dart';
import 'glass.dart';

Future<void> showCompanionSettings(
  BuildContext context,
  CompanionController controller,
) => showDialog<void>(
  context: context,
  barrierColor: const Color(0x2433403c),
  builder: (_) => SettingsSheet(controller: controller),
);

class SettingsSheet extends StatefulWidget {
  const SettingsSheet({super.key, required this.controller});
  final CompanionController controller;
  @override
  State<SettingsSheet> createState() => _SettingsSheetState();
}

class _SettingsSheetState extends State<SettingsSheet> {
  final _form = GlobalKey<FormState>();
  late Map<String, dynamic> values;
  late final TextEditingController companion,
      user,
      notes,
      address,
      customStyle,
      model,
      modelUrl;
  final apiKey = TextEditingController();
  bool working = false;
  bool rememberKey = false, clearKey = false;
  String? notice;
  int tab = 0;
  @override
  void initState() {
    super.initState();
    values = widget.controller.settingsCopy();
    companion = TextEditingController(text: widget.controller.companionName);
    user = TextEditingController(text: widget.controller.userName);
    notes = TextEditingController(
      text: values['persona_notes'] as String? ?? '',
    );
    address = TextEditingController(text: widget.controller.endpoint);
    customStyle = TextEditingController(
      text: values['custom_style'] as String? ?? '',
    );
    model = TextEditingController(
      text: values['deepseek']?['model'] as String? ?? 'deepseek-flash',
    );
    modelUrl = TextEditingController(
      text:
          values['deepseek']?['base_url'] as String? ??
          'https://api.deepseek.com',
    );
    rememberKey = widget.controller.capabilities['key_persisted'] == true;
  }

  @override
  void dispose() {
    for (final c in [
      companion,
      user,
      notes,
      address,
      apiKey,
      customStyle,
      model,
      modelUrl,
    ]) {
      c.dispose();
    }
    super.dispose();
  }

  Future<void> _action(
    Future<void> Function() action, {
    bool close = false,
    String? success,
  }) async {
    if (working) return;
    setState(() {
      working = true;
      notice = null;
    });
    try {
      await action();
      if (!mounted) return;
      if (close) {
        Navigator.pop(context);
        return;
      }
      setState(() {
        values = widget.controller.settingsCopy();
        companion.text = widget.controller.companionName;
        user.text = widget.controller.userName;
        notes.text = values['persona_notes'] as String? ?? '';
        customStyle.text = values['custom_style'] as String? ?? '';
        model.text =
            values['deepseek']?['model'] as String? ?? 'deepseek-flash';
        modelUrl.text =
            values['deepseek']?['base_url'] as String? ??
            'https://api.deepseek.com';
        rememberKey = widget.controller.capabilities['key_persisted'] == true;
        apiKey.clear();
        clearKey = false;
        notice =
            success ??
            (widget.controller.isDemo
                ? '已切换到演示空间；内容仅保留在本次运行。'
                : '本机数据已载入，请核对保存与模型选项。');
      });
    } catch (e) {
      if (mounted) {
        setState(
          () =>
              notice = e is CompanionException ? e.message : '操作未完成，请检查服务后重试。',
        );
      }
    } finally {
      if (mounted) setState(() => working = false);
    }
  }

  Future<void> _save() async {
    if (!_form.currentState!.validate()) return;
    values['companion_name'] = companion.text.trim();
    values['user_name'] = user.text.trim();
    values['persona_notes'] = notes.text.trim();
    values['custom_style'] = customStyle.text.trim();
    if (!widget.controller.isDemo) {
      final config = Map<String, dynamic>.from(
        values['deepseek'] as Map? ?? {},
      );
      config['model'] = model.text.trim();
      config['base_url'] = modelUrl.text.trim();
      values['deepseek'] = config;
    }
    await _action(
      () => widget.controller.save(
        values,
        apiKey: apiKey.text,
        rememberKey: rememberKey,
        clearKey: clearKey,
      ),
      close: true,
    );
  }

  @override
  Widget build(BuildContext context) {
    final size = MediaQuery.sizeOf(context);
    return Dialog(
      backgroundColor: Colors.transparent,
      elevation: 0,
      insetPadding: EdgeInsets.symmetric(
        horizontal: size.width < 600 ? 12 : 36,
        vertical: 20,
      ),
      child: ConstrainedBox(
        constraints: BoxConstraints(
          maxWidth: 570,
          maxHeight: size.height * .86,
        ),
        child: BackdropGroup(
          child: GlassSurface(
            key: const Key('settings-glass'),
            blur: 28,
            tint: const Color(0xb8faf9f5),
            radius: 30,
            padding: const EdgeInsets.all(22),
            child: Form(
              key: _form,
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Row(
                    children: [
                      const Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              '让这里，更像我们',
                              style: TextStyle(
                                fontSize: 22,
                                fontWeight: FontWeight.w600,
                              ),
                            ),
                            SizedBox(height: 5),
                            Text(
                              '相处的节奏，由你来定。',
                              style: TextStyle(
                                color: XinYuColors.muted,
                                fontSize: 13,
                              ),
                            ),
                          ],
                        ),
                      ),
                      IconButton(
                        tooltip: '关闭设置',
                        onPressed: working
                            ? null
                            : () => Navigator.pop(context),
                        icon: const Icon(Icons.close_rounded),
                      ),
                    ],
                  ),
                  const SizedBox(height: 22),
                  SizedBox(
                    width: double.infinity,
                    child: SegmentedButton<int>(
                      segments: const [
                        ButtonSegment(
                          value: 0,
                          label: Text('相处设定'),
                          icon: Icon(Icons.favorite_border_rounded, size: 17),
                        ),
                        ButtonSegment(
                          value: 1,
                          label: Text('连接与数据'),
                          icon: Icon(Icons.link_rounded, size: 18),
                        ),
                      ],
                      selected: {tab},
                      onSelectionChanged: working
                          ? null
                          : (v) => setState(() => tab = v.first),
                      showSelectedIcon: false,
                    ),
                  ),
                  const SizedBox(height: 20),
                  Flexible(
                    child: SingleChildScrollView(
                      key: const Key('settings-scroll'),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          if (tab == 0) ..._persona(),
                          if (tab == 1) ..._connection(),
                          if (notice != null)
                            Padding(
                              padding: const EdgeInsets.only(top: 16),
                              child: Semantics(
                                liveRegion: true,
                                child: Text(
                                  notice!,
                                  style: const TextStyle(
                                    color: Color(0xff865c43),
                                    height: 1.6,
                                  ),
                                ),
                              ),
                            ),
                        ],
                      ),
                    ),
                  ),
                  const SizedBox(height: 20),
                  Row(
                    children: [
                      Expanded(
                        child: Text(
                          widget.controller.isDemo
                              ? '演示设置仅在本次运行生效'
                              : '保存在这台设备上',
                          style: const TextStyle(
                            fontSize: 11,
                            color: XinYuColors.muted,
                          ),
                        ),
                      ),
                      const SizedBox(width: 8),
                      FilledButton(
                        onPressed: working || widget.controller.busy
                            ? null
                            : _save,
                        child: Text(working ? '处理中…' : '保存设置'),
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

  List<Widget> _persona() => [
    TextFormField(
      controller: companion,
      decoration: const InputDecoration(labelText: '怎么称呼 TA'),
      maxLength: 24,
      validator: (v) => v == null || v.trim().isEmpty ? '请填写一个称呼' : null,
    ),
    const SizedBox(height: 12),
    TextFormField(
      controller: user,
      decoration: const InputDecoration(labelText: '希望 TA 怎么称呼你'),
      maxLength: 24,
    ),
    const SizedBox(height: 12),
    DropdownButtonFormField<String>(
      key: ValueKey('style-${values['style']}'),
      isExpanded: true,
      initialValue: values['style'] as String? ?? 'gentle',
      decoration: const InputDecoration(labelText: '相处风格'),
      items: const [
        DropdownMenuItem(value: 'gentle', child: Text('温柔细腻')),
        DropdownMenuItem(value: 'playful', child: Text('明快俏皮')),
        DropdownMenuItem(value: 'steady', child: Text('沉稳坦诚')),
        DropdownMenuItem(value: 'custom', child: Text('自定义')),
      ],
      onChanged: (v) => setState(() => values['style'] = v),
    ),
    if (values['style'] == 'custom') ...[
      const SizedBox(height: 12),
      TextFormField(
        controller: customStyle,
        maxLines: 5,
        maxLength: 6000,
        decoration: const InputDecoration(labelText: '自定义相处风格'),
        validator: (value) =>
            value == null || value.trim().isEmpty ? '请描述希望的相处风格' : null,
      ),
    ],
    const SizedBox(height: 18),
    TextFormField(
      controller: notes,
      decoration: const InputDecoration(
        labelText: '想让 TA 了解的相处偏好',
        alignLabelWithHint: true,
      ),
      maxLines: 3,
      maxLength: 1000,
    ),
    SwitchListTile.adaptive(
      contentPadding: EdgeInsets.zero,
      title: const Text('允许浪漫互动', style: TextStyle(fontSize: 14)),
      subtitle: const Text('关闭后以普通陪伴关系相处。', style: TextStyle(fontSize: 12)),
      value: values['romance_consent'] == true,
      onChanged: (v) => setState(() => values['romance_consent'] = v),
    ),
  ];

  Future<void> _restore() async {
    final accepted = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('从备份恢复'),
        content: const Text('恢复会替换当前设备的聊天、记忆和设置。当前数据会先留一份恢复副本，模型 Key 不在备份中。'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('取消'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('选择备份'),
          ),
        ],
      ),
    );
    if (accepted != true || !mounted) return;
    bool? restored;
    await _action(() async {
      restored = await widget.controller.restoreBackup();
    });
    if (mounted && restored != null) {
      setState(() => notice = restored! ? '备份已恢复。' : '已取消，数据未更改。');
    }
  }

  Future<void> _backup() async {
    bool? saved;
    await _action(() async {
      saved = await widget.controller.backup();
    });
    if (mounted && saved != null) {
      setState(() => notice = saved! ? '备份已保存到你选择的位置。' : '已取消导出。');
    }
  }

  List<Widget> _connection() => [
    Text(
      widget.controller.isDemo ? '当前：界面演示' : '当前：本机数据',
      style: const TextStyle(fontWeight: FontWeight.w600),
    ),
    const SizedBox(height: 8),
    const Text(
      '聊天和记忆保存在这台设备，电脑和手机各自独立。使用在线模型时，会发送当前消息及必要的记忆上下文。',
      style: TextStyle(color: XinYuColors.muted, fontSize: 13, height: 1.6),
    ),
    const SizedBox(height: 12),
    FilledButton.tonalIcon(
      onPressed: working || widget.controller.busy
          ? null
          : () => _action(widget.controller.useLocal),
      icon: const Icon(Icons.refresh_rounded),
      label: Text(widget.controller.isDemo ? '打开本机数据' : '重新连接'),
    ),
    if (const bool.fromEnvironment('XINYU_DEVELOPMENT')) ...[
      const SizedBox(height: 12),
      TextFormField(
        controller: address,
        decoration: const InputDecoration(labelText: '开发服务地址'),
      ),
      TextButton(
        onPressed: working
            ? null
            : () => _action(() => widget.controller.connect(address.text)),
        child: const Text('连接开发服务'),
      ),
      TextButton(
        onPressed: working ? null : () => _action(widget.controller.useDemo),
        child: const Text('切换演示'),
      ),
    ],
    const SizedBox(height: 20),
    if (!widget.controller.isDemo) ...[
      DropdownButtonFormField<String>(
        key: ValueKey('mode-${values['model_mode']}'),
        isExpanded: true,
        initialValue: values['model_mode'] as String? ?? 'offline',
        decoration: InputDecoration(
          labelText: '回复方式',
          helperText: values['model_mode'] == 'api'
              ? null
              : '规则回复用于流程体验，不运行大模型。',
          helperMaxLines: 2,
        ),
        items: const [
          DropdownMenuItem(value: 'offline', child: Text('离线规则回复')),
          DropdownMenuItem(value: 'api', child: Text('联网调用模型')),
        ],
        onChanged: (v) => setState(() => values['model_mode'] = v),
      ),
      if (values['model_mode'] == 'api') ...[
        const SizedBox(height: 16),
        TextFormField(
          controller: model,
          decoration: const InputDecoration(labelText: '模型名称'),
          validator: (v) => v == null || v.trim().isEmpty ? '请填写模型名称' : null,
        ),
        const SizedBox(height: 12),
        TextFormField(
          controller: modelUrl,
          autocorrect: false,
          keyboardType: TextInputType.url,
          decoration: const InputDecoration(labelText: '模型 API 地址'),
          validator: (v) {
            final uri = Uri.tryParse(v?.trim() ?? '');
            return uri != null && uri.scheme == 'https' && uri.host.isNotEmpty
                ? null
                : '请填写服务商的 HTTPS API 地址';
          },
        ),
        const SizedBox(height: 12),
        TextFormField(
          controller: apiKey,
          obscureText: true,
          autocorrect: false,
          enableSuggestions: false,
          decoration: InputDecoration(
            labelText: 'API Key',
            helperText: widget.controller.capabilities['key_configured'] == true
                ? '已配置；留空保留现有 Key。'
                : '请填写你自己的模型服务 Key。',
          ),
        ),
        if (widget
                .controller
                .capabilities['credential_persistence_supported'] ==
            true)
          CheckboxListTile(
            contentPadding: EdgeInsets.zero,
            title: const Text('在这台设备安全保存 Key', style: TextStyle(fontSize: 14)),
            subtitle: const Text(
              '使用系统凭据存储；不会写入聊天备份。',
              style: TextStyle(fontSize: 12),
            ),
            value: rememberKey,
            onChanged: (v) => setState(() => rememberKey = v ?? false),
          ),
        if (widget.controller.capabilities['key_configured'] == true)
          CheckboxListTile(
            contentPadding: EdgeInsets.zero,
            title: const Text('清除已保存的 Key', style: TextStyle(fontSize: 14)),
            value: clearKey,
            onChanged: (v) => setState(() => clearKey = v ?? false),
          ),
      ],
      const SizedBox(height: 12),
      CheckboxListTile(
        contentPadding: EdgeInsets.zero,
        controlAffinity: ListTileControlAffinity.leading,
        title: const Text('允许保存对话与记忆', style: TextStyle(fontSize: 14)),
        subtitle: const Text('数据保存在当前设备。', style: TextStyle(fontSize: 12)),
        value: values['storage_consent'] == true,
        onChanged: (v) =>
            setState(() => values['storage_consent'] = v ?? false),
      ),
      CheckboxListTile(
        contentPadding: EdgeInsets.zero,
        controlAffinity: ListTileControlAffinity.leading,
        title: const Text('允许所选回复方式处理消息', style: TextStyle(fontSize: 14)),
        subtitle: const Text(
          '联网模型会处理必要上下文，并产生服务商 API 用量。',
          style: TextStyle(fontSize: 12),
        ),
        value: values['model_consent'] == true,
        onChanged: (v) => setState(() => values['model_consent'] = v ?? false),
      ),
      if (widget.controller.hasManagedStorage) ...[
        const Divider(height: 28),
        const Text('备份与恢复', style: TextStyle(fontWeight: FontWeight.w600)),
        const SizedBox(height: 8),
        const Text(
          '备份包含完整聊天和记忆，请保存到你信任的位置。恢复支持本应用生成的备份，最多 64 MB。',
          style: TextStyle(fontSize: 12, color: XinYuColors.muted, height: 1.6),
        ),
        const SizedBox(height: 10),
        Wrap(
          spacing: 8,
          runSpacing: 8,
          children: [
            OutlinedButton.icon(
              onPressed: working || widget.controller.busy ? null : _backup,
              icon: const Icon(Icons.save_alt_rounded),
              label: const Text('导出备份'),
            ),
            OutlinedButton.icon(
              onPressed: working || widget.controller.busy ? null : _restore,
              icon: const Icon(Icons.restore_rounded),
              label: const Text('从备份恢复'),
            ),
          ],
        ),
      ],
    ],
  ];
}
