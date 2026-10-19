typedef SpeechResult = void Function(String words, bool finalResult);

abstract interface class SpeechInput {
  Future<bool> initialize({
    required void Function(String) onStatus,
    required void Function(String) onError,
  });
  Future<List<({String id, String name})>> languages();
  Future<void> listen({
    required String? locale,
    required SpeechResult onResult,
  });
  Future<void> stop();
  Future<void> cancel();
}
