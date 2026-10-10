/// 触摸板整页。
///
/// 面板本体在 touch_pad.dart —— 键盘页里嵌的那块用的是同一个控件，手势逻辑只有
/// 一份。这一页多出来的是灵敏度、鼠标键和游戏模式开关。
library;

import 'package:flutter/material.dart';

import '../core/client.dart';
import 'common.dart';
import 'theme.dart';
import 'touch_pad.dart';

class PadPage extends StatefulWidget {
  const PadPage({super.key});

  @override
  State<PadPage> createState() => _PadPageState();
}

class _PadPageState extends State<PadPage> {
  final RemoteClient _client = RemoteClient.instance;

  double _sensitivity = 2;

  /// 电脑上前台窗口是不是"管理员进程"（注入会被丢掉）。只在它真变化时重建。
  bool _blocked = false;

  @override
  void initState() {
    super.initState();
    _blocked = _client.inputBlocked;
    _client.addListener(_onClientChanged);
  }

  @override
  void dispose() {
    _client.removeListener(_onClientChanged);
    super.dispose();
  }

  void _onClientChanged() {
    if (mounted && _blocked != _client.inputBlocked) {
      setState(() => _blocked = _client.inputBlocked);
    }
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
              // 前台是管理员进程时，注入会被系统静默丢掉，先说清楚
              if (_blocked) ...[
                const WarningNote(kBlockedHint),
                const Gap(10),
              ],
              Expanded(
                child: TouchPad(
                  sensitivity: _sensitivity,
                  tip: '单指滑动移动光标 · 轻点＝左键 · 双指轻点＝右键 · 双指上下滑动＝滚轮',
                ),
              ),
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
              const Gap(6),
              _gameModeRow(),
            ],
          ),
        ),
      ),
    );
  }

  /// 游戏模式开关。开关是自绘的，跟网页版那个 .toggle 一个样子。
  ///
  /// 值存在 touch_pad.dart 里，键盘页嵌的那块触摸板读的是同一个开关。
  Widget _gameModeRow() {
    return GestureDetector(
      behavior: HitTestBehavior.opaque,
      onTap: () => setState(() => padGameMode = !padGameMode),
      child: Row(
        children: [
          const Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('游戏模式', style: TextStyle(fontSize: 13)),
                SizedBox(height: 2),
                Text(
                  '用相对位移，光标被游戏锁住时也能转视角',
                  style: TextStyle(fontSize: 11, color: kMuted),
                ),
              ],
            ),
          ),
          const SizedBox(width: 10),
          AnimatedContainer(
            duration: const Duration(milliseconds: 150),
            width: 40,
            height: 23,
            decoration: BoxDecoration(
              color: padGameMode ? kAccent.withValues(alpha: .18) : kCard2,
              border: Border.all(color: padGameMode ? kAccent : kLine),
              borderRadius: BorderRadius.circular(999),
            ),
            child: AnimatedAlign(
              duration: const Duration(milliseconds: 150),
              alignment: padGameMode ? Alignment.centerRight : Alignment.centerLeft,
              child: Container(
                margin: const EdgeInsets.symmetric(horizontal: 2),
                width: 17,
                height: 17,
                decoration: BoxDecoration(
                  color: padGameMode ? kAccent : kMuted,
                  shape: BoxShape.circle,
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}
