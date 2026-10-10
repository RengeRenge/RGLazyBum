/// 控制页：连着电脑时显示，网页版那些卡片都在这儿。
library;

import 'dart:async';

import 'package:flutter/material.dart';

import '../core/client.dart';
import 'common.dart';
import 'help_sheet.dart';
import 'keyboard_page.dart';
import 'pad_page.dart';
import 'screen_page.dart';
import 'theme.dart';

/// 功能键面板上的按键：显示文字 + 发给电脑的键名（和电脑端 wininput 对齐）。
const List<(String, String)> _namedKeys = <(String, String)>[
  ('回车', 'enter'),
  ('⌫ 退格', 'backspace'),
  ('空格', 'space'),
  ('Tab', 'tab'),
  ('Esc', 'esc'),
  ('←', 'left'),
  ('↓', 'down'),
  ('↑', 'up'),
  ('→', 'right'),
  ('Home', 'home'),
  ('End', 'end'),
  ('PgUp', 'pageup'),
  ('PgDn', 'pagedown'),
  ('Del', 'delete'),
];

class HomePage extends StatefulWidget {
  const HomePage({super.key});

  @override
  State<HomePage> createState() => _HomePageState();
}

class _HomePageState extends State<HomePage> {
  final RemoteClient _client = RemoteClient.instance;
  final TextEditingController _text = TextEditingController();
  final FocusNode _textFocus = FocusNode();

  /// 正在拖的音量。非空时以手指为准，忽略服务端推来的值，免得滑块被抢回去。
  double? _draggingVolume;
  Timer? _dragTimer;

  @override
  void dispose() {
    _dragTimer?.cancel();
    // 列表还没回来就退出页面了，别把回调留在客户端上
    _client.onWindowList = null;
    _text.dispose();
    _textFocus.dispose();
    super.dispose();
  }

  void _send(String action, [Map<String, Object?>? params]) {
    _client.send(action, params);
  }

  // ---------------------------------------------------------------- 键盘输入

  void _sendText() {
    final text = _text.text;
    if (text.isEmpty) {
      showToast('先输入内容');
      return;
    }
    if (!_client.send('text.send', {'text': text})) return;
    showToast('已发送 ${text.runes.length} 个字符');
  }

  void _clearText() {
    _text.clear();
    _textFocus.requestFocus();
  }

  // -------------------------------------------------------------------- 电源

  Future<void> _power(String action) async {
    if (action == 'sleep' || action == 'hibernate') {
      final label = action == 'sleep' ? '睡眠' : '休眠';
      final ok = await showDialog<bool>(
        context: context,
        builder: (dialogContext) => AlertDialog(
          backgroundColor: kCard,
          title: Text('确定让电脑$label吗？'),
          content: Text('$label后需要用开机卡或电源键唤醒。'),
          actions: [
            TextButton(
              onPressed: () => Navigator.of(dialogContext).pop(false),
              child: const Text('取消', style: TextStyle(color: kMuted)),
            ),
            TextButton(
              onPressed: () => Navigator.of(dialogContext).pop(true),
              child: const Text('确定', style: TextStyle(color: kDanger)),
            ),
          ],
        ),
      );
      if (ok != true) return;
    }
    _send('power.$action');
  }

  // -------------------------------------------------------------------- 菜单

  void _showMenu() {
    showModalBottomSheet<void>(
      context: context,
      backgroundColor: kCard,
      shape: RoundedRectangleBorder(
        borderRadius: const BorderRadius.vertical(top: Radius.circular(16)),
        side: const BorderSide(color: kLine),
      ),
      builder: (sheet) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(18),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const Text(
                '菜单',
                style: TextStyle(fontSize: 16, fontWeight: FontWeight.w600),
              ),
              const Gap(12),
              _MenuItem(
                title: '触摸板',
                desc: '移动光标 · 左中右键 · 调灵敏度',
                onTap: () {
                  Navigator.of(sheet).pop();
                  _openPage(const PadPage());
                },
              ),
              const Gap(8),
              _MenuItem(
                title: '键盘',
                desc: '完整虚拟键盘 · 可以按住不放 · 修饰键锁定',
                onTap: () {
                  Navigator.of(sheet).pop();
                  _openPage(const KeyboardPage());
                },
              ),
              const Gap(8),
              _MenuItem(
                title: '屏幕',
                desc: '看电脑画面 · 多显示器分块',
                onTap: () {
                  Navigator.of(sheet).pop();
                  _openPage(const ScreenPage());
                },
              ),
              const Gap(8),
              _MenuItem(
                title: '使用说明',
                desc: '连接方式 · 外网访问 · 各项功能',
                onTap: () {
                  Navigator.of(sheet).pop();
                  showHelpSheet(context);
                },
              ),
              const Gap(8),
              _MenuItem(
                title: '连接设置',
                desc: '换一台电脑 · 重新扫码',
                onTap: () {
                  Navigator.of(sheet).pop();
                  _client.forget(); // 根节点看到地址被清掉就会回到连接页
                },
              ),
              const Gap(14),
              // 不能用 expand：Expanded 塞进 mainAxisSize.min 的 Column 里会被拉高，
              // 这个"关闭"按钮会变成一整块。Column 已经 stretch，不展开也是满宽。
              ActionButton(
                label: '关闭',
                onTap: () => Navigator.of(sheet).pop(),
              ),
            ],
          ),
        ),
      ),
    );
  }

  void _openPage(Widget page) {
    Navigator.of(context).push(
      MaterialPageRoute<void>(builder: (_) => page, fullscreenDialog: true),
    );
  }

  // -------------------------------------------------------------------- 界面

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: ListenableBuilder(
        listenable: _client,
        builder: (context, _) => Column(
          children: [
            _topBar(context),
            Expanded(
              child: ListView(
                padding: const EdgeInsets.fromLTRB(12, 12, 12, 24),
                children: [
                  _volumeCard(),
                  _mediaCard(),
                  _textCard(),
                  _audioCard(),
                  _windowCard(),
                  _powerCard(),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _topBar(BuildContext context) {
    return Container(
      padding: EdgeInsets.only(
        top: MediaQuery.paddingOf(context).top + 10,
        left: 12,
        right: 12,
        bottom: 10,
      ),
      decoration: const BoxDecoration(
        color: kBg,
        border: Border(bottom: BorderSide(color: kLine)),
      ),
      child: Row(
        children: [
          Expanded(
            child: GestureDetector(
              behavior: HitTestBehavior.opaque,
              onTap: _showMenu,
              child: const Row(
                children: [
                  Text('☰', style: TextStyle(color: kMuted, fontSize: 15)),
                  SizedBox(width: 8),
                  Text(
                    '懒狗',
                    style: TextStyle(fontSize: 16, fontWeight: FontWeight.w700, letterSpacing: .5),
                  ),
                ],
              ),
            ),
          ),
          _StatusPill(state: _client.state, text: _client.statusText),
        ],
      ),
    );
  }

  Widget _volumeCard() {
    final volume = _draggingVolume ?? _client.volume;
    final percent = (volume * 100).round();

    return Panel(
      title: '音量',
      trailing: PillButton(
        label: _client.muted ? '已静音' : '静音',
        active: _client.muted,
        onTap: () => _send('vol.toggle'),
      ),
      children: [
        Row(
          children: [
            IconBox(
              child: const Icon(Icons.remove),
              onTap: () => _send('vol.step', {'delta': -0.05}),
            ),
            Expanded(
              child: Text(
                '$percent%',
                textAlign: TextAlign.center,
                style: TextStyle(
                  fontSize: 30,
                  fontWeight: FontWeight.w700,
                  color: _client.muted ? kDanger : kText,
                ),
              ),
            ),
            IconBox(
              child: const Icon(Icons.add),
              onTap: () => _send('vol.step', {'delta': 0.05}),
            ),
          ],
        ),
        const Gap(4),
        Slider(
          value: percent.clamp(0, 100) / 100,
          onChanged: (value) {
            _dragTimer?.cancel();
            setState(() => _draggingVolume = value);
            _send('vol.set', {'value': value});
            // 松手后 500ms 内不再拖，就把显示权还给服务端
            _dragTimer = Timer(const Duration(milliseconds: 500), () {
              if (mounted) setState(() => _draggingVolume = null);
            });
          },
        ),
      ],
    );
  }

  Widget _mediaCard() {
    return Panel(
      title: '媒体',
      // 电脑上可能同时有好几个播放器，下面这排键只会动"当前会话"，标出来免得按错
      hint: _client.mediaApp.isEmpty ? null : _client.mediaApp,
      children: [
        LayoutBuilder(
          builder: (context, constraints) {
            // 一排五个键，按可用宽度等比缩放：中间的播放键 1.4 份，其余各 1 份。
            // 尺寸写死的话窄屏会横向溢出。
            const gap = 8.0;
            final unit = ((constraints.maxWidth - gap * 4) / 5.4).clamp(28.0, 68.0);
            final big = unit * 1.4;

            return Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                IconBox(
                  size: unit,
                  radius: unit * .25,
                  // 播放器没实现跳转（网易云音乐）时这两个键是灰的
                  disabled: !_client.mediaCanSeek,
                  onTap: () => _send('media.seek', {'delta': -10}),
                  child: const Icon(Icons.fast_rewind),
                ),
                const SizedBox(width: gap),
                IconBox(
                  size: unit,
                  radius: unit * .25,
                  // Edge 放单个视频时无处可切，这两个键跟着当前会话的能力灰掉
                  disabled: !_client.mediaCanPrev,
                  onTap: () => _send('media.prev'),
                  child: const Icon(Icons.skip_previous),
                ),
                const SizedBox(width: gap),
                IconBox(
                  size: big,
                  radius: big * .26,
                  primary: true,
                  onTap: () => _send('media.playpause'),
                  // 图标跟着电脑上真实的播放状态走（在电脑上手动暂停也会变）
                  child: Icon(_client.mediaPlaying ? Icons.pause : Icons.play_arrow),
                ),
                const SizedBox(width: gap),
                IconBox(
                  size: unit,
                  radius: unit * .25,
                  disabled: !_client.mediaCanNext,
                  onTap: () => _send('media.next'),
                  child: const Icon(Icons.skip_next),
                ),
                const SizedBox(width: gap),
                IconBox(
                  size: unit,
                  radius: unit * .25,
                  disabled: !_client.mediaCanSeek,
                  onTap: () => _send('media.seek', {'delta': 10}),
                  child: const Icon(Icons.fast_forward),
                ),
              ],
            );
          },
        ),
      ],
    );
  }

  Widget _audioCard() {
    final devices = _client.devices;

    return Panel(
      title: '音频输出',
      trailing: PillButton(label: '刷新', onTap: () => _send('audio.refresh')),
      children: [
        if (devices.isEmpty)
          const Text('没有找到可用的输出设备', style: TextStyle(fontSize: 13, color: kMuted)),
        for (final device in devices) ...[
          TapBox(
            onTap: device.id == _client.deviceId
                ? null
                : () => _send('audio.set', {'id': device.id}),
            padding: const EdgeInsets.all(12),
            color: device.id == _client.deviceId
                ? kAccent.withValues(alpha: .12)
                : kCard2,
            borderColor: device.id == _client.deviceId ? kAccent : kLine,
            child: Row(
              children: [
                _Dot(active: device.id == _client.deviceId),
                const SizedBox(width: 10),
                Expanded(
                  child: Text(
                    device.name,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(fontSize: 14),
                  ),
                ),
              ],
            ),
          ),
          const Gap(8),
        ],
      ],
    );
  }

  Widget _textCard() {
    return Panel(
      title: '键盘输入',
      hint: '输入到电脑当前焦点窗口',
      children: [
        TextField(
          controller: _text,
          focusNode: _textFocus,
          minLines: 3,
          maxLines: 5,
          autocorrect: false,
          enableSuggestions: false,
          style: const TextStyle(fontSize: 16),
          // 关键：点下面的按键、点发送时不要把输入焦点丢掉。
          // 默认行为是"点到输入框外面就收起键盘"，连着按几下简直没法用。
          onTapOutside: (_) {},
          decoration: InputDecoration(
            hintText: '在这里打字，然后点发送…',
            hintStyle: const TextStyle(color: kMuted, fontSize: 14),
            filled: true,
            fillColor: kCard2,
            contentPadding: const EdgeInsets.all(12),
            border: OutlineInputBorder(
              borderRadius: BorderRadius.circular(10),
              borderSide: const BorderSide(color: kLine),
            ),
            enabledBorder: OutlineInputBorder(
              borderRadius: BorderRadius.circular(10),
              borderSide: const BorderSide(color: kLine),
            ),
            focusedBorder: OutlineInputBorder(
              borderRadius: BorderRadius.circular(10),
              borderSide: const BorderSide(color: kAccent),
            ),
          ),
        ),
        const Gap(10),
        LayoutBuilder(
          builder: (context, constraints) {
            // 一行四个，宽度按可用空间算，小屏大屏都不挤
            const gap = 6.0;
            final width = (constraints.maxWidth - gap * 3) / 4;
            return Wrap(
              spacing: gap,
              runSpacing: gap,
              children: [
                for (final key in _namedKeys)
                  SizedBox(
                    width: width,
                    child: KeyChip(
                      label: key.$1,
                      onTap: () => _send('key.press', {'key': key.$2}),
                    ),
                  ),
              ],
            );
          },
        ),
        const Gap(10),
        Row(
          children: [
            ActionButton(label: '发送', primary: true, expand: true, onTap: _sendText),
            const SizedBox(width: 8),
            ActionButton(label: '清空', expand: true, onTap: _clearText),
          ],
        ),
      ],
    );
  }

  Widget _windowCard() {
    return Panel(
      title: '窗口',
      // 右边显示电脑当前前台窗口的标题（没窗口在前台时是「桌面」），点一下
      // 弹出所有可切换窗口的列表。
      hint: _client.windowTitle.isEmpty ? null : _client.windowTitle,
      hintOnTap: _pickWindow,
      // 标题同一行右侧那三个键，照着 Windows 标题栏右边三个键做的，
      // 作用对象都是电脑上当前前台窗口
      trailing: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          IconBox(
            size: 32,
            radius: 10,
            onTap: () => _send('window.minimize'),
            child: const Icon(Icons.remove),
          ),
          const SizedBox(width: 4),
          IconBox(
            size: 32,
            radius: 10,
            onTap: () => _send('window.maximize'),
            child: Icon(_client.windowMaximized ? Icons.filter_none : Icons.crop_square),
          ),
          const SizedBox(width: 4),
          IconBox(
            size: 32,
            radius: 10,
            onTap: _closeWindow,
            child: const Icon(Icons.close, color: kDanger),
          ),
        ],
      ),
      children: [
        Row(
          children: [
            ActionButton(
              label: '← 移到左屏',
              expand: true,
              onTap: () => _send('window.move', {'direction': 'left'}),
            ),
            const SizedBox(width: 8),
            ActionButton(
              label: '移到右屏 →',
              expand: true,
              onTap: () => _send('window.move', {'direction': 'right'}),
            ),
          ],
        ),
      ],
    );
  }

  /// 关电脑上那个窗口。跟点标题栏的 ✕ 一样会丢没保存的东西，先问一句；
  /// 该不该保存还是由那个程序自己弹（电脑端发的是 WM_CLOSE）。
  Future<void> _closeWindow() async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        backgroundColor: kCard,
        title: const Text('确定关闭电脑上这个窗口吗？'),
        content: const Text('没保存的内容会按那个程序自己的提示处理。'),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(dialogContext).pop(false),
            child: const Text('取消', style: TextStyle(color: kMuted)),
          ),
          TextButton(
            onPressed: () => Navigator.of(dialogContext).pop(true),
            child: const Text('确定', style: TextStyle(color: kDanger)),
          ),
        ],
      ),
    );
    if (ok == true) _send('window.close');
  }

  // ------------------------------------------------------------------ 切窗口

  /// 点「窗口」卡片右上角的标题：向电脑要一份窗口列表。
  /// 列表是异步推回来的，所以先挂上回调，收到之后再弹面板。
  void _pickWindow() {
    if (!_client.send('window.list')) return;
    _client.onWindowList = _showWindowSheet;
  }

  void _showWindowSheet(List<WindowInfo> windows) {
    _client.onWindowList = null;
    if (!mounted) return;
    showModalBottomSheet<void>(
      context: context,
      backgroundColor: kCard,
      shape: RoundedRectangleBorder(
        borderRadius: const BorderRadius.vertical(top: Radius.circular(16)),
        side: const BorderSide(color: kLine),
      ),
      builder: (sheet) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            const Padding(
              padding: EdgeInsets.fromLTRB(18, 16, 18, 10),
              child: Text(
                '切换窗口',
                style: TextStyle(fontSize: 14, fontWeight: FontWeight.w600, color: kMuted),
              ),
            ),
            Flexible(
              child: ListView.builder(
                shrinkWrap: true,
                padding: const EdgeInsets.fromLTRB(10, 0, 10, 16),
                itemCount: windows.length,
                itemBuilder: (context, i) {
                  final win = windows[i];
                  return Padding(
                    padding: const EdgeInsets.only(bottom: 6),
                    child: TapBox(
                      alignment: Alignment.centerLeft,
                      onTap: () {
                        _client.send('window.activate', {'id': win.id});
                        Navigator.of(sheet).pop();
                      },
                      child: Row(
                        children: [
                          // 当前前台窗口的圆点用高亮色，一眼看出自己在哪一行
                          Container(
                            width: 7,
                            height: 7,
                            decoration: BoxDecoration(
                              shape: BoxShape.circle,
                              color: win.current ? kAccent : kLine,
                            ),
                          ),
                          const SizedBox(width: 10),
                          Expanded(
                            child: Text(
                              win.title,
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                              style: TextStyle(
                                fontSize: 14,
                                color: win.current ? kAccent : kText,
                              ),
                            ),
                          ),
                          if (win.current)
                            const Text('当前', style: TextStyle(fontSize: 11, color: kMuted)),
                        ],
                      ),
                    ),
                  );
                },
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _powerCard() {
    return Panel(
      title: '电源',
      children: [
        Row(
          children: [
            ActionButton(
              label: '关闭显示器',
              expand: true,
              onTap: () => _send('power.monitor_off'),
            ),
            const SizedBox(width: 8),
            ActionButton(
              label: '唤醒屏幕',
              expand: true,
              onTap: () => _send('power.wake'),
            ),
          ],
        ),
        const Gap(8),
        Row(
          children: [
            ActionButton(label: '锁定', expand: true, onTap: () => _power('lock')),
            const SizedBox(width: 8),
            ActionButton(label: '睡眠', expand: true, onTap: () => _power('sleep')),
            const SizedBox(width: 8),
            ActionButton(
              label: '休眠',
              expand: true,
              danger: true,
              onTap: () => _power('hibernate'),
            ),
          ],
        ),
      ],
    );
  }
}

class _StatusPill extends StatelessWidget {
  const _StatusPill({required this.state, required this.text});

  final LinkState state;
  final String text;

  @override
  Widget build(BuildContext context) {
    final color = switch (state) {
      LinkState.online => kOk,
      LinkState.connecting => kMuted,
      LinkState.idle => kDanger,
    };

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
      decoration: BoxDecoration(
        color: kCard2,
        borderRadius: BorderRadius.circular(999),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
            width: 7,
            height: 7,
            decoration: BoxDecoration(color: color, shape: BoxShape.circle),
          ),
          const SizedBox(width: 6),
          Text(text, style: TextStyle(fontSize: 12, color: color)),
        ],
      ),
    );
  }
}

class _Dot extends StatelessWidget {
  const _Dot({required this.active});

  final bool active;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: 8,
      height: 8,
      decoration: BoxDecoration(
        color: active ? kAccent : kLine,
        shape: BoxShape.circle,
      ),
    );
  }
}

class _MenuItem extends StatelessWidget {
  const _MenuItem({required this.title, required this.desc, required this.onTap});

  final String title;
  final String desc;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return TapBox(
      onTap: onTap,
      radius: 12,
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      // TapBox 默认把内容居中，两行文字会缩成一块贴在中间，得靠左
      alignment: Alignment.centerLeft,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(title, style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w600)),
          const SizedBox(height: 2),
          Text(desc, style: const TextStyle(fontSize: 12, color: kMuted)),
        ],
      ),
    );
  }
}
