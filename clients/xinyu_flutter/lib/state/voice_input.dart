import 'dart:async';

import 'package:flutter/foundation.dart';

import '../data/speech_input.dart';
import '../data/local_speech_input.dart';
import '../data/speech_models.dart';

enum VoicePhase { ready, starting, listening, finishing, review, error }

/// An editable, unsent draft. Recognition never invokes the chat repository.
class VoiceInput extends ChangeNotifier {
  VoiceInput({SpeechInput? input}) : _input = input ?? LocalSpeechInput();
  final SpeechInput _input;
  SpeechModels? get models => _input is LocalSpeechInput ? _input.models : null;

  VoicePhase phase = VoicePhase.ready;
  String text = '', message = '';
  List<({String id, String name})> languages = [];
  String? locale;
  String _prefix = '', _recognized = '';
  int _generation = 0;
  bool _disposed = false, _used = false;
  Timer? _deadline, _finalWait;
  Future<void> _release = Future.value();

  bool get active =>
      phase == VoicePhase.starting ||
      phase == VoicePhase.listening ||
      phase == VoicePhase.finishing;

  Future<void> prepare() async {
    await _release;
    if (_disposed) return;
    if (_input case final LocalSpeechInput local) await local.prepare();
  }

  void releaseModel() {
    if (_input case final LocalSpeechInput local) {
      _release = _release
          .then((_) => local.releaseModel())
          .catchError((Object _) {});
    }
  }

  bool _current(int generation) => !_disposed && generation == _generation;
  void _emit() {
    if (!_disposed) notifyListeners();
  }

  void edit(String value) {
    if (!active) text = value;
  }

  void chooseLanguage(String? value) {
    if (!active) {
      locale = value;
      _emit();
    }
  }

  Future<void> start() async {
    if (active || _disposed) return;
    final generation = ++_generation;
    _prefix = text.trimRight();
    _recognized = '';
    message = '';
    phase = VoicePhase.starting;
    _emit();
    try {
      await _release;
      if (!_current(generation)) return;
      _used = true;
      final available = await _input.initialize(
        onStatus: (status) {
          if (!_current(generation)) return;
          if (status == 'buffering') {
            message = '已经开始录音，正在准备出字，开头会保留。';
            _emit();
          } else if (status == 'decoderReady' || status == 'listening') {
            message = '';
            _emit();
          }
          if (status == 'notListening' || status == 'done') {
            phase = VoicePhase.finishing;
            _waitForFinal(generation);
            _emit();
          }
        },
        onError: (code) {
          if (_current(generation)) _fail(errorMessage(code));
        },
      );
      if (!_current(generation)) return;
      if (!available) {
        _fail('本地识别未就绪。请检查语音资源和麦克风权限；暂时也可以用键盘输入。');
        return;
      }
      if (languages.isEmpty) {
        try {
          languages = await _input.languages().timeout(
            const Duration(seconds: 5),
          );
        } catch (_) {
          languages =
              []; // The local bilingual model needs no language selection.
        }
        if (!_current(generation)) return;
        final chinese = languages.where(
          (item) => item.id.toLowerCase().replaceAll('-', '_').startsWith('zh'),
        );
        if (locale == null && chinese.isNotEmpty) {
          locale = chinese
              .firstWhere(
                (item) => item.id.toLowerCase().replaceAll('-', '_') == 'zh_cn',
                orElse: () => chinese.first,
              )
              .id;
        }
      }
      await _input.listen(
        locale: locale,
        onResult: (words, finalResult) {
          if (!_current(generation)) return;
          if (words.trim().isNotEmpty) _recognized = words.trim();
          text = [
            _prefix,
            _recognized,
          ].where((part) => part.isNotEmpty).join('\n');
          if (finalResult) {
            _complete();
          } else {
            _emit();
          }
        },
      );
      if (_current(generation) && phase == VoicePhase.starting) {
        phase = VoicePhase.listening;
        _deadline = Timer(const Duration(seconds: 60), () => unawaited(stop()));
        _emit();
      }
    } catch (_) {
      if (_current(generation)) _fail('语音服务暂时不可用，已识别的文字会保留。请稍后重试或用键盘输入。');
    }
  }

  void _waitForFinal(int generation) {
    _finalWait ??= Timer(const Duration(seconds: 20), () {
      if (_current(generation)) {
        _fail('最后几个字未能识别完成，已保留当前文字，请检查后使用。');
      }
    });
  }

  Future<void> stop() async {
    if (phase != VoicePhase.listening) return;
    final generation = _generation;
    phase = VoicePhase.finishing;
    _deadline?.cancel();
    _waitForFinal(generation);
    _emit();
    try {
      await _input.stop();
    } catch (_) {
      if (_current(generation)) _complete();
    }
  }

  void _end() {
    ++_generation;
    _deadline?.cancel();
    _finalWait?.cancel();
    _deadline = _finalWait = null;
    if (_used) {
      _used = false;
      _release = _input.cancel().catchError((Object _) {});
    }
  }

  void _complete() {
    _end();
    phase = text.isEmpty ? VoicePhase.ready : VoicePhase.review;
    message = text.isEmpty ? '还没听清，可以再说一次。' : '';
    _emit();
  }

  void _fail(String value) {
    _end();
    phase = VoicePhase.error;
    message = value;
    _emit();
  }

  void interrupt() {
    if (!active) {
      releaseModel();
      return;
    }
    _end();
    phase = text.isEmpty ? VoicePhase.ready : VoicePhase.review;
    message = '语音输入已暂停，识别到的文字留在这里。';
    releaseModel();
    _emit();
  }

  Future<void> close() {
    _end();
    releaseModel();
    text = _prefix = message = '';
    phase = VoicePhase.ready;
    _emit();
    return _release;
  }

  static String errorMessage(String code) => switch (code) {
    'voice_model_missing' => '请先下载免费的语音资源，完成后即可离线使用。',
    'voice_model_load' => '本地语音资源加载失败。请关闭占用内存较多的应用后重试。',
    'voice_too_slow' => '这台设备暂时处理不过来，已保留识别文字。请缩短每段语音后重试。',
    'voice_interrupted' => '语音输入已中断，已识别的文字会保留。',
    'voice_audio_format' => '当前录音设备不支持所需音频格式，请换用设备麦克风。',
    'voice_audio_limit' => '这段语音已到长度上限，可以检查文字后继续说。',
    'error_permission' ||
    'error_permission_denied' ||
    'error_permission_denied_never_ask' ||
    'error_insufficient_permissions' => '麦克风权限未开启，请在系统设置中允许心隅使用麦克风。',
    'error_no_match' || 'error_speech_timeout' => '还没听清，可以靠近麦克风再说一次。',
    'error_audio' ||
    'error_busy' ||
    'error_recognizer_busy' => '麦克风或语音服务正忙，请结束其他录音或通话后重试。',
    _ => '本地语音识别暂时不可用，已识别的文字会保留。可以稍后重试或用键盘输入。',
  };

  @override
  void dispose() {
    _disposed = true;
    _end();
    if (_input case final LocalSpeechInput local) {
      unawaited(local.dispose().catchError((Object _) {}));
    }
    models?.dispose();
    super.dispose();
  }
}
