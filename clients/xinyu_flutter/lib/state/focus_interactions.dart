part of 'companion_controller.dart';

extension FocusInteractions on CompanionController {
  bool get canInteractWithFocus =>
      !_disposed && focus.enabled && !busy && !focus.busy;

  bool get canRetryFocusInteraction {
    final target = _focusReply;
    return target != null &&
        canRetry &&
        _failed?.$2 == target.$1 &&
        active == target.$3 &&
        focus.presence.accepts(target.$2) &&
        focus.presence.error != null;
  }

  Future<void> interactWithFocus(
    FocusInteraction action, {
    String? step,
  }) async {
    if (!canInteractWithFocus || active == null || !checkChatSetup()) return;
    final presence = focus.presence;
    switch (action) {
      case FocusInteraction.touch:
        if (!presence.touch()) return;
      case FocusInteraction.chooseStep:
        if (!presence.setStep(step ?? '')) return;
      case FocusInteraction.completeStep:
        step = presence.step;
        if (!presence.completeStep()) return;
      case FocusInteraction.breathe:
        if (focus.session?.paused != true) return;
    }
    final message = focusInteractionMessage(
      action,
      session: focus.session,
      step: step ?? presence.step,
    );
    await send(
      message,
      useComposerAttachments: false,
      focusTicket: presence.beginReply(),
    );
  }

  void _receiveFocusReply(String request, {String? text, String? failure}) {
    final target = _focusReply;
    if (_disposed ||
        target == null ||
        target.$1 != request ||
        target.$3 != active) {
      return;
    }
    focus.presence.finishReply(target.$2, text: text, failure: failure);
  }
}
