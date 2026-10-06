import 'dart:ui' as ui;

import 'package:flutter/material.dart';

import 'glass.dart';

/// A quiet surface for reading; panel highlights do not belong on every message.
class MessageSurface extends StatelessWidget {
  const MessageSurface({super.key, required this.isUser, required this.child});

  final bool isUser;
  final Widget child;

  static const corners = BorderRadius.all(Radius.circular(16));

  @override
  Widget build(BuildContext context) => DecoratedBox(
    decoration: const BoxDecoration(
      borderRadius: corners,
      boxShadow: [
        BoxShadow(
          color: Color(0x03515e70),
          blurRadius: 12,
          offset: Offset(0, 2),
        ),
      ],
    ),
    child: ClipRRect(
      borderRadius: corners,
      child: BackdropFilter.grouped(
        filter: ui.ImageFilter.blur(sigmaX: 18, sigmaY: 18),
        child: DecoratedBox(
          decoration: BoxDecoration(
            borderRadius: corners,
            gradient: LinearGradient(
              begin: Alignment.topLeft,
              end: Alignment.bottomRight,
              colors: [
                Color.alphaBlend(
                  const Color(0x18ffffff),
                  isUser ? XinYuColors.outgoing : XinYuColors.incoming,
                ),
                isUser ? XinYuColors.outgoing : XinYuColors.incoming,
              ],
            ),
            border: Border.all(color: const Color(0x66ffffff), width: .6),
          ),
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 11),
            child: child,
          ),
        ),
      ),
    ),
  );
}
