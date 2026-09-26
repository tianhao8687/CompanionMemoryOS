import 'dart:math';
import 'dart:ui' as ui;

import 'package:flutter/services.dart';

import 'models.dart';

Future<Uint8List?> pickLocalImage(String purpose) async {
  final bytes = await const MethodChannel('xinyu/local-files')
      .invokeMethod<Uint8List>('pickImage');
  if (bytes == null) return null;
  return normalizeImage(
    bytes,
    maxSide: purpose.endsWith('avatar') ? 512 : 2048,
  );
}

Future<Uint8List?> pickLocalSticker() async {
  final bytes = await const MethodChannel('xinyu/local-files')
      .invokeMethod<Uint8List>('pickImage');
  return bytes == null ? null : normalizeSticker(bytes);
}

Future<Uint8List> normalizeSticker(Uint8List bytes) async {
  final gif =
      bytes.length >= 6 &&
      String.fromCharCodes(bytes.take(6)).startsWith('GIF8');
  if (!gif) return normalizeImage(bytes, maxSide: 512);
  if (bytes.length > 2 * 1024 * 1024) {
    throw const CompanionException('GIF 动图最多 2 MB。');
  }
  ui.ImmutableBuffer? buffer;
  ui.ImageDescriptor? descriptor;
  ui.Codec? codec;
  try {
    buffer = await ui.ImmutableBuffer.fromUint8List(bytes);
    descriptor = await ui.ImageDescriptor.encoded(buffer);
    if (descriptor.width > 512 || descriptor.height > 512) {
      throw const CompanionException('GIF 动图宽高需在 512 像素以内。');
    }
    codec = await descriptor.instantiateCodec();
    if (codec.frameCount > 60) throw const CompanionException('GIF 动图最多 60 帧。');
    for (var i = 0; i < codec.frameCount; i++) {
      (await codec.getNextFrame()).image.dispose();
    }
    return bytes; // Preserve animation, never re-encode only the first frame.
  } on CompanionException {
    rethrow;
  } catch (_) {
    throw const CompanionException('无法读取这张动图，请换一张。');
  } finally {
    codec?.dispose();
    descriptor?.dispose();
    buffer?.dispose();
  }
}

Future<Uint8List> normalizeImage(Uint8List bytes, {int maxSide = 2048}) async {
  if (bytes.isEmpty || bytes.length > 20 * 1024 * 1024) {
    throw const CompanionException('请选择 20 MB 以内的图片。');
  }
  ui.ImmutableBuffer? buffer;
  ui.ImageDescriptor? descriptor;
  ui.Codec? codec;
  ui.Image? image;
  try {
    buffer = await ui.ImmutableBuffer.fromUint8List(bytes);
    descriptor = await ui.ImageDescriptor.encoded(buffer);
    if (descriptor.width * descriptor.height > 80000000) {
      throw const CompanionException('图片分辨率过大，请先缩小。');
    }
    final ratio = min(1.0, maxSide / max(descriptor.width, descriptor.height));
    codec = await descriptor.instantiateCodec(
      targetWidth: max(1, (descriptor.width * ratio).round()),
      targetHeight: max(1, (descriptor.height * ratio).round()),
    );
    image = (await codec.getNextFrame()).image;
    final data = await image.toByteData(format: ui.ImageByteFormat.png);
    if (data == null || data.lengthInBytes > 8 * 1024 * 1024) {
      throw const CompanionException('图片处理后超过 8 MB，请换一张较小的图片。');
    }
    return data.buffer.asUint8List(data.offsetInBytes, data.lengthInBytes);
  } on CompanionException {
    rethrow;
  } catch (_) {
    throw const CompanionException('无法读取图片，请选择 PNG、JPEG 或 WebP 图片。');
  } finally {
    image?.dispose();
    codec?.dispose();
    descriptor?.dispose();
    buffer?.dispose();
  }
}
