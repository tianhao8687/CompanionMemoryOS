import 'dart:convert';
import 'dart:typed_data';

/// Import character content, never executable extensions or global instructions.
class PersonaDraft {
  const PersonaDraft({
    required this.name,
    required this.description,
    this.examples = '',
    this.notes = const [],
  });
  final String name, description, examples;
  final List<String> notes;
}

PersonaDraft parsePersonaText(String input) {
  final text = input.replaceFirst('\ufeff', '').trim();
  if (text.isEmpty) throw const FormatException('请先粘贴人设内容。');
  if (utf8.encode(text).length > 256 * 1024) {
    throw const FormatException('人设文字超过 256 KB，请精简后再导入。');
  }
  if (!text.startsWith('{') && !text.startsWith('[')) {
    return PersonaDraft(name: '', description: text);
  }
  // Bound nesting before the JSON decoder allocates a deeply recursive object.
  var depth = 0;
  var quoted = false;
  var escaped = false;
  for (final unit in text.codeUnits) {
    if (escaped) {
      escaped = false;
      continue;
    }
    if (quoted && unit == 92) {
      escaped = true;
      continue;
    }
    if (unit == 34) {
      quoted = !quoted;
      continue;
    }
    if (!quoted && (unit == 123 || unit == 91) && ++depth > 32) {
      throw const FormatException('角色卡结构过于复杂。');
    }
    if (!quoted && (unit == 125 || unit == 93)) depth--;
  }
  final dynamic decoded;
  try {
    decoded = jsonDecode(text);
  } on FormatException {
    throw const FormatException('JSON 格式不完整，请检查角色卡文件。');
  }
  if (decoded is! Map) throw const FormatException('这不是有效的角色卡。');
  final spec = decoded['spec'];
  if (spec != null && spec != 'chara_card_v2' && spec != 'chara_card_v3') {
    throw const FormatException('暂不支持此角色卡版本，请导出为 V1 / V2 / V3 JSON。');
  }
  final data = spec == null ? decoded : decoded['data'];
  if (data is! Map) throw const FormatException('角色卡缺少角色资料。');
  String field(String key) {
    final value = data[key];
    if (value == null) return '';
    if (value is! String) throw FormatException('角色卡的 $key 应为文字。');
    return value.trim();
  }

  final description = [
    field('description'),
    if (field('personality').isNotEmpty) '性格：${field('personality')}',
    if (field('scenario').isNotEmpty) '虚构背景：${field('scenario')}',
    if (field('music_taste').isNotEmpty) '音乐品味：${field('music_taste')}',
  ].where((part) => part.isNotEmpty).join('\n\n');
  if (description.isEmpty) throw const FormatException('角色卡没有可导入的描述或性格。');
  return PersonaDraft(
    name: field('name'),
    description: description,
    examples: [
      if (field('first_mes').isNotEmpty) '开场示例（不是既有对话）：\n${field('first_mes')}',
      field('mes_example'),
    ].where((part) => part.isNotEmpty).join('\n\n'),
    notes: [
      if (field('creator_notes').isNotEmpty) '作者说明：${field('creator_notes')}',
      if ([
        'system_prompt',
        'post_history_instructions',
        'character_book',
        'extensions',
        'alternate_greetings',
        'assets',
      ].any(
        (key) =>
            data[key] != null &&
            data[key].toString() != '' &&
            data[key].toString() != '{}' &&
            data[key].toString() != '[]',
      ))
        '已提取角色描述、性格、背景和对话示例。世界书、扩展、全局指令和其他资源暂不导入。',
    ],
  );
}

PersonaDraft parsePersonaBytes(Uint8List bytes) {
  if (bytes.isEmpty || bytes.length > 20 * 1024 * 1024) {
    throw const FormatException('请选择 20 MB 以内的角色卡。');
  }
  const signature = [137, 80, 78, 71, 13, 10, 26, 10];
  final png =
      bytes.length >= 8 &&
      List.generate(8, (i) => bytes[i] == signature[i]).every((v) => v);
  if (!png) {
    if (bytes.length > 256 * 1024) {
      throw const FormatException('文字角色卡最多 256 KB。');
    }
    try {
      return parsePersonaText(utf8.decode(bytes));
    } on FormatException catch (error) {
      throw FormatException(
        error.message == 'Invalid UTF-8 byte'
            ? '请选择 PNG、JSON 或 UTF-8 文本角色卡。'
            : error.message,
      );
    }
  }
  final view = ByteData.sublistView(bytes);
  String? payload;
  var ended = false;
  var chunks = 0;
  for (var offset = 8; offset + 12 <= bytes.length;) {
    if (++chunks > 10000) throw const FormatException('PNG 结构过于复杂。');
    final size = view.getUint32(offset);
    if (size > bytes.length - offset - 12) {
      throw const FormatException('PNG 文件不完整。');
    }
    final kind = ascii.decode(
      bytes.sublist(offset + 4, offset + 8),
      allowInvalid: true,
    );
    if (kind == 'tEXt') {
      final start = offset + 8;
      final end = start + size;
      var split = start;
      while (split < end && split - start < 80 && bytes[split] != 0) {
        split++;
      }
      final keyword = ascii.decode(
        bytes.sublist(start, split),
        allowInvalid: true,
      );
      if (split < end && (keyword == 'chara' || keyword == 'ccv3')) {
        if (size > 350 * 1024) throw const FormatException('角色卡中的人设文字过长。');
        if (payload == null || keyword == 'ccv3') {
          try {
            payload = utf8.decode(
              base64.decode(ascii.decode(bytes.sublist(split + 1, end))),
            );
          } on FormatException {
            throw const FormatException('PNG 中的角色资料已损坏。');
          }
        }
      }
    }
    offset += size + 12;
    if (kind == 'IEND') {
      ended = true;
      break;
    }
  }
  if (!ended) throw const FormatException('PNG 文件不完整。');
  if (payload == null) {
    throw const FormatException('这张图片没有角色卡资料，请选择原始 PNG 角色卡或 JSON 文件。');
  }
  if (!payload.trimLeft().startsWith('{')) {
    throw const FormatException('PNG 中的角色资料不是有效 JSON。');
  }
  return parsePersonaText(payload);
}
