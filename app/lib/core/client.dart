/// 和电脑端的长连接，以及电脑端的音频状态。
///
/// 协议（和 web/app.js 完全一致）：
///   发：{"a": 动作名, "p": {参数}}
///   收：{"t":"state","d":{...}} / {"t":"err","msg":...} / {"t":"notice","msg":...}
/// 连上就会先收到一条 state（音频快照），之后电脑每秒对一次状态，有变化才推。
library;

import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'endpoint.dart';

enum LinkState { idle, connecting, online }

class AudioDevice {
  const AudioDevice({required this.id, required this.name});

  final String id;
  final String name;
}

/// 电脑上一个能切过去的窗口。[id] 是电脑那边的窗口句柄，
/// 0 是特例——代表桌面（点它把所有窗口最小化）。
class WindowInfo {
  const WindowInfo({required this.id, required this.title, required this.current});

  final int id;
  final String title;

  /// 是不是电脑当前的前台窗口。服务端下发，不要拿标题去比：
  /// 列表里的标题截到 120 字符，而每秒推的 focus 截到 200，长标题对不上。
  final bool current;
}

class RemoteClient extends ChangeNotifier {
  RemoteClient._();

  static final RemoteClient instance = RemoteClient._();

  static const String _prefsKey = 'endpoint';
  static const String _addressKey = 'address';

  Endpoint? _endpoint;
  LinkState _state = LinkState.idle;
  WebSocket? _socket;
  Timer? _retry;
  int _retryDelay = 400;

  double volume = 0;
  bool muted = false;
  List<AudioDevice> devices = const [];
  String deviceId = '';

  /// 电脑上是否有媒体正在播放。没有媒体会话时也是 false，界面就显示"播放"。
  bool mediaPlaying = false;

  /// 电脑上正在被控制的播放器名字（Edge / 网易云音乐…）。
  /// 电脑上可能同时有好几个播放器在放，按钮只会动"当前会话"这一个，所以把它显示出来。
  /// 没有媒体会话时是空串。
  String mediaApp = '';

  /// 电脑上当前前台窗口的标题，显示在「窗口」卡片右上角。读不到时是空串。
  String windowTitle = '';

  /// 前台窗口是不是最大化状态 —— 标题栏中间那个键要在「最大化」和「还原」
  /// 两个图标之间切，靠它决定画哪个。
  bool windowMaximized = false;

  /// 当前这条媒体会话支不支持快进/快退。网易云音乐这类只做了播放/暂停/切歌的
  /// 播放器会报 false，界面就把那两个键灰掉——位置请求它们收下却不动，
  /// 光看返回值分辨不出来。
  bool mediaCanSeek = false;

  /// 当前这条会话支不支持切上一首/下一首。Edge 里放单个视频时就无处可切，
  /// 界面把对应的键灰掉。
  bool mediaCanPrev = false;
  bool mediaCanNext = false;

  /// 由界面注入：把服务端发来的错误 / 提示显示成浮层。
  void Function(String message, {bool error})? onToast;

  /// 由界面注入：点了「窗口」卡片右上角的标题之后，服务端会把窗口列表推回来，
  /// 界面拿它弹选择面板。列表是异步回来的，所以走回调而不是返回值。
  void Function(List<WindowInfo> windows)? onWindowList;

  Endpoint? get endpoint => _endpoint;
  LinkState get state => _state;
  bool get online => _state == LinkState.online;

  String get statusText => switch (_state) {
    LinkState.online => '已连接',
    LinkState.connecting => '连接中…',
    LinkState.idle => '已断开，重连中…',
  };

  // ------------------------------------------------------------ 地址记忆

  Future<Endpoint?> restoreEndpoint() async {
    final prefs = await SharedPreferences.getInstance();
    return Endpoint.decode(prefs.getString(_prefsKey));
  }

  Future<void> rememberEndpoint(Endpoint endpoint) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_prefsKey, endpoint.encode());
  }

  Future<void> forgetEndpoint() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_prefsKey);
  }

  /// 上次连成功时手填（或扫出来）的那串地址，回到连接页直接填回输入框。
  /// 外网那条链接里带 token，存下来省得每次翻电脑的二维码。
  Future<String> restoreAddress() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getString(_addressKey) ?? '';
  }

  /// 只在真的连上之后才记：手滑打错的地址不该把上一次能用的冲掉。
  Future<void> rememberAddress(String raw) async {
    final text = raw.trim();
    if (text.isEmpty) return;
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_addressKey, text);
  }

  // -------------------------------------------------------------- 连接

  /// 换一台电脑或换一个地址：彻底断开再重连。
  void connect(Endpoint endpoint) {
    _endpoint = endpoint;
    _retryDelay = 400;
    _retry?.cancel();
    unawaited(_open());
  }

  /// 断开并清空地址 —— 界面据此回到连接页。
  void forget() {
    _retry?.cancel();
    _retry = null;
    _endpoint = null;
    unawaited(_closeSocket());
    _setState(LinkState.idle);
    unawaited(forgetEndpoint());
  }

  /// 从后台回到前台时补一次连接。手机息屏、切走再回来，socket 常常已经死了。
  void reconnectIfNeeded() {
    if (_endpoint == null) return;
    if (_state == LinkState.online) return;
    _retryDelay = 400;
    _retry?.cancel();
    unawaited(_open());
  }

  Future<void> _open() async {
    final endpoint = _endpoint;
    if (endpoint == null) return;

    await _closeSocket();
    _setState(LinkState.connecting);

    WebSocket socket;
    try {
      socket = await WebSocket.connect(
        endpoint.websocket.toString(),
      ).timeout(const Duration(seconds: 6));
    } catch (_) {
      _setState(LinkState.idle);
      _scheduleRetry();
      return;
    }

    _socket = socket;
    _retryDelay = 400;
    _setState(LinkState.online);
    socket.listen(
      _onFrame,
      onError: (_) => _onClosed(socket),
      onDone: () => _onClosed(socket),
      cancelOnError: false,
    );
    send('audio.refresh', null, true);
  }

  void _onClosed(WebSocket socket) {
    if (_socket != socket) return; // 已经被新一轮连接替换掉了
    _socket = null;
    _setState(LinkState.idle);
    _scheduleRetry();
  }

  void _scheduleRetry() {
    if (_endpoint == null) return;
    _retry?.cancel();
    _retry = Timer(Duration(milliseconds: _retryDelay), () => unawaited(_open()));
    _retryDelay = (_retryDelay * 1.6).round().clamp(400, 3000);
  }

  Future<void> _closeSocket() async {
    final socket = _socket;
    _socket = null;
    if (socket == null) return;
    try {
      await socket.close();
    } catch (_) {
      // 关一个已经死掉的 socket 不用管
    }
  }

  // -------------------------------------------------------------- 收发

  bool send(String action, [Map<String, Object?>? params, bool quiet = false]) {
    final socket = _socket;
    if (socket == null || _state != LinkState.online) {
      if (!quiet) onToast?.call('还没连上电脑', error: true);
      return false;
    }
    try {
      socket.add(jsonEncode({'a': action, 'p': params ?? const <String, Object?>{}}));
      return true;
    } catch (_) {
      _onClosed(socket);
      if (!quiet) onToast?.call('发送失败，正在重连', error: true);
      return false;
    }
  }

  void _onFrame(dynamic frame) {
    if (frame is! String) return;
    Object? decoded;
    try {
      decoded = jsonDecode(frame);
    } catch (_) {
      return;
    }
    if (decoded is! Map) return;

    switch (decoded['t']) {
      case 'state':
        _applyState(decoded['d']);
      case 'err':
        onToast?.call('${decoded['msg'] ?? '操作失败'}', error: true);
      case 'notice':
        final message = '${decoded['msg'] ?? ''}';
        if (message.isNotEmpty) onToast?.call(message, error: false);
    }
  }

  void _applyState(Object? data) {
    if (data is! Map) return;

    final volume = data['volume'];
    if (volume is num) this.volume = volume.toDouble().clamp(0.0, 1.0);

    final muted = data['muted'];
    if (muted is bool) this.muted = muted;

    final devices = data['devices'];
    if (devices is List) {
      this.devices = [
        for (final item in devices)
          if (item is Map)
            AudioDevice(id: '${item['id']}', name: '${item['name']}'),
      ];
    }

    final deviceId = data['deviceId'];
    if (deviceId != null) this.deviceId = '$deviceId';

    final focus = data['focus'];
    if (focus != null) windowTitle = '$focus';

    final maximized = data['maximized'];
    if (maximized is bool) windowMaximized = maximized;

    // window.list 的答复，只有点了标题才会来
    final windows = data['windows'];
    if (windows is List) {
      onWindowList?.call([
        for (final item in windows)
          if (item is Map)
            WindowInfo(
              id: item['id'] is num ? (item['id'] as num).toInt() : 0,
              title: '${item['title'] ?? ''}',
              current: item['current'] == true,
            ),
      ]);
    }

    // media 为 null 表示电脑上没有媒体会话
    if (data.containsKey('media')) {
      final media = data['media'];
      mediaPlaying = media is Map && media['playing'] == true;
      mediaApp = media is Map ? '${media['app'] ?? ''}' : '';
      mediaCanSeek = media is Map && media['canSeek'] == true;
      mediaCanPrev = media is Map && media['canPrev'] == true;
      mediaCanNext = media is Map && media['canNext'] == true;
    }

    notifyListeners();
  }

  void _setState(LinkState next) {
    if (_state == next) return;
    _state = next;
    notifyListeners();
  }
}
