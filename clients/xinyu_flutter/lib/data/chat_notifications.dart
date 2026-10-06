import 'package:flutter/services.dart';

/// Optional native capability: absent on Windows, tests and browser previews.
class ChatNotifications {
  bool _listening = false;
  static const channel = MethodChannel('xinyu/notifications');
  Future<T?> call<T>(String method, [Map<String, dynamic>? arguments]) async {
    try {
      return await channel.invokeMethod<T>(method, arguments);
    } on MissingPluginException {
      return null;
    } on PlatformException {
      return null;
    }
  }

  void listen(Future<void> Function(String) open) {
    _listening = true;
    channel.setMethodCallHandler((call) async {
      if (call.method == 'openConversation' && call.arguments is String) {
        await open(call.arguments as String);
      }
    });
  }

  void dispose() {
    if (_listening) channel.setMethodCallHandler(null);
    _listening = false;
  }
}
