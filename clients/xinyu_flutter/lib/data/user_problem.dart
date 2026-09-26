import 'dart:async';
import 'dart:io';

import 'package:flutter/services.dart';

import 'models.dart';

class UserProblem {
  const UserProblem(this.title, this.message, {this.openSettings = false});
  final String title, message;
  final bool openSettings;
}

String userProblemMessage(
  Object error, {
  String fallback = '操作未完成，暂时无法确定具体原因。请稍后再试。',
}) => switch (error) {
  CompanionException() => error.message,
  TimeoutException() => '等待服务响应超时，请检查网络或稍后再试。',
  SocketException() || HttpException() => '连接已中断，请检查网络和本机引擎后重试。',
  FileSystemException() => '文件读取或写入失败，请检查存储空间和文件访问权限。',
  FormatException() => '收到的数据格式不正确，请检查服务地址或导入文件。',
  PlatformException() => error.message ?? '系统操作未完成，请检查相关权限后重试。',
  _ => fallback,
};
