/// 界面上的公共小控件：卡片、各种按钮、浮层提示。
///
/// 按钮都走 TapBox —— 按下缩一点、边框变亮，对应网页上 :active 那一下反馈。
library;

import 'package:flutter/material.dart';

import 'theme.dart';

/// 全局的浮层提示出口，给 core 层（收不到电脑的报错时）直接调用。
final GlobalKey<ScaffoldMessengerState> messengerKey =
    GlobalKey<ScaffoldMessengerState>();

void showToast(String message, {bool error = false}) {
  final messenger = messengerKey.currentState;
  if (messenger == null || message.isEmpty) return;
  messenger.clearSnackBars();
  messenger.showSnackBar(
    SnackBar(
      content: Text(message),
      duration: const Duration(milliseconds: 1800),
      backgroundColor: error ? const Color(0xFF3A1F1F) : kCard2,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(10),
        side: BorderSide(color: error ? const Color(0xFF5C2B2B) : kLine),
      ),
      margin: const EdgeInsets.fromLTRB(24, 0, 24, 24),
    ),
  );
}

/// 卡片。title / hint / trailing 都给了就按"标题在左、说明和按钮在右"排。
class Panel extends StatelessWidget {
  const Panel({
    super.key,
    this.title,
    this.hint,
    this.trailing,
    this.hintOnTap,
    required this.children,
  });

  final String? title;
  final String? hint;
  final Widget? trailing;

  /// 说明文字可点（点「窗口」卡片右上角的标题弹出窗口列表）。给了它就在文字
  /// 右边补一个小三角，提示这里点得动。
  final VoidCallback? hintOnTap;

  final List<Widget> children;

  /// 表头里「标题」和「说明」之间最窄留多少。说明是右对齐的，平时它俩离得
  /// 比这远；只有标题长到占满时才会压到这个宽度，这就是那段"留白"的下限。
  static const double _titleGap = 14;

  /// 说明和右边那组按钮之间留多少（「窗口」卡片那三个标题栏键就挂在 trailing）。
  static const double _trailingGap = 10;

  /// 表头：[标题] …… [说明] [右边那组按钮]。
  ///
  /// 标题按自己的宽度占位、说明吃掉剩下的空间，反过来不行 —— 说明一长就会把
  /// 标题（比如「窗口」两个字）挤没。说明本身是右对齐 + 省略号的，所以标题短
  /// 的时候，那段空白自然就落在中间。
  List<Widget> _header() {
    final onTap = hintOnTap;
    Widget? hintBox;
    if (hint != null) {
      final text = Text(
        hint!,
        maxLines: 1,
        textAlign: TextAlign.right,
        overflow: TextOverflow.ellipsis,
        style: const TextStyle(fontSize: 11, color: kMuted),
      );
      hintBox = onTap == null
          ? text
          : GestureDetector(
              onTap: onTap,
              behavior: HitTestBehavior.opaque,
              child: Row(
                mainAxisAlignment: MainAxisAlignment.end,
                children: [
                  Flexible(child: text),
                  const SizedBox(width: 4),
                  // 向下的小三角，和网页上那个 caret 一个意思
                  const Icon(Icons.arrow_drop_down, size: 14, color: kMuted),
                ],
              ),
            );
    }

    return <Widget>[
      if (title != null) ...[
        Text(
          title!,
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
          style: const TextStyle(
            fontSize: 14,
            fontWeight: FontWeight.w600,
            color: kMuted,
          ),
        ),
        if (hintBox != null || trailing != null) const SizedBox(width: _titleGap),
      ],
      // 说明吃掉中间的空间，右边那组按钮才贴得住右边。没有说明时（音量卡片就
      // 是「音量」+「静音」，没有说明）用 Spacer 顶开，效果和网页上
      // .card-head 的 space-between 一致。
      if (hintBox != null)
        Expanded(child: hintBox)
      else if (trailing != null)
        const Spacer(),
      if (trailing != null) ...[
        if (hintBox != null) const SizedBox(width: _trailingGap),
        trailing!,
      ],
    ];
  }

  @override
  Widget build(BuildContext context) {
    final hasHeader = title != null || hint != null || trailing != null;

    return Container(
      margin: const EdgeInsets.only(bottom: 12),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: kCard,
        border: Border.all(color: kLine),
        borderRadius: BorderRadius.circular(kRadius),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          if (hasHeader) ...[
            Row(children: _header()),
            const SizedBox(height: 12),
          ],
          ...children,
        ],
      ),
    );
  }
}

/// 通用可点方块。
class TapBox extends StatefulWidget {
  const TapBox({
    super.key,
    required this.child,
    this.onTap,
    this.color = kCard2,
    this.borderColor = kLine,
    this.radius = 10,
    this.padding = const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
    this.alignment = Alignment.center,
    this.width,
    this.height,
    this.showBorder = true,
  });

  final Widget child;
  final VoidCallback? onTap;
  final Color color;
  final Color borderColor;
  final double radius;
  final EdgeInsetsGeometry padding;

  /// 内容在方块里的对齐方式。默认居中；左侧文字（菜单项那种）要传
  /// [Alignment.centerLeft]，否则整块文字会跟着内容宽度居中。
  final AlignmentGeometry alignment;
  final double? width;
  final double? height;
  final bool showBorder;

  @override
  State<TapBox> createState() => _TapBoxState();
}

class _TapBoxState extends State<TapBox> {
  bool _pressed = false;

  @override
  Widget build(BuildContext context) {
    // onTap 为空就是"这个键当前不可用"，那连按下缩一下的反馈也别给
    final enabled = widget.onTap != null;
    return GestureDetector(
      onTapDown: enabled ? (_) => setState(() => _pressed = true) : null,
      onTapUp: enabled ? (_) => setState(() => _pressed = false) : null,
      onTapCancel: enabled ? () => setState(() => _pressed = false) : null,
      onTap: widget.onTap,
      child: AnimatedScale(
        scale: _pressed ? 0.96 : 1,
        duration: const Duration(milliseconds: 60),
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 120),
          width: widget.width,
          height: widget.height,
          padding: widget.padding,
          alignment: widget.alignment,
          decoration: BoxDecoration(
            color: widget.color,
            border: widget.showBorder
                ? Border.all(color: _pressed ? kAccent : widget.borderColor)
                : null,
            borderRadius: BorderRadius.circular(widget.radius),
          ),
          child: widget.child,
        ),
      ),
    );
  }
}

/// 小圆角胶囊按钮（卡片右上角那种）。
class PillButton extends StatelessWidget {
  const PillButton({super.key, required this.label, this.onTap, this.active = false});

  final String label;
  final VoidCallback? onTap;
  final bool active;

  @override
  Widget build(BuildContext context) {
    return TapBox(
      onTap: onTap,
      radius: 999,
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 5),
      color: active ? kAccent : kCard2,
      borderColor: active ? kAccent : kLine,
      child: Text(
        label,
        style: TextStyle(
          fontSize: 12,
          color: active ? Colors.white : kMuted,
        ),
      ),
    );
  }
}

/// 方形的图标大按钮（音量 ±、媒体键）。
class IconBox extends StatelessWidget {
  const IconBox({
    super.key,
    required this.child,
    this.onTap,
    this.size = 56,
    this.radius = 14,
    this.primary = false,
    this.disabled = false,
  });

  final Widget child;
  final VoidCallback? onTap;
  final double size;
  final double radius;
  final bool primary;

  /// 灰掉不可点。用在"这个操作当前播放器不支持"这类情况上。
  final bool disabled;

  @override
  Widget build(BuildContext context) {
    final content = IconTheme(
      data: IconThemeData(
        size: size * 0.42,
        color: primary ? Colors.white : kText,
      ),
      child: child,
    );
    return TapBox(
      onTap: disabled ? null : onTap,
      width: size,
      height: size,
      radius: radius,
      padding: EdgeInsets.zero,
      color: primary ? kAccent : kCard2,
      borderColor: primary ? kAccent : kLine,
      // 透明度跟网页端 :disabled 的 opacity 对齐
      child: disabled ? Opacity(opacity: 0.35, child: content) : content,
    );
  }
}

/// 行内按钮。放在 Row 里时用 expand: true 让它等分一行；
/// 直接塞进卡片（Column 里、高度不受限）时不能展开，否则会撑崩布局。
class ActionButton extends StatelessWidget {
  const ActionButton({
    super.key,
    required this.label,
    this.onTap,
    this.primary = false,
    this.danger = false,
    this.expand = false,
  });

  final String label;
  final VoidCallback? onTap;
  final bool primary;
  final bool danger;
  final bool expand;

  @override
  Widget build(BuildContext context) {
    final box = TapBox(
      onTap: onTap,
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 12),
      color: primary ? kAccent : kCard2,
      borderColor: primary ? kAccent : (danger ? const Color(0xFF4A2B2B) : kLine),
      child: Text(
        label,
        textAlign: TextAlign.center,
        style: TextStyle(
          fontSize: 14,
          color: primary ? Colors.white : (danger ? kDanger : kText),
        ),
      ),
    );
    return expand ? Expanded(child: box) : box;
  }
}

/// 功能键面板上的小按键。
class KeyChip extends StatelessWidget {
  const KeyChip({super.key, required this.label, this.onTap});

  final String label;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    return TapBox(
      onTap: onTap,
      radius: 10,
      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 10),
      child: Text(
        label,
        textAlign: TextAlign.center,
        style: const TextStyle(fontSize: 13, color: kText),
      ),
    );
  }
}

/// 分隔一小段间距的常用写法。
class Gap extends StatelessWidget {
  const Gap(this.height, {super.key});

  final double height;

  @override
  Widget build(BuildContext context) => SizedBox(height: height);
}
