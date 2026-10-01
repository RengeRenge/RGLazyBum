/// 屏幕页：看电脑画面，一块显示器一个模块。
///
/// 抓图走的是 HTTP（/api/shot），和长连接不是一条路，所以这里自己发请求。
library;

import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';

import '../core/client.dart';
import 'common.dart';
import 'theme.dart';

class Monitor {
  const Monitor({
    required this.index,
    required this.width,
    required this.height,
    required this.primary,
  });

  final int index;
  final int width;
  final int height;
  final bool primary;

  static Monitor? fromJson(Object? raw) {
    if (raw is! Map) return null;
    final index = raw['index'];
    final width = raw['width'];
    final height = raw['height'];
    if (index is! num || width is! num || height is! num) return null;
    return Monitor(
      index: index.toInt(),
      width: width.toInt(),
      height: height.toInt(),
      primary: raw['primary'] == true,
    );
  }
}

class ScreenPage extends StatefulWidget {
  const ScreenPage({super.key});

  @override
  State<ScreenPage> createState() => _ScreenPageState();
}

class _ScreenPageState extends State<ScreenPage> {
  final RemoteClient _client = RemoteClient.instance;

  List<Monitor> _monitors = const [];
  String? _message = '加载中…';
  bool _loading = false;
  bool _auto = false;
  Timer? _timer;

  /// 每次刷新都换一个时间戳，让图片 URL 变掉，否则会一直显示缓存里的旧图。
  int _stamp = DateTime.now().millisecondsSinceEpoch;

  @override
  void initState() {
    super.initState();
    _loadScreens();
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _loadScreens() async {
    if (_loading) return;
    final endpoint = _client.endpoint;
    if (endpoint == null) return;

    _loading = true;
    final http = HttpClient()..connectionTimeout = const Duration(seconds: 5);
    try {
      final request = await http.getUrl(endpoint.http('/api/screens'));
      final response = await request.close();
      final body = await response.transform(utf8.decoder).join();
      if (response.statusCode != 200) {
        throw HttpException('HTTP ${response.statusCode}');
      }
      final decoded = jsonDecode(body);
      final monitors = <Monitor>[
        if (decoded is List) for (final item in decoded) ?Monitor.fromJson(item),
      ];
      if (!mounted) return;
      setState(() {
        _monitors = monitors;
        _stamp = DateTime.now().millisecondsSinceEpoch;
        _message = monitors.isEmpty ? '没有检测到显示器' : null;
      });
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _monitors = const [];
        _message = '取显示器列表失败：$error';
      });
      showToast('抓图失败，稍后再试', error: true);
    } finally {
      http.close(force: true);
      _loading = false;
    }
  }

  void _refresh() {
    if (_monitors.isEmpty) {
      _loadScreens();
      return;
    }
    setState(() => _stamp = DateTime.now().millisecondsSinceEpoch);
  }

  void _toggleAuto() {
    setState(() => _auto = !_auto);
    _timer?.cancel();
    if (_auto) {
      _timer = Timer.periodic(const Duration(seconds: 2), (_) => _refresh());
    }
  }

  String _shotUrl(Monitor monitor) {
    final endpoint = _client.endpoint;
    if (endpoint == null) return '';
    return endpoint
        .http('/api/shot', {
          'm': '${monitor.index}',
          'w': '1400',
          'q': '70',
          't': '$_stamp',
        })
        .toString();
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
                      '屏幕',
                      style: TextStyle(fontSize: 15, fontWeight: FontWeight.w600),
                    ),
                  ),
                  PillButton(label: '自动', active: _auto, onTap: _toggleAuto),
                  const SizedBox(width: 8),
                  PillButton(label: '刷新', onTap: _refresh),
                  const SizedBox(width: 8),
                  PillButton(label: '关闭', onTap: () => Navigator.of(context).pop()),
                ],
              ),
              const Gap(10),
              Expanded(
                child: _monitors.isEmpty
                    ? Center(
                        child: Text(
                          _message ?? '没有检测到显示器',
                          style: const TextStyle(fontSize: 13, color: kMuted),
                        ),
                      )
                    : ListView(
                        padding: EdgeInsets.zero,
                        children: [
                          for (var i = 0; i < _monitors.length; i++)
                            _monitorCard(_monitors[i], i),
                        ],
                      ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _monitorCard(Monitor monitor, int position) {
    final title = '显示器 ${position + 1}${monitor.primary ? '（主屏）' : ''}';

    return Panel(
      title: title,
      hint: '${monitor.width}×${monitor.height}',
      children: [
        ClipRRect(
          borderRadius: BorderRadius.circular(10),
          child: Image.network(
            _shotUrl(monitor),
            fit: BoxFit.fitWidth,
            gaplessPlayback: true,
            loadingBuilder: (context, child, progress) {
              if (progress == null) return child;
              return const SizedBox(
                height: 80,
                child: Center(
                  child: SizedBox(
                    width: 20,
                    height: 20,
                    child: CircularProgressIndicator(strokeWidth: 2, color: kAccent),
                  ),
                ),
              );
            },
            errorBuilder: (context, error, stack) => Container(
              height: 80,
              alignment: Alignment.center,
              color: kCard2,
              child: const Text('抓图失败', style: TextStyle(fontSize: 13, color: kMuted)),
            ),
          ),
        ),
      ],
    );
  }
}
