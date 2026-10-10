/// 虚拟键盘整页。
///
/// 键位分三个标签：主键区（字母数字符号）、功能键（F1-F12、方向键等）、小键盘。
/// 行为上和网页版一致：
///
///   普通键 —— 手指按住＝按下不放，松开手指＝弹起。这样游戏里能按住 W 一直
///             往前走，而不是走一下就停。
///   修饰键 —— Ctrl / Shift / Alt / Win 点一下锁定（等于一直按着），再点一下
///             解锁。要按 Ctrl+C 这类组合键，单指按着两个键太难了。
///
/// 单独发"按下"/"弹起"而不是按一下就完，代价是按键状态留在了电脑上 ——
/// 所以退出这一页时必须补一条"全部松开"，否则修饰键会卡住。
library;

import 'package:flutter/material.dart';

import '../core/client.dart';
import 'common.dart';
import 'theme.dart';
import 'touch_pad.dart';

/// 一个键：[键名, 键帽文字, 宽度权重]。键名要和电脑端 wininput._NAMED_KEYS 对齐。
typedef _KeySpec = ({String name, String label, double weight});

/// 这四把是"点一下锁定"的修饰键，其余键都是按住生效
const Set<String> _mods = <String>{'ctrl', 'shift', 'alt', 'win'};

/// 把布局表里混排的"简写 / 完整写法"统一成 _KeySpec。
/// 元素是 String 就按普通键处理（键名即键帽、占 1 份宽），
/// 是 (键名, 键帽, 权重) 这种位置记录就补上字段名，是 null 就表示空位。
///
/// 权重按 num 收，不按 double —— 布局表里为了少打字会直接写 `1`，
/// 那是 int，用 double 去 as 会在运行时炸掉。
_KeySpec? _spec(Object? raw) {
  if (raw == null) return null;
  if (raw is String) return (name: raw, label: raw, weight: 1.0);
  if (raw is (String, String, num)) {
    final (name, label, weight) = raw;
    return (name: name, label: label, weight: weight.toDouble());
  }
  throw ArgumentError('键盘布局表里有不认识的元素：$raw');
}

List<_KeySpec?> _row(List<Object?> raw) => raw.map(_spec).toList();

/// 键帽的"上档字符"：Shift 锁定着的时候，这些键显示的是它真正会打出来的那个
/// 符号。字母不在这里 —— 上档是大写，但把一堆字母全变成大写反而更难看，就没做。
const Map<String, String> _shiftedLabels = <String, String>{
  '1': '!',
  '2': '@',
  '3': '#',
  '4': r'$',
  '5': '%',
  '6': '^',
  '7': '&',
  '8': '*',
  '9': '(',
  '0': ')',
  '-': '_',
  '=': '+',
  '`': '~',
  '[': '{',
  ']': '}',
  r'\': '|',
  ';': ':',
  "'": '"',
  ',': '<',
  '.': '>',
  '/': '?',
};

/// 主键区。权重决定键的宽窄，照着真实键盘：Backspace / Shift / 空格 要更宽。
final List<List<Object?>> _mainLayout = <List<Object?>>[
  <Object?>[
    ('esc', 'Esc', 1.3), ('grave', '`', 1), '1', '2', '3', '4', '5', '6',
    '7', '8', '9', '0', ('minus', '-', 1), ('equal', '=', 1),
    ('backspace', '⌫', 2),
  ],
  <Object?>[
    ('tab', 'Tab', 1.5), 'q', 'w', 'e', 'r', 't', 'y', 'u', 'i', 'o', 'p',
    ('lbracket', '[', 1), ('rbracket', ']', 1), ('backslash', r'\', 1.5),
  ],
  <Object?>[
    ('capslock', 'Caps', 1.8), 'a', 's', 'd', 'f', 'g', 'h', 'j', 'k', 'l',
    ('semicolon', ';', 1), ('quote', "'", 1), ('enter', 'Enter', 2.2),
  ],
  <Object?>[
    ('shift', 'Shift', 2.3), 'z', 'x', 'c', 'v', 'b', 'n', 'm',
    ('comma', ',', 1), ('period', '.', 1), ('slash', '/', 1.3),
  ],
  <Object?>[
    ('ctrl', 'Ctrl', 1.3), ('win', 'Win', 1.2), ('alt', 'Alt', 1.2),
    ('space', '空格', 6),
  ],
];

/// 功能键。F1-F12 按每行四个生成，省得手写十二遍。
final List<List<Object?>> _funcLayout = <List<Object?>>[
  for (var i = 1; i <= 12; i += 4)
    <Object?>[for (var n = i; n < i + 4; n++) ('f$n', 'F$n', 1)],
  <Object?>[
    ('esc', 'Esc', 1), ('printscreen', 'PrtSc', 1),
    ('scrolllock', 'ScrLk', 1), ('pause', 'Pause', 1),
  ],
  // 导航键簇右边那格本来就是空的，跟真键盘一样
  <Object?>[
    ('insert', 'Ins', 1), ('home', 'Home', 1), ('pageup', 'PgUp', 1), null,
  ],
  <Object?>[
    ('delete', 'Del', 1), ('end', 'End', 1), ('pagedown', 'PgDn', 1), null,
  ],
  <Object?>[
    ('left', '←', 1), ('up', '↑', 1), ('down', '↓', 1), ('right', '→', 1),
  ],
];

/// 小键盘。最后一行只有一个 0，它会自然占满整行。
final List<List<Object?>> _numpadLayout = <List<Object?>>[
  <Object?>[
    ('numlock', 'NumLock', 1), ('numdiv', '÷', 1),
    ('nummul', '×', 1), ('numsub', '−', 1),
  ],
  <Object?>[('num7', '7', 1), ('num8', '8', 1), ('num9', '9', 1), ('numadd', '+', 1)],
  <Object?>[('num4', '4', 1), ('num5', '5', 1), ('num6', '6', 1), ('numenter', 'Enter', 1)],
  <Object?>[('num1', '1', 1), ('num2', '2', 1), ('num3', '3', 1), ('numdot', '.', 1)],
  <Object?>[('num0', '0', 1)],
];

class KeyboardPage extends StatefulWidget {
  const KeyboardPage({super.key});

  @override
  State<KeyboardPage> createState() => _KeyboardPageState();
}

class _KeyboardPageState extends State<KeyboardPage> {
  final RemoteClient _client = RemoteClient.instance;

  String _tab = 'main';

  /// 锁定中的修饰键
  final Set<String> _latched = <String>{};

  /// 各手指正按着的普通键：pointer -> 键名
  final Map<int, String> _held = <int, String>{};

  /// 电脑上前台窗口是不是"管理员进程"（注入会被丢掉）。只在它真变化时重建。
  bool _blocked = false;

  /// 触摸板有没有被叫出来 —— 页面标题栏那个「触摸板」按钮控制。默认就是打开的，
  /// 这一页本来就是"键盘 + 触摸板"一起用的。
  bool _showPad = true;

  /// 触摸板排在前面吗（上下布局＝在上面，左右布局＝在左边）。点中间那根横杆
  /// 切换；存成 static，来回进出这一页不用重摆一次。
  static bool _padFirst = false;

  /// 上下排至少要这么高（逻辑像素）。低于它就改成左右排 —— 上下排时键盘占
  /// 3/5，五行的主键区每行还能剩 40 上下，按键才按得住。
  static const double _stackMinHeight = 380;

  /// 横杆本体 8px，外面留一圈好按的判定区，总高/总宽就是这个数
  static const double _handleTouch = 26;

  /// 面板之间、以及键盘行与行之间的缝
  static const double _gap = 6;

  /// 单行键最高多少。主键区一行 15 个键、每个才 18 上下宽，不封顶的话在竖屏上
  /// 会被拉成细高条，高宽比很难看。
  static const double _maxRowHeight = 44;

  /// 换边 / 让位时滑过去的时长
  static const Duration _flipDuration = Duration(milliseconds: 240);

  /// 鼠标往哪边挪才叫"往对面拖"。布局时记下来，拖动回调里要用
  bool _layoutVertical = true;

  /// 触摸板的手动大小（逻辑像素，只算主方向）。上下排记的是高度、左右排记的是
  /// 宽度，两维各记各的 —— 换个方向再换回来，还回到之前那个大小。
  /// 0 = 这一维还没手动调过，用自动值。
  static double _padSizeVertical = 0;
  static double _padSizeHorizontal = 0;

  /// 拖动时把触摸板/键盘限制在这个范围里，免得拖成一条缝或者把键盘挤没
  static const double _padMinSize = 120;
  static const double _keyboardMinSize = 140;

  bool _dragging = false;

  /// 这几个是布局时顺手记下来的，拖动的时候要用（拖动回调里拿不到约束）
  double _layoutRest = 0;
  double _autoPadSize = 0;

  double get _padManualSize =>
      _layoutVertical ? _padSizeVertical : _padSizeHorizontal;

  void _setPadManualSize(double value) {
    if (_layoutVertical) {
      _padSizeVertical = value;
    } else {
      _padSizeHorizontal = value;
    }
  }

  @override
  void initState() {
    super.initState();
    _blocked = _client.inputBlocked;
    _client.addListener(_onClientChanged);
  }

  void _onClientChanged() {
    if (mounted && _blocked != _client.inputBlocked) {
      setState(() => _blocked = _client.inputBlocked);
    }
  }

  @override
  void dispose() {
    _client.removeListener(_onClientChanged);
    // 退出这一页等于"手全松开了"。不补这一下的话，锁定中的 Ctrl 会一直卡在
    // 电脑上 —— 之后在电脑上敲的每个键都会变成组合键。
    if (_latched.isNotEmpty || _held.isNotEmpty) {
      _client.send('key.release_all', null, true);
    }
    super.dispose();
  }

  void _releaseAll() {
    _latched.clear();
    _held.clear();
    setState(() {});
    _client.send('key.release_all', null, true);
  }

  void _onKeyDown(String name, int pointer) {
    if (_mods.contains(name)) {
      // 修饰键：点一下锁定（等于一直按着），再点一下解锁
      final wasLatched = _latched.contains(name);
      setState(() {
        if (wasLatched) {
          _latched.remove(name);
        } else {
          _latched.add(name);
        }
      });
      _client.send(wasLatched ? 'key.up' : 'key.down', {'key': name}, true);
      return;
    }
    setState(() => _held[pointer] = name);
    _client.send('key.down', {'key': name}, true);
  }

  void _onKeyUp(int pointer) {
    final name = _held.remove(pointer);
    if (name == null) return;
    setState(() {});
    _client.send('key.up', {'key': name}, true);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Column(
            children: [
              _header(),
              const Gap(10),
              // 前台是管理员进程时，注入会被系统静默丢掉，先说清楚
              if (_blocked) ...[
                const WarningNote(kBlockedHint),
                const Gap(10),
              ],
              _tabs(),
              const Gap(8),
              Expanded(child: _split()),
              // 触摸板出来之后底下就没地方了，这行说明收起来
              if (!_showPad) ...[
                const Gap(6),
                const Text(
                  '按住＝按下不放（按住 W 就能一直往前走）\n'
                  'Ctrl / Shift / Alt / Win 点一下锁定，再点一下解锁',
                  textAlign: TextAlign.center,
                  style: TextStyle(fontSize: 11, color: kMuted),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }

  /// 键盘 +（叫出来之后）触摸板。
  ///
  /// 竖着放得下（这块地方够高）就上下排，放不下（矮屏 / 横屏）就左右排；触摸板
  /// 在哪一侧由中间那根小横杆拖出来。
  ///
  /// 两块面板的尺寸是算出来再用 AnimatedPositioned 摆的，不是靠 flex —— flex 的
  /// order 没法过渡，换边就成了"啪一下跳过去"。自己算位置才能让它滑过去。
  Widget _split() {
    // 没叫触摸板的时候整页高度本来都给键盘，五行的键会被拉成细高条，所以同样
    // 要封顶；多出来的地方空着，键盘贴着底边放。
    if (!_showPad) {
      return LayoutBuilder(
        builder: (context, constraints) {
          final natural = _keyboardNaturalHeight;
          return Align(
            alignment: Alignment.bottomCenter,
            child: SizedBox(
              width: double.infinity,
              height: natural < constraints.maxHeight
                  ? natural
                  : constraints.maxHeight,
              child: _keyboard(),
            ),
          );
        },
      );
    }

    return LayoutBuilder(
      builder: (context, constraints) {
        // 看的是"这块地方能分到多高"，不是整块屏幕的高度
        final vertical = constraints.maxHeight >= _stackMinHeight;
        final span = vertical ? constraints.maxHeight : constraints.maxWidth;
        // 横杆和它两侧的缝先扣掉，剩下的才分给两块面板
        final rest = (span - _handleTouch - _gap * 2).clamp(0.0, double.infinity);
        // 自动摆法：键盘先拿 min(3/5, 它需要的自然高度)，剩下的全给触摸板 ——
        // 这样刚叫出来的时候键不会很长、也没有空白
        final natural = _keyboardNaturalHeight;
        final autoPad = vertical
            ? rest - (natural < rest * 0.6 ? natural : rest * 0.6)
            : rest * 0.5;
        final maxPad = (rest - _keyboardMinSize).clamp(_padMinSize, rest);
        // 拖动回调里拿不到约束，这几个先记下来
        _layoutRest = rest;
        _autoPadSize = autoPad;
        // 按"这一轮的方向"直接取对应那一维，不要读 _layoutVertical —— 触摸板
        // 隐藏时它还是上一次的值，会把另一维的值读过来
        final manual = vertical ? _padSizeVertical : _padSizeHorizontal;
        final padSize = (manual > 0 ? manual : autoPad).clamp(_padMinSize, maxPad);
        final keyboardSize = rest - padSize;
        // 拖动改尺寸时要知道改哪一维
        _layoutVertical = vertical;

        // 拖动改的是尺寸，不能走缓动，否则黏手；只有换边才交给动画
        final duration = _dragging ? Duration.zero : _flipDuration;

        Widget place({
          required double start,
          required double size,
          required Widget child,
        }) {
          return AnimatedPositioned(
            duration: duration,
            curve: Curves.easeOutCubic,
            left: vertical ? 0 : start,
            top: vertical ? start : 0,
            width: vertical ? constraints.maxWidth : size,
            height: vertical ? size : constraints.maxHeight,
            child: child,
          );
        }

        return Stack(
          fit: StackFit.expand,
          children: [
            // 键盘压在下面、触摸板在上面：换边时触摸板从键盘上方滑过去，
            // 看着才像"挪过去了"而不是闪现
            place(
              start: _padFirst ? padSize + _handleTouch + _gap * 2 : 0,
              size: keyboardSize,
              child: _keyboard(),
            ),
            place(
              start: _padFirst ? 0 : keyboardSize + _handleTouch + _gap * 2,
              size: padSize,
              child: const TouchPad(),
            ),
            place(
              start: (_padFirst ? padSize : keyboardSize) + _gap,
              size: _handleTouch,
              child: _dragHandle(vertical),
            ),
          ],
        );
      },
    );
  }

  /// 键盘按"每行最多 _maxRowHeight"算出来的自然高度
  double get _keyboardNaturalHeight {
    final rowCount = switch (_tab) {
      'func' => _funcLayout.length,
      'numpad' => _numpadLayout.length,
      _ => _mainLayout.length,
    };
    return rowCount * _maxRowHeight + (rowCount - 1) * _gap;
  }

  /// 两根面板之间那根小横杆：点一下把触摸板换到对面（上↔下 / 左↔右）；
  /// 按住拖是改触摸板的大小 —— 上下排改它的高度，左右排改它的宽度。
  Widget _dragHandle(bool vertical) {
    final bar = Container(
      width: vertical ? 64 : 8,
      height: vertical ? 8 : 64,
      decoration: BoxDecoration(
        color: _dragging ? kAccent : kMuted,
        borderRadius: BorderRadius.circular(999),
      ),
    );

    return GestureDetector(
      behavior: HitTestBehavior.opaque,
      // 点一下 = 直接换到对面；拖 = 改触摸板的大小
      onTap: () => setState(() => _padFirst = !_padFirst),
      onVerticalDragStart: vertical ? (_) => _beginDrag() : null,
      onVerticalDragUpdate: vertical ? (d) => _dragUpdate(d.delta.dy) : null,
      onVerticalDragEnd: vertical ? (_) => _endDrag() : null,
      onHorizontalDragStart: vertical ? null : (_) => _beginDrag(),
      onHorizontalDragUpdate: vertical ? null : (d) => _dragUpdate(d.delta.dx),
      onHorizontalDragEnd: vertical ? null : (_) => _endDrag(),
      child: Center(child: bar),
    );
  }

  void _beginDrag() => setState(() {
        _dragging = true;
        // 从当前大小接着拖：这一维还没手动调过的话，先把自动值固化下来
        if (_padManualSize <= 0) _setPadManualSize(_autoPadSize);
      });

  /// 拖动改的是触摸板的主方向尺寸（上下排是高度、左右排是宽度）。
  /// 触摸板排在后面时，往下拖＝把它挤小（键盘变大）；排在前面时反过来。
  void _dragUpdate(double delta) {
    setState(() {
      final next = _padManualSize + (_padFirst ? delta : -delta);
      final maxPad =
          (_layoutRest - _keyboardMinSize).clamp(_padMinSize, _layoutRest);
      _setPadManualSize(next.clamp(_padMinSize, maxPad));
    });
  }

  void _endDrag() => setState(() => _dragging = false);

  Widget _header() {
    return Row(
      children: [
        const Expanded(
          child: Text(
            '键盘',
            style: TextStyle(fontSize: 15, fontWeight: FontWeight.w600),
          ),
        ),
        // 触摸板的开关放这儿 —— 搁在页面底下会白白占掉一整行按键的高度
        PillButton(
          label: '触摸板',
          active: _showPad,
          onTap: () => setState(() => _showPad = !_showPad),
        ),
        const SizedBox(width: 8),
        PillButton(label: '全部松开', onTap: _releaseAll),
        const SizedBox(width: 8),
        PillButton(label: '关闭', onTap: () => Navigator.of(context).pop()),
      ],
    );
  }

  Widget _tabs() {
    const tabs = <(String, String)>[
      ('main', '主键区'),
      ('func', '功能键'),
      ('numpad', '小键盘'),
    ];
    return Row(
      children: [
        for (final (id, label) in tabs) ...[
          Expanded(
            child: TapBox(
              onTap: () => setState(() => _tab = id),
              color: _tab == id ? kCard2 : kCard,
              borderColor: _tab == id ? kAccent : kLine,
              padding: const EdgeInsets.symmetric(vertical: 8),
              child: Text(
                label,
                style: TextStyle(
                  fontSize: 13,
                  color: _tab == id ? kAccent : kMuted,
                ),
              ),
            ),
          ),
          if (id != 'numpad') const SizedBox(width: 6),
        ],
      ],
    );
  }

  Widget _keyboard() {
    final rows = (switch (_tab) {
      'func' => _funcLayout,
      'numpad' => _numpadLayout,
      _ => _mainLayout,
    }).map(_row).toList();

    // 锁定的修饰键 + 手指正按着的普通键，都要点亮
    final down = <String>{..._latched, ..._held.values};
    // Shift 锁定着的话，键帽要换成上档字符
    final shiftOn = _latched.contains('shift');

    return Column(
      children: [
        for (var r = 0; r < rows.length; r++) ...[
          Expanded(
            child: Row(
              children: [
                for (var c = 0; c < rows[r].length; c++) ...[
                  Expanded(
                    // 权重乘 100 换成 flex 的整数份数；空位也占同样一格
                    flex: ((rows[r][c]?.weight ?? 1) * 100).round(),
                    child: _keySlot(rows[r][c], down, shiftOn),
                  ),
                  if (c != rows[r].length - 1) const SizedBox(width: _gap),
                ],
              ],
            ),
          ),
          // 行间距要和 _keyboardNaturalHeight 里算的一致，不然限高会算歪
          if (r != rows.length - 1) const SizedBox(height: _gap),
        ],
      ],
    );
  }

  /// 空位只占宽度，不画键（导航键簇右侧那格本来就是空的）
  Widget _keySlot(_KeySpec? spec, Set<String> down, bool shiftOn) => spec == null
      ? const SizedBox()
      : _key(spec, down.contains(spec.name), shiftOn);

  Widget _key(_KeySpec spec, bool lit, bool shiftOn) {
    final isMod = _mods.contains(spec.name);
    // Shift 锁着的时候显示它真正会打出来的那个上档字符（1 → !、` → ~ ……）
    final label = shiftOn ? (_shiftedLabels[spec.label] ?? spec.label) : spec.label;

    return Listener(
      behavior: HitTestBehavior.opaque,
      onPointerDown: (ev) => _onKeyDown(spec.name, ev.pointer),
      onPointerUp: (ev) => _onKeyUp(ev.pointer),
      onPointerCancel: (ev) => _onKeyUp(ev.pointer),
      child: Container(
        decoration: BoxDecoration(
          color: lit ? kAccent.withValues(alpha: .16) : kCard2,
          border: Border.all(color: lit ? kAccent : kLine),
          borderRadius: BorderRadius.circular(9),
        ),
        alignment: Alignment.center,
        padding: const EdgeInsets.symmetric(horizontal: 2),
        // 窄屏上 "NumLock" / "Enter" 这类长文字放不下，等比缩一点而不是溢出
        child: FittedBox(
          fit: BoxFit.scaleDown,
          child: Text(
            label,
            maxLines: 1,
            style: TextStyle(
              fontSize: isMod ? 12 : 13,
              color: lit ? kAccent : (isMod ? kMuted : kText),
            ),
          ),
        ),
      ),
    );
  }
}
