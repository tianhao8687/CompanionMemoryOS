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
        ? Image.memory(
            snapshot.data!,
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
  });
  final CompanionController controller;
  final bool isUser;
  final double size;
  @override
  Widget build(BuildContext context) {
    final id =
        controller.settings[isUser ? 'user_avatar' : 'companion_avatar']
            as String?;
    final name = isUser ? controller.userName : controller.companionName;
    final fallback = CompanionAvatar(
      size: size,
      label: name.isEmpty ? '我' : name.characters.last,
    );
    if (id == null) return fallback;
    return Container(
      width: size,
      height: size,
      decoration: BoxDecoration(
        shape: BoxShape.circle,
        border: Border.all(color: Colors.white, width: 1.5),
      ),
      child: ClipOval(
        child: LocalImage(
          controller: controller,
          id: id,
          width: size,
          height: size,
          fallback: fallback,
        ),
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
          borderRadius: BorderRadius.circular(12),
          child: LocalImage(
            controller: controller,
            id: id,
            width: 240,
            height: 180,
          ),
        ),
      ),
    ),
  );
}
