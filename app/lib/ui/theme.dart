/// 配色和控件样式，值直接抄 web/style.css 里的 CSS 变量，保证两个前端看着是一套东西。
library;

import 'package:flutter/material.dart';

const Color kBg = Color(0xFF0F1115);
const Color kCard = Color(0xFF191C23);
const Color kCard2 = Color(0xFF21252E);
const Color kLine = Color(0xFF2B313C);
const Color kText = Color(0xFFE8ECF1);
const Color kMuted = Color(0xFF8B95A5);
const Color kAccent = Color(0xFF4F8CFF);
const Color kDanger = Color(0xFFE5534B);
const Color kOk = Color(0xFF3FB950);

const double kRadius = 14;

ThemeData buildTheme() {
  const scheme = ColorScheme.dark(
    primary: kAccent,
    onPrimary: Colors.white,
    secondary: kAccent,
    surface: kCard,
    onSurface: kText,
    error: kDanger,
    onError: Colors.white,
  );

  return ThemeData(
    useMaterial3: true,
    brightness: Brightness.dark,
    colorScheme: scheme,
    scaffoldBackgroundColor: kBg,
    splashFactory: InkSparkle.splashFactory,
    sliderTheme: const SliderThemeData(
      trackHeight: 8,
      activeTrackColor: kAccent,
      inactiveTrackColor: kCard2,
      thumbColor: kAccent,
      overlayColor: Colors.transparent,
      thumbShape: RoundSliderThumbShape(enabledThumbRadius: 9),
      trackShape: RoundedRectSliderTrackShape(),
    ),
    textSelectionTheme: const TextSelectionThemeData(
      cursorColor: kAccent,
      selectionColor: Color(0x554F8CFF),
      selectionHandleColor: kAccent,
    ),
    snackBarTheme: const SnackBarThemeData(
      behavior: SnackBarBehavior.floating,
      backgroundColor: kCard2,
      contentTextStyle: TextStyle(color: kText, fontSize: 13),
      elevation: 0,
    ),
  );
}
