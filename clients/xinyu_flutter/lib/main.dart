import 'dart:async';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';

import 'state/companion_controller.dart';
import 'state/frame_probe.dart';
import 'ui/glass.dart';
import 'ui/home.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const XinYuApp());
}

class XinYuApp extends StatefulWidget {
  const XinYuApp({super.key, this.controller, this.probe});
  final CompanionController? controller;
  final FrameProbe? probe;
  @override
  State<XinYuApp> createState() => _XinYuAppState();
}

class _XinYuAppState extends State<XinYuApp> {
  late final CompanionController controller =
      widget.controller ?? CompanionController();
  late final FrameProbe probe = widget.probe ?? FrameProbe();
  @override
  void initState() {
    super.initState();
    // Failures remain visible in the controller's error region.
    unawaited(controller.initialize().catchError((Object _) {}));
  }

  @override
  void dispose() {
    if (widget.controller == null) controller.dispose();
    if (widget.probe == null) probe.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => MaterialApp(
    title: '心隅',
    debugShowCheckedModeBanner: false,
    locale: const Locale('zh', 'CN'),
    supportedLocales: const [Locale('zh', 'CN'), Locale('en')],
    localizationsDelegates: GlobalMaterialLocalizations.delegates,
    theme: ThemeData(
      useMaterial3: true,
      fontFamily: Platform.isWindows ? 'Microsoft YaHei UI' : null,
      fontFamilyFallback: const [
        'Microsoft YaHei',
        'PingFang SC',
        'Noto Sans CJK SC',
      ],
      colorScheme:
          ColorScheme.fromSeed(
            seedColor: XinYuColors.accent,
            brightness: Brightness.light,
          ).copyWith(
            surface: const Color(0xfff1eee7),
            onSurface: XinYuColors.ink,
            primary: XinYuColors.accent,
          ),
      scaffoldBackgroundColor: Colors.transparent,
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: const Color(0x66ffffff),
        contentPadding: const EdgeInsets.symmetric(
          horizontal: 16,
          vertical: 15,
        ),
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(15),
          borderSide: const BorderSide(color: Color(0xaaffffff)),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(15),
          borderSide: const BorderSide(color: Color(0xaaffffff)),
        ),
      ),
      filledButtonTheme: FilledButtonThemeData(
        style: FilledButton.styleFrom(
          minimumSize: const Size(48, 46),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(15),
          ),
        ),
      ),
      textButtonTheme: TextButtonThemeData(
        style: TextButton.styleFrom(minimumSize: const Size(44, 44)),
      ),
      iconButtonTheme: IconButtonThemeData(
        style: IconButton.styleFrom(minimumSize: const Size(44, 44)),
      ),
      scrollbarTheme: ScrollbarThemeData(
        thumbColor: WidgetStateProperty.all(const Color(0x65748a7c)),
        thickness: WidgetStateProperty.all(4),
      ),
    ),
    home: XinYuHome(controller: controller, probe: probe),
  );
}
