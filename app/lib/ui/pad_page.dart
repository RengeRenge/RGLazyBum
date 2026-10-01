/// 触摸板整页。
///
/// 手势和网页版逐条对齐：
///   单指滑动 → 移动光标（乘灵敏度）
///   轻点     → 左键   双指轻点 → 右键
///   双指上下滑 → 滚轮（往下滑＝往下滚，跟手机上看网页一个方向）
library;

import 'package:flutter/material.dart';

import '../core/client.dart';
import 'common.dart';
import 'theme.dart';

class PadPage extends StatefulWidget {
  const PadPage({super.key});

  @override
  State<PadPage> createState() => _PadPageState();
}

class _PadPageState extends State<PadPage> {
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
  double _sensitivity = 2;

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

    _pendingDx += dx * _sensitivity;
    _pendingDy += dy * _sensitivity;
    _flushMove();
  }

  void _flushMove() {
    final dx = _pendingDx.round();
    final dy = _pendingDy.round();
    _pendingDx -= dx; // 不够一个像素的零头留着，攒够再发
    _pendingDy -= dy;
    if (dx != 0 || dy != 0) {
      _client.send('mouse.move', {'dx': dx, 'dy': dy}, true);
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
    return Scaffold(
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Column(
            children: [
              Row(
                children: [
                  const Expanded(
                    child: Text(
                      '触摸板',
                      style: TextStyle(fontSize: 15, fontWeight: FontWeight.w600),
                    ),
                  ),
                  PillButton(label: '关闭', onTap: () => Navigator.of(context).pop()),
                ],
              ),
              const Gap(10),
              Expanded(child: _pad()),
              const Gap(10),
              Row(
                children: [
                  ActionButton(
                    label: '左键',
                    expand: true,
                    onTap: () => _client.send('mouse.button', {
                      'button': 'left',
                      'action': 'click',
                    }),
                  ),
                  const SizedBox(width: 8),
                  ActionButton(
                    label: '右键',
                    expand: true,
                    onTap: () => _client.send('mouse.button', {
                      'button': 'right',
                      'action': 'click',
                    }),
                  ),
                  const SizedBox(width: 8),
                  ActionButton(
                    label: '中键',
                    expand: true,
                    onTap: () => _client.send('mouse.button', {
                      'button': 'middle',
                      'action': 'click',
                    }),
                  ),
                ],
              ),
              const Gap(10),
              Row(
                children: [
                  const Text('灵敏度', style: TextStyle(fontSize: 12, color: kMuted)),
                  Expanded(
                    child: Slider(
                      value: _sensitivity,
                      min: 0.5,
                      max: 5,
                      divisions: 45,
                      onChanged: (value) => setState(() => _sensitivity = value),
                    ),
                  ),
                  SizedBox(
                    width: 42,
                    child: Text(
                      '${_sensitivity.toStringAsFixed(1)}×',
                      textAlign: TextAlign.right,
                      style: const TextStyle(fontSize: 12, color: kMuted),
                    ),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _pad() {
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
            const Positioned(
              left: 0,
              right: 0,
              bottom: 10,
              child: IgnorePointer(
                child: Text(
                  '单指滑动移动光标 · 轻点＝左键 · 双指轻点＝右键 · 双指上下滑动＝滚轮',
                  textAlign: TextAlign.center,
                  style: TextStyle(fontSize: 11, color: Color(0xFF5B6472)),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
