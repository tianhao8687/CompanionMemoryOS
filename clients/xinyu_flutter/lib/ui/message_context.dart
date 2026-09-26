import 'package:flutter/material.dart';

import '../data/models.dart';
import '../state/companion_controller.dart';
import 'glass.dart';
import 'local_image.dart';

Future<void> showMessageContext(
  BuildContext context,
  CompanionController controller,
  String conversation,
  String id,
) async {
  await showDialog<void>(
    context: context,
    builder: (_) => _MessageContext(controller, conversation, id),
  );
}

class _MessageContext extends StatefulWidget {
  const _MessageContext(this.controller, this.conversation, this.id);
  final CompanionController controller;
  final String conversation, id;
  @override
  State<_MessageContext> createState() => _MessageContextState();
}

class _MessageContextState extends State<_MessageContext> {
  late final Future<List<ChatLine>> messages = _load();
  Future<List<ChatLine>> _load() async {
    try {
      return await widget.controller.localConnection!.context(
        widget.conversation,
        widget.id,
      );
    } catch (e) {
      if (mounted) widget.controller.reportFailure(e, title: '原消息暂时无法读取');
      rethrow;
    }
  }

  final anchor = GlobalKey();
  bool positioned = false;
  @override
  Widget build(BuildContext context) => Dialog(
    backgroundColor: Colors.transparent,
    insetPadding: const EdgeInsets.all(16),
    child: ConstrainedBox(
      constraints: const BoxConstraints(maxWidth: 660, maxHeight: 700),
      child: GlassSurface(
        tint: const Color(0xeef4faf5),
        padding: const EdgeInsets.all(18),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Row(
              children: [
                const Expanded(
                  child: Text('原来的对话', style: TextStyle(fontSize: 20)),
                ),
                IconButton(
                  tooltip: '关闭原对话',
                  onPressed: () => Navigator.pop(context),
                  icon: const Icon(Icons.close),
                ),
              ],
            ),
            Flexible(
              child: FutureBuilder<List<ChatLine>>(
                future: messages,
                builder: (context, snapshot) {
                  if (snapshot.hasError) {
                    return Padding(
                      padding: const EdgeInsets.all(24),
                      child: Text(
                        snapshot.error is CompanionException
                            ? '${snapshot.error}'
                            : '原消息已不可用。',
                      ),
                    );
                  }
                  if (!snapshot.hasData) {
                    return const Padding(
                      padding: EdgeInsets.all(30),
                      child: CircularProgressIndicator(),
                    );
                  }
                  if (!positioned) {
                    positioned = true;
                    WidgetsBinding.instance.addPostFrameCallback((_) {
                      final target = anchor.currentContext;
                      if (target != null) {
                        Scrollable.ensureVisible(target, alignment: .3);
                      }
                    });
                  }
                  return SingleChildScrollView(
                    child: Column(
                      children: [
                        for (final line in snapshot.data!)
                          Container(
                            key: line.id == widget.id ? anchor : null,
                            margin: const EdgeInsets.symmetric(vertical: 6),
                            padding: const EdgeInsets.all(14),
                            width: double.infinity,
                            decoration: BoxDecoration(
                              color: line.id == widget.id
                                  ? const Color(0x406aaf8e)
                                  : const Color(0x60ffffff),
                              borderRadius: XinYuShapes.cardCorners,
                            ),
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(
                                  line.notice
                                      ? '约定提醒'
                                      : line.isUser
                                      ? (widget.controller.userName.isEmpty
                                            ? '你'
                                            : widget.controller.userName)
                                      : widget.controller.companionName,
                                  style: const TextStyle(
                                    color: XinYuColors.muted,
                                    fontSize: 12,
                                  ),
                                ),
                                const SizedBox(height: 6),
                                SelectableText(line.text),
                                for (final image in line.imageIds)
                                  ChatPhoto(
                                    controller: widget.controller,
                                    id: image,
                                  ),
                              ],
                            ),
                          ),
                      ],
                    ),
                  );
                },
              ),
            ),
            TextButton(
              onPressed: () async {
                await widget.controller.select(widget.conversation);
                if (context.mounted) Navigator.pop(context);
              },
              child: const Text('打开这段对话'),
            ),
          ],
        ),
      ),
    ),
  );
}
