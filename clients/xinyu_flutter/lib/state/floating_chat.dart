import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

import 'companion_controller.dart';

/// A second view of the existing controller. No second repository or chat store.
class FloatingChat extends ChangeNotifier {
  FloatingChat(this.controller, {MethodChannel? channel})
    : channel = channel ?? const MethodChannel('xinyu/floating-chat');

  final CompanionController controller;
  final MethodChannel channel;
  bool supported = false, permitted = false, running = false;
  bool readScreen = true, screenPermitted = false;
  String _screenNotice = '';
  String? _screenConversation;
  int? _lastScreen;
  bool _disposed = false, _started = false;
  int _editAck = 0;
  Timer? _timer;

  Future<void> initialize() async {
    if (_started) return;
    _started = true;
    channel.setMethodCallHandler(_receive);
    controller.addListener(_changed);
    controller.composerUpdates.addListener(_changed);
    await refresh();
  }

  Future<void> refresh() async {
    try {
      final state = await channel.invokeMapMethod<String, dynamic>('status');
      if (!_disposed && state != null) _status(state);
    } on MissingPluginException {
      // The native surface is Android-only; desktop chat remains unchanged.
    } on PlatformException {
      if (!_disposed) {
        running = false;
        notifyListeners();
      }
    }
  }

  void _status(Map<dynamic, dynamic> state) {
    supported = state['supported'] == true;
    permitted = state['permitted'] == true;
    running = state['running'] == true;
    readScreen = state['readScreen'] != false;
    screenPermitted = state['screenPermitted'] == true;
    if (running) _changed();
    notifyListeners();
  }

  Map<String, dynamic> snapshot() {
    final c = controller;
    if (_screenConversation != c.active) {
      _screenConversation = c.active;
      _screenNotice = '';
      _lastScreen = null;
    }
    final attachments = c.pendingImages.isNotEmpty || c.pendingQuote != null;
    return {
      'conversation': c.active,
      'name': c.companionDisplayName,
      'composer': c.composerText,
      'editAck': _editAck,
      'busy': c.busy,
      'editable': c.connected && !c.loading,
      'canSend': c.ready && !c.busy && !attachments && c.active != null,
      'canRetry': c.canRetry,
      'readScreen': readScreen,
      'screenVision': c.capabilities['vision_ready'] == true,
      'notice': attachments
          ? '输入框含图片或引用，请回到完整对话发送。'
          : c.chatSetupIssue()?.message ?? c.error ?? _screenNotice,
      'status': c.collecting ? '正在整理这句话' : (c.sending ? c.status : ''),
      'draft': c.draft,
      'messages': [
        for (final line in c.messages.skip(
          c.messages.length > 12 ? c.messages.length - 12 : 0,
        ))
          {
            'id': line.id,
            'text': line.text.isEmpty && line.imageIds.isNotEmpty
                ? '[图片 · 请在完整对话查看]'
                : line.text,
            'user': line.isUser,
          },
      ],
    };
  }

  Future<void> start() async {
    if (controller.loading || !controller.connected) {
      throw PlatformException(code: 'not_ready', message: '请等对话连接完成。');
    }
    if (controller.active == null) await controller.newConversation();
    if (controller.active == null) return;
    final state = await channel.invokeMapMethod<String, dynamic>(
      'start',
      snapshot(),
    );
    if (!_disposed && state != null) _status(state);
  }

  Future<void> stop() async {
    await channel.invokeMethod<void>('stop');
    await refresh();
  }

  Future<void> permission() => channel.invokeMethod<void>('permission');
  Future<void> screenPermission() =>
      channel.invokeMethod<void>('screen_permission');

  Future<void> setReadScreen(bool enabled) async {
    final value = await channel.invokeMapMethod<String, dynamic>(
      'screen_mode',
      enabled,
    );
    if (!_disposed && value != null) _status(value);
  }

  void _changed() {
    if (!running || _disposed) return;
    _timer ??= Timer(const Duration(milliseconds: 60), () {
      _timer = null;
      unawaited(_publish());
    });
  }

  Future<void> _publish() async {
    if (!running || _disposed) return;
    try {
      await channel.invokeMethod<void>('update', snapshot());
    } on PlatformException {
      await refresh();
    } on MissingPluginException {
      // A destroyed Android host cannot accept new view updates.
    }
  }

  Future<dynamic> _receive(MethodCall call) async {
    if (_disposed) return false;
    if (call.method == 'closed') {
      running = false;
      _timer?.cancel();
      _timer = null;
      notifyListeners();
      await controller.flushChatState();
      return null;
    }
    final args = call.arguments is Map ? call.arguments as Map : const {};
    if (call.method == 'state') {
      _status(args);
      return null;
    }
    if (!running || args['conversation'] != controller.active) return false;
    if (call.method == 'screen_open') {
      if (!readScreen) return false;
      _screenNotice = args['notice'] is String ? args['notice'] as String : '';
      final screen = args['screen'];
      if (screen is! Map) {
        await _publish();
        return true;
      }
      if (!controller.ready || controller.busy || controller.loading) {
        _screenNotice = controller.busy
            ? '先接着这一句聊，刚才的页面没有另发一轮。'
            : '请先完成对话连接，再点小点看当前页面。';
        await _publish();
        return true;
      }
      final context = Map<String, dynamic>.from(screen);
      if (context['package_name'] is! String ||
          context['text'] is! String ||
          (context['text'] as String).length > 4000 ||
          (context['image_base64'] != null &&
              context['image_base64'] is! String)) {
        return false;
      }
      final fingerprint = Object.hash(
        controller.active,
        context['package_name'],
        context['text'],
        context['image_base64'],
      );
      if (_lastScreen == fingerprint) {
        await _publish();
        return true;
      }
      _lastScreen = fingerprint;
      unawaited(
        controller.send(
          '陪我看看当前屏幕。',
          useComposerAttachments: false,
          screenContext: context,
        ),
      );
      await _publish();
      return true;
    }
    if (call.method == 'cancel') {
      if (controller.collecting) controller.cancelCollected();
      await controller.cancel();
      return true;
    }
    if (call.method == 'retry') {
      if (!controller.canRetry) return false;
      unawaited(controller.retry());
      return true;
    }
    if (call.method != 'edit' && call.method != 'send') return false;
    if (controller.loading || !controller.connected) return false;
    final text = args['text'];
    final edit = args['editId'];
    if (text is! String ||
        text.length > 6000 ||
        edit is! int ||
        edit < _editAck) {
      return false;
    }
    _editAck = edit;
    if (call.method == 'send' &&
        (!controller.ready ||
            controller.busy ||
            controller.pendingImages.isNotEmpty ||
            controller.pendingQuote != null)) {
      return false;
    }
    controller.updateExternalComposer(text);
    _screenNotice = '';
    if (call.method == 'edit') return true;
    final accepted = await controller.submit(text);
    if (accepted) controller.updateExternalComposer('');
    await _publish();
    return accepted;
  }

  @override
  void dispose() {
    _disposed = true;
    _timer?.cancel();
    channel.setMethodCallHandler(null);
    if (_started) {
      controller.removeListener(_changed);
      controller.composerUpdates.removeListener(_changed);
    }
    super.dispose();
  }
}
