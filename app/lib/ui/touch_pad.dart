/// 触摸板本体：只有那块面板，不带灵敏度、鼠标键那些设置项。
///
/// 触摸板整页和键盘页里嵌的那块都用它 —— 手势逻辑只留一份，两边行为才一致。
/// 手势和网页版逐条对齐：
///   单指滑动  → 移动光标（乘灵敏度）
///   轻点      → 左键   双指轻点 → 右键
///   双指上下滑 → 滚轮（往下滑＝往下滚，跟手机上看网页一个方向）
library;

import 'package:flutter/material.dart';

import '../core/client.dart';
import 'theme.dart';

/// 游戏模式：移动改成发相对位移。
///
/// 游戏（原神这类）看视角时会把光标 ClipCursor 锁在窗口中间并隐藏，那时
/// "读坐标 + 绝对定位"的常规发法位移会被吃掉，只有纯相对位移能转视角。
///
/// 放在这一层是因为"触摸板整页"和"键盘页里嵌的那块"要共用同一个开关 ——
/// 用户在整页那边打开了，嵌的那块也该是开的。进程重启就回到关闭。
bool padGameMode = false;

class TouchPad extends StatefulWidget {
  const TouchPad({super.key, this.tip, this.sensitivity = 2});

  /// 面板底部那行手势说明；不给就不画。
  final String? tip;

  /// 光标位移的放大倍数，整页那边由滑块控制。
  final double sensitivity;

  @override
  State<TouchPad> createState() => _TouchPadState();
}

class _TouchPadState extends State<TouchPad> {
  final RemoteClient _client = RemoteClient.instance;

  final Map<int, Offset> _pointers = <int, Offset>{};
  bool _pressed = false;
  int _maxFingers = 0;
  double _travel = 0;
  Offset _anchor = Offset.zero;
  DateTime _startedAt = DateTime.now();
  double _scrollAcc = 0;
  double _pendingDx = 0;
  double _pendingDy = 0;

  static const double _tapMs = 260;
  static const double _tapSlop = 12;
  static const double _notch = 20; // 滚一格要滑多少像素

  Offset _median() {
    if (_pointers.length < 2) return _pointers.values.first;
    final points = _pointers.values.toList();
    final a = points[0];
    final b = points[1];
    return Offset((a.dx + b.dx) / 2, (a.dy + b.dy) / 2);
  }

  void _onDown(PointerDownEvent event) {
    _pointers[event.pointer] = event.localPosition;
    if (_pointers.length == 1) {
      _startedAt = DateTime.now();
      _maxFingers = 1;
      _travel = 0;
      _scrollAcc = 0;
      _pendingDx = 0;
      _pendingDy = 0;
    }
    if (_pointers.length > _maxFingers) _maxFingers = _pointers.length;
    _anchor = _median();
    setState(() => _pressed = true);
  }

  void _onMove(PointerMoveEvent event) {
    if (!_pointers.containsKey(event.pointer)) return;
    _pointers[event.pointer] = event.localPosition;

    final current = _median();
    final dx = current.dx - _anchor.dx;
    final dy = current.dy - _anchor.dy;
    _anchor = current;
    _travel += dx.abs() + dy.abs();

    if (_pointers.length >= 2) {
      // 双指滑动 = 滚轮，和触屏上的自然滚动方向一致
      _scrollAcc += -dy;
      final notches = (_scrollAcc / _notch).truncate();
      if (notches != 0) {
        _scrollAcc -= notches * _notch;
        _client.send('mouse.wheel', {'delta': -notches * 120}, true);
      }
      return;
    }

    _pendingDx += dx * widget.sensitivity;
    _pendingDy += dy * widget.sensitivity;
    _flushMove();
  }

  void _flushMove() {
    final dx = _pendingDx.round();
    final dy = _pendingDy.round();
    _pendingDx -= dx; // 不够一个像素的零头留着，攒够再发
    _pendingDy -= dy;
    if (dx != 0 || dy != 0) {
      _client.send('mouse.move', {'dx': dx, 'dy': dy, 'rel': padGameMode}, true);
    }
  }

  void _onUp(PointerEvent event) {
    final wasTracked = _pointers.remove(event.pointer) != null;
    if (_pointers.isNotEmpty) {
      _anchor = _median();
      return;
    }

    setState(() => _pressed = false);
    if (!wasTracked) return;

    // 轻点：时间短 + 几乎没移动，算一次点击；双指轻点 = 右键
    final elapsed = DateTime.now().difference(_startedAt).inMilliseconds;
    if (elapsed < _tapMs && _travel < _tapSlop) {
      _client.send('mouse.button', {
        'button': _maxFingers >= 2 ? 'right' : 'left',
        'action': 'click',
      }, true);
    }
  }

  void _onCancel(PointerCancelEvent event) {
    _pointers.remove(event.pointer);
    if (_pointers.isEmpty) setState(() => _pressed = false);
  }

  @override
  Widget build(BuildContext context) {
    final tip = widget.tip;

    return ClipRRect(
      borderRadius: BorderRadius.circular(12),
      child: Listener(
        onPointerDown: _onDown,
        onPointerMove: _onMove,
        onPointerUp: _onUp,
        onPointerCancel: _onCancel,
        behavior: HitTestBehavior.opaque,
        child: Stack(
          fit: StackFit.expand,
          children: [
            AnimatedContainer(
              duration: const Duration(milliseconds: 120),
              decoration: BoxDecoration(
                border: Border.all(color: _pressed ? kAccent : kLine),
                borderRadius: BorderRadius.circular(12),
                gradient: LinearGradient(
                  begin: Alignment.topCenter,
                  end: Alignment.bottomCenter,
                  colors: _pressed
                      ? const [Color(0xFF161B26), Color(0xFF11151D)]
                      : const [Color(0xFF14171D), Color(0xFF10131A)],
                ),
              ),
            ),
            if (tip != null)
              Positioned(
                left: 0,
                right: 0,
                bottom: 10,
                child: IgnorePointer(
                  child: Text(
                    tip,
                    textAlign: TextAlign.center,
                    style: const TextStyle(fontSize: 11, color: Color(0xFF5B6472)),
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }
}
