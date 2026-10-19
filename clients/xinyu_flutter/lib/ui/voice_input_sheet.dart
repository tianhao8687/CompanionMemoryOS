import 'dart:async';

import 'package:flutter/material.dart';

import '../state/voice_input.dart';
import 'glass.dart';
import 'speech_model_card.dart';

Future<void> showVoiceInput(
  BuildContext context,
  VoiceInput voice, {
  required String? Function(String) insert,
}) async {
  await showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    useSafeArea: true,
    backgroundColor: Colors.transparent,
    builder: (_) => VoiceInputSheet(voice: voice, insert: insert),
  );
}

class VoiceInputSheet extends StatefulWidget {
  const VoiceInputSheet({super.key, required this.voice, required this.insert});
  final VoiceInput voice;
  final String? Function(String) insert;
  @override
  State<VoiceInputSheet> createState() => _VoiceInputSheetState();
}

class _VoiceInputSheetState extends State<VoiceInputSheet>
    with WidgetsBindingObserver {
  final _text = TextEditingController();
  String? _insertionError;
  VoiceInput get voice => widget.voice;

  @override
  void initState() {
    super.initState();
    _text.text = voice.text;
    voice.addListener(_changed);
    WidgetsBinding.instance.addObserver(this);
    voice.models?.addListener(_changed);
    unawaited(voice.prepare());
  }

  @override
  void didHaveMemoryPressure() => voice.interrupt();

  void _changed() {
    if (_text.text != voice.text) {
      _text.value = TextEditingValue(
        text: voice.text,
        selection: TextSelection.collapsed(offset: voice.text.length),
      );
    }
    if (mounted) setState(() {});
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    // The permission dialog itself can briefly make the app inactive.
    if (state == AppLifecycleState.paused ||
        state == AppLifecycleState.hidden ||
        state == AppLifecycleState.detached ||
        (state == AppLifecycleState.inactive &&
            voice.phase == VoicePhase.listening)) {
      voice.interrupt();
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    voice.removeListener(_changed);
    unawaited(voice.close());
    _text.dispose();
    voice.models?.removeListener(_changed);
    if (voice.models != null) unawaited(voice.models!.cancelDownload());
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final active = voice.active;
    final status = switch (voice.phase) {
      VoicePhase.ready =>
        voice.models != null && !voice.models!.ready ? '先准备好离线语音' : '准备好了就开始说',
      VoicePhase.starting => '正在准备本地识别…',
      VoicePhase.listening => '正在听 · 说完点停止',
      VoicePhase.finishing => '正在确认最后几个字…',
      VoicePhase.review => '说完了，检查一下文字',
      VoicePhase.error => '这次没能继续识别',
    };
    return Padding(
      padding: EdgeInsets.only(bottom: MediaQuery.viewInsetsOf(context).bottom),
      child: SafeArea(
        top: false,
        child: Container(
          constraints: BoxConstraints(
            maxHeight: MediaQuery.sizeOf(context).height * .85,
          ),
          decoration: const BoxDecoration(
            color: XinYuColors.sheet,
            borderRadius: BorderRadius.vertical(top: Radius.circular(24)),
          ),
          child: SingleChildScrollView(
            padding: const EdgeInsets.fromLTRB(24, 12, 24, 24),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Row(
                  children: [
                    const Expanded(
                      child: Text(
                        '说给我听',
                        style: TextStyle(
                          fontSize: 21,
                          fontWeight: FontWeight.w500,
                        ),
                      ),
                    ),
                    IconButton(
                      tooltip: '关闭语音输入',
                      onPressed: () => Navigator.pop(context),
                      icon: const Icon(Icons.close_rounded),
                    ),
                  ],
                ),
                Text(
                  '免费本地识别，录音不上传、不保存。文字确认后才放进输入框。',
                  style: const TextStyle(
                    fontSize: 13,
                    color: XinYuColors.muted,
                  ),
                ),
                if (voice.models != null)
                  SpeechModelCard(models: voice.models!, active: active),
                const SizedBox(height: 20),
                Semantics(
                  liveRegion: true,
                  child: Text(
                    status,
                    style: const TextStyle(
                      fontSize: 15,
                      color: XinYuColors.accent,
                    ),
                  ),
                ),
                const SizedBox(height: 12),
                TextField(
                  key: const Key('voice-preview'),
                  controller: _text,
                  readOnly: active,
                  minLines: 3,
                  maxLines: 6,
                  keyboardType: TextInputType.multiline,
                  onChanged: (value) {
                    voice.edit(value);
                    setState(() => _insertionError = null);
                  },
                  decoration: InputDecoration(
                    labelText: '识别文字',
                    hintText: '文字会出现在这里，发送前可以修改。',
                    filled: true,
                    fillColor: Colors.white,
                    border: OutlineInputBorder(
                      borderRadius: BorderRadius.circular(16),
                    ),
                  ),
                ),
                if (voice.languages.isNotEmpty) ...[
                  const SizedBox(height: 8),
                  DropdownButtonFormField<String>(
                    key: ValueKey('voice-language-${voice.locale}'),
                    initialValue: voice.locale ?? '',
                    isExpanded: true,
                    decoration: const InputDecoration(labelText: '识别语言'),
                    items: [
                      const DropdownMenuItem(value: '', child: Text('自动识别')),
                      for (final language in voice.languages)
                        DropdownMenuItem(
                          value: language.id,
                          child: Text(
                            language.name,
                            overflow: TextOverflow.ellipsis,
                          ),
                        ),
                    ],
                    onChanged: active
                        ? null
                        : (value) =>
                              voice.chooseLanguage(value == '' ? null : value),
                  ),
                ],
                if (voice.message.isNotEmpty || _insertionError != null) ...[
                  const SizedBox(height: 12),
                  Semantics(
                    liveRegion: true,
                    child: Text(
                      _insertionError ?? voice.message,
                      style: const TextStyle(
                        color: XinYuColors.ink,
                        fontSize: 14,
                      ),
                    ),
                  ),
                ],
                const SizedBox(height: 20),
                FilledButton.icon(
                  key: const Key('voice-listen'),
                  style: FilledButton.styleFrom(
                    minimumSize: const Size.fromHeight(48),
                    backgroundColor: XinYuColors.accent,
                  ),
                  onPressed:
                      (voice.models != null && !voice.models!.ready) ||
                          voice.phase == VoicePhase.starting ||
                          voice.phase == VoicePhase.finishing
                      ? null
                      : () {
                          FocusScope.of(context).unfocus();
                          unawaited(
                            voice.phase == VoicePhase.listening
                                ? voice.stop()
                                : voice.start(),
                          );
                        },
                  icon: Icon(
                    voice.phase == VoicePhase.listening
                        ? Icons.stop_rounded
                        : Icons.mic_none_rounded,
                  ),
                  label: Text(
                    voice.phase == VoicePhase.starting
                        ? '正在准备…'
                        : voice.phase == VoicePhase.finishing
                        ? '正在确认文字…'
                        : voice.phase == VoicePhase.listening
                        ? '停止录音'
                        : voice.text.isEmpty
                        ? '开始说话'
                        : '继续说',
                  ),
                ),
                const SizedBox(height: 8),
                OutlinedButton(
                  key: const Key('voice-insert'),
                  style: OutlinedButton.styleFrom(
                    minimumSize: const Size.fromHeight(48),
                  ),
                  onPressed: active || voice.text.trim().isEmpty
                      ? null
                      : () {
                          final error = widget.insert(voice.text.trim());
                          if (error == null) {
                            Navigator.pop(context);
                          } else {
                            setState(() => _insertionError = error);
                          }
                        },
                  child: const Text('放进输入框'),
                ),
                const SizedBox(height: 12),
                Text(
                  '支持普通话和英语，边说边显示；停顿时会分段。每段最多一分钟，可以继续补充。识别文字可能有误，发送前请检查。',
                  style: const TextStyle(
                    fontSize: 12,
                    color: XinYuColors.muted,
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
