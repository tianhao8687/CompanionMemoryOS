import 'dart:typed_data';

import 'package:flutter/material.dart';

import '../state/companion_controller.dart';
import 'glass.dart';

class LocalImage extends StatelessWidget {
  const LocalImage({
    super.key,
    required this.controller,
    required this.id,
    this.fit = BoxFit.cover,
    this.width,
    this.height,
    this.fallback,
  });
  final CompanionController controller;
  final String id;
  final BoxFit fit;
  final double? width, height;
  final Widget? fallback;
  @override
  Widget build(BuildContext context) => FutureBuilder<Uint8List>(
    future: controller.image(id),
    builder: (context, snapshot) => snapshot.hasData
        ? Image(
            image:
                width != null &&
                    height != null &&
                    width!.isFinite &&
                    height!.isFinite
                ? ResizeImage(
                    MemoryImage(snapshot.data!),
                    width: (width! * MediaQuery.devicePixelRatioOf(context))
                        .ceil()
                        .clamp(1, 1600),
                    height: (height! * MediaQuery.devicePixelRatioOf(context))
                        .ceil()
                        .clamp(1, 1600),
                    policy: ResizeImagePolicy.fit,
                  )
                : MemoryImage(snapshot.data!),
            fit: fit,
            width: width,
            height: height,
            gaplessPlayback: false,
            errorBuilder: (_, _, _) =>
                fallback ?? const Center(child: Text('图片不可用')),
          )
        : SizedBox(
            width: width,
            height: height,
            child:
                fallback ??
                Center(
                  child: snapshot.hasError
                      ? const Text('图片不可用')
                      : const Icon(Icons.image_outlined),
                ),
          ),
  );
}

class ProfileAvatar extends StatelessWidget {
  const ProfileAvatar({
    super.key,
    required this.controller,
    this.isUser = false,
    this.size = 32,
    this.fallbackColor,
    this.foregroundColor,
    this.shape = BoxShape.rectangle,
  });
  final CompanionController controller;
  final bool isUser;
  final double size;
  final Color? fallbackColor, foregroundColor;
  final BoxShape shape;
  @override
  Widget build(BuildContext context) {
    final id =
        controller.settings[isUser ? 'user_avatar' : 'companion_avatar']
            as String?;
    final name = isUser ? controller.userName : controller.companionDisplayName;
    final fallback = CompanionAvatar(
      size: size,
      label: name.isEmpty ? '我' : name.characters.last,
      backgroundColor: fallbackColor,
      foregroundColor: foregroundColor,
      shape: shape,
    );
    if (id == null) return fallback;
    final image = LocalImage(
      controller: controller,
      id: id,
      width: size,
      height: size,
      fallback: fallback,
    );
    return Container(
      width: size,
      height: size,
      decoration: BoxDecoration(
        shape: shape,
        borderRadius: shape == BoxShape.rectangle
            ? BorderRadius.circular(size * .27)
            : null,
        border: Border.all(color: const Color(0x80ffffff), width: .7),
      ),
      child: shape == BoxShape.circle
          ? ClipOval(child: image)
          : ClipRRect(
              borderRadius: BorderRadius.circular(size * .27),
              child: image,
            ),
    );
  }
}

class ChatPhoto extends StatelessWidget {
  const ChatPhoto({super.key, required this.controller, required this.id});
  final CompanionController controller;
  final String id;
  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.only(bottom: 8),
    child: Semantics(
      label: '查看聊天图片',
      button: true,
      child: InkWell(
        onTap: () => showDialog<void>(
          context: context,
          builder: (context) => Dialog.fullscreen(
            backgroundColor: Colors.black87,
            child: Stack(
              children: [
                Positioned.fill(
                  child: InteractiveViewer(
                    minScale: .5,
                    maxScale: 5,
                    child: LocalImage(
                      controller: controller,
                      id: id,
                      fit: BoxFit.contain,
                    ),
                  ),
                ),
                SafeArea(
                  child: Align(
                    alignment: Alignment.topRight,
                    child: IconButton(
                      tooltip: '关闭图片',
                      onPressed: () => Navigator.pop(context),
                      icon: const Icon(Icons.close, color: Colors.white),
                    ),
                  ),
                ),
              ],
            ),
          ),
        ),
        child: ClipRRect(
          borderRadius: BorderRadius.circular(16),
          child: LayoutBuilder(
            builder: (context, constraints) {
              final preferred = MediaQuery.sizeOf(context).width < 880
                  ? 240.0
                  : 320.0;
              final width = preferred.clamp(0.0, constraints.maxWidth);
              return LocalImage(
                controller: controller,
                id: id,
                width: width,
                height: width * .75,
              );
            },
          ),
        ),
      ),
    ),
  );
}
