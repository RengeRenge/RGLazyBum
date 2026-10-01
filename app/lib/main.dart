/// RGLazyBum 手机端 —— 安卓遥控电脑。电脑端是 Python 写的托盘后台程序，
/// 这里通过 WebSocket 发指令、通过 HTTP 取截图。
///
/// 只做安卓：网页版（web/ 那三个文件）继续由电脑端直接发给浏览器，两边各管各的。
library;

import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';

import 'core/client.dart';
import 'ui/common.dart';
import 'ui/connect_page.dart';
import 'ui/home_page.dart';
import 'ui/theme.dart';

void main() {
  runApp(const RGLazyBumApp());
}

class RGLazyBumApp extends StatefulWidget {
  const RGLazyBumApp({super.key});

  @override
  State<RGLazyBumApp> createState() => _RGLazyBumAppState();
}

class _RGLazyBumAppState extends State<RGLazyBumApp> with WidgetsBindingObserver {
  final RemoteClient _client = RemoteClient.instance;

  /// 读上次连的地址是一步异步操作，读完之前先别闪一下连接页。
  bool _booted = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _client.onToast = showToast;
    _client.addListener(_onClientChanged);
    _restoreLastEndpoint();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _client.removeListener(_onClientChanged);
    super.dispose();
  }

  void _onClientChanged() {
    if (mounted) setState(() {});
  }

  Future<void> _restoreLastEndpoint() async {
    final endpoint = await _client.restoreEndpoint();
    if (endpoint != null) _client.connect(endpoint);
    if (mounted) setState(() => _booted = true);
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    // 切走再回来时 socket 往往已经断了，补一次连接
    if (state == AppLifecycleState.resumed) _client.reconnectIfNeeded();
  }

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: '懒狗',
      debugShowCheckedModeBanner: false,
      theme: buildTheme(),
      scaffoldMessengerKey: messengerKey,
      locale: const Locale('zh', 'CN'),
      localizationsDelegates: GlobalMaterialLocalizations.delegates,
      supportedLocales: const <Locale>[Locale('zh', 'CN')],
      home: !_booted
          ? const _Splash()
          : (_client.endpoint == null ? const ConnectPage() : const HomePage()),
    );
  }
}

class _Splash extends StatelessWidget {
  const _Splash();

  @override
  Widget build(BuildContext context) {
    return const Scaffold(
      body: Center(
        child: Text(
          '懒狗',
          style: TextStyle(fontSize: 22, fontWeight: FontWeight.w700, letterSpacing: 1),
        ),
      ),
    );
  }
}
