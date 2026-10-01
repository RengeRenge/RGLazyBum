/// 连接页：还没连上电脑时显示。
///
/// 三条路都留出来了 —— 扫码（最快）、搜局域网（二维码找不到了）、手填地址
/// （认得出 IP 的时候）。
library;

import 'package:flutter/material.dart';
import 'package:mobile_scanner/mobile_scanner.dart';

import '../core/client.dart';
import '../core/discovery.dart';
import '../core/endpoint.dart';
import 'common.dart';
import 'theme.dart';

class ConnectPage extends StatefulWidget {
  const ConnectPage({super.key});

  @override
  State<ConnectPage> createState() => _ConnectPageState();
}

class _ConnectPageState extends State<ConnectPage> {
  final RemoteClient _client = RemoteClient.instance;
  final TextEditingController _address = TextEditingController();

  bool _busy = false;
  String _busyText = '';
  double? _progress;
  String? _error;
  List<Endpoint> _found = const [];
  Endpoint? _lastUsed;

  @override
  void initState() {
    super.initState();
    _loadLastUsed();
  }

  @override
  void dispose() {
    _address.dispose();
    super.dispose();
  }

  Future<void> _loadLastUsed() async {
    final endpoint = await _client.restoreEndpoint();
    final address = await _client.restoreAddress();
    if (!mounted) return;
    setState(() {
      _lastUsed = endpoint;
      // 把上次连成功的那串地址填回输入框，外网链接里带 token，省得每次翻二维码。
      if (address.isNotEmpty) _address.text = address;
    });
  }

  // ------------------------------------------------------------ 三种连接方式

  Future<void> _connectTo(Endpoint endpoint) async {
    await _client.rememberEndpoint(endpoint);
    _client.connect(endpoint); // 连上之后根节点会自己切到控制页
  }

  Future<void> _connectManual(String raw) async {
    final target = parseTarget(raw);
    if (target == null) {
      setState(() {
        _error = '这个地址看不懂。可以填 192.168.3.10、192.168.3.10:8765、'
            'pc.example.com，或直接粘贴二维码里的完整链接。';
      });
      return;
    }
    await _run('正在连接 ${target.host}…', () async {
      final (endpoint, outcome) = await resolveTarget(target);
      if (endpoint == null) {
        _fail(_describeFailure(target.host, outcome));
        return;
      }
      await _client.rememberAddress(raw);
      await _connectTo(endpoint);
    });
  }

  /// 连一个已经记下来的地址：先按原样试，不行再按候选端口找一遍。
  /// （端口是自动挑的，电脑重启后可能换了一个，这时原地址就不通了。）
  Future<void> _connectKnown(Endpoint endpoint) async {
    await _run('正在连接 ${endpoint.label}…', () async {
      if (await probeEndpoint(endpoint)) {
        await _connectTo(endpoint);
        return;
      }
      final (fallback, outcome) = await resolveTarget(
        ParsedTarget(host: endpoint.host, token: endpoint.token),
      );
      if (fallback == null) {
        _fail(_describeFailure(endpoint.host, outcome));
        return;
      }
      await _connectTo(fallback);
    });
  }

  /// 连不上时把下一步说清楚。外网那条路十有八九是口令没带，其次是手机没 IPv6。
  String _describeFailure(String host, ProbeOutcome outcome) {
    if (outcome == ProbeOutcome.needsToken) {
      return '$host 上的 懒狗 需要访问口令。在电脑托盘菜单点「显示外网二维码（含 token）」，'
          '把带 ?k= 的整条链接粘到下面的输入框里。';
    }
    if (looksLocalHost(host)) {
      return '连不上 $host。确认电脑上的 懒狗 正在运行，且手机和电脑连的是同一个 Wi-Fi。';
    }
    return '连不上 $host。外网地址要求手机自己就有 IPv6（多数家庭 Wi-Fi 没有、移动数据通常有），'
        '并且电脑端已经打开「IPv6 外网访问」。也可以改用局域网 IP 或扫码。';
  }

  Future<void> _scanQr() async {
    final text = await Navigator.of(
      context,
    ).push<String>(MaterialPageRoute(builder: (_) => const _QrScanPage()));
    if (text == null || text.isEmpty || !mounted) return;
    await _connectManual(text);
  }

  Future<void> _scanLan() async {
    final prefixes = await localSubnets();
    if (!mounted) return;
    if (prefixes.isEmpty) {
      setState(() => _error = '读不到本机网段，请改用扫码或手动填电脑的 IP。');
      return;
    }

    final found = <Endpoint>[];
    await _run('正在扫描局域网…', () async {
      for (final port in kCandidatePorts) {
        for (final prefix in prefixes) {
          found.addAll(
            await scanSubnet(
              prefix,
              port,
              onProgress: (done, total) {
                if (!mounted) return;
                setState(() {
                  _busyText = '正在扫描 $prefix.* · 端口 $port · $done/$total';
                  _progress = done / total;
                });
              },
            ),
          );
        }
        // 一般第一轮就能命中；找到了就不用再换下一个端口重扫一遍
        if (found.isNotEmpty) break;
      }
    });

    if (!mounted) return;
    if (found.isEmpty) {
      setState(() {
        _error = '没搜到电脑。确认电脑上的 懒狗 正在运行，且手机和电脑连的是同一个 Wi-Fi。'
            '还不行就用扫码，或手动填电脑的 IP。';
      });
    } else if (found.length == 1) {
      await _connectTo(found.first);
    } else {
      setState(() => _found = found);
    }
  }

  // ---------------------------------------------------------------- 小工具

  Future<void> _run(String busyText, Future<void> Function() body) async {
    setState(() {
      _busy = true;
      _busyText = busyText;
      _progress = null;
      _error = null;
    });
    try {
      await body();
    } finally {
      if (mounted) {
        setState(() {
          _busy = false;
          _progress = null;
        });
      }
    }
  }

  void _fail(String message) {
    if (!mounted) return;
    setState(() => _error = message);
  }

  // ---------------------------------------------------------------- 界面

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.fromLTRB(12, 24, 12, 24),
          children: [
            const Text(
              '懒狗',
              textAlign: TextAlign.center,
              style: TextStyle(fontSize: 26, fontWeight: FontWeight.w700, letterSpacing: 1),
            ),
            const SizedBox(height: 6),
            const Text(
              '手机遥控电脑',
              textAlign: TextAlign.center,
              style: TextStyle(fontSize: 13, color: kMuted),
            ),
            const SizedBox(height: 24),

            if (_lastUsed != null) ...[
              Panel(
                title: '上次连的',
                children: [
                  ActionButton(
                    label: '${_lastUsed!.label}   直接连',
                    primary: true,
                    onTap: _busy ? null : () => _connectKnown(_lastUsed!),
                  ),
                ],
              ),
            ],

            Panel(
              title: '连接电脑',
              children: [
                ActionButton(label: '扫码连接', primary: true, onTap: _busy ? null : _scanQr),
                const Gap(8),
                ActionButton(label: '搜索局域网', onTap: _busy ? null : _scanLan),
                const Gap(14),
                TextField(
                  controller: _address,
                  keyboardType: TextInputType.url,
                  autocorrect: false,
                  enableSuggestions: false,
                  textInputAction: TextInputAction.go,
                  onSubmitted: (value) {
                    if (!_busy) _connectManual(value);
                  },
                  // 点按钮时别把输入焦点丢掉，否则软键盘会收起来 —— 连按几下很难受
                  onTapOutside: (_) {},
                  style: const TextStyle(fontSize: 15),
                  decoration: InputDecoration(
                    hintText: '电脑地址：192.168.3.10、pc.example.com 或外网完整链接',
                    hintStyle: const TextStyle(color: kMuted, fontSize: 14),
                    filled: true,
                    fillColor: kCard2,
                    isDense: true,
                    contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 14),
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
                const Gap(8),
                Row(
                  children: [
                    ActionButton(
                      label: '连接这个地址',
                      expand: true,
                      onTap: _busy ? null : () => _connectManual(_address.text),
                    ),
                  ],
                ),
              ],
            ),

            if (_busy)
              Panel(
                children: [
                  LinearProgressIndicator(
                    value: _progress,
                    minHeight: 4,
                    backgroundColor: kCard2,
                    color: kAccent,
                  ),
                  const Gap(10),
                  Text(
                    _busyText,
                    textAlign: TextAlign.center,
                    style: const TextStyle(fontSize: 13, color: kMuted),
                  ),
                ],
              ),

            if (_found.isNotEmpty)
              Panel(
                title: '找到 ${_found.length} 台',
                children: [
                  for (final endpoint in _found) ...[
                    ActionButton(
                      label: endpoint.label,
                      onTap: _busy ? null : () => _connectTo(endpoint),
                    ),
                    const Gap(8),
                  ],
                ],
              ),

            if (_error != null)
              Panel(
                children: [
                  Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text('⚠ ', style: TextStyle(color: kDanger, fontSize: 14)),
                      Expanded(
                        child: Text(
                          _error!,
                          style: const TextStyle(fontSize: 13, color: kDanger, height: 1.5),
                        ),
                      ),
                    ],
                  ),
                ],
              ),

            const Padding(
              padding: EdgeInsets.symmetric(horizontal: 4),
              child: Text(
                '同一个 Wi-Fi 下直接填电脑的局域网 IP 就行。人在外面就填 DDNS 域名，'
                '并且要把二维码里的 ?k= 口令一起带上（在电脑托盘菜单点「显示外网二维码（含 token）」拿完整的链接）。'
                '电脑上双击 懒狗 托盘程序，二维码会自己弹出来，扫它最省事。',
                style: TextStyle(fontSize: 12, color: kMuted, height: 1.6),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// 全屏扫码页。扫到第一段文字就返回。
class _QrScanPage extends StatefulWidget {
  const _QrScanPage();

  @override
  State<_QrScanPage> createState() => _QrScanPageState();
}

class _QrScanPageState extends State<_QrScanPage> {
  final MobileScannerController _controller = MobileScannerController(
    detectionSpeed: DetectionSpeed.noDuplicates,
    formats: const <BarcodeFormat>[BarcodeFormat.qrCode],
  );

  bool _handled = false;

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  void _onDetect(BarcodeCapture capture) {
    if (_handled) return;
    for (final barcode in capture.barcodes) {
      final value = barcode.rawValue;
      if (value == null || value.isEmpty) continue;
      _handled = true; // 一帧里可能有好几个码，只认第一个
      Navigator.of(context).pop(value);
      return;
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.black,
      body: Stack(
        fit: StackFit.expand,
        children: [
          MobileScanner(
            controller: _controller,
            onDetect: _onDetect,
            errorBuilder: (context, error) {
              return Center(
                child: Padding(
                  padding: const EdgeInsets.all(32),
                  child: Text(
                    '相机打不开：${error.errorCode.name}\n'
                    '如果是权限问题，到系统设置里给 懒狗 打开相机权限。',
                    textAlign: TextAlign.center,
                    style: const TextStyle(color: kText, fontSize: 14, height: 1.6),
                  ),
                ),
              );
            },
          ),
          const _ScanFrame(),
          Positioned(
            left: 0,
            right: 0,
            bottom: 0,
            child: SafeArea(
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Column(
                  children: [
                    Text(
                      '对着电脑上的二维码扫一下',
                      textAlign: TextAlign.center,
                      style: const TextStyle(color: kText, fontSize: 14),
                    ),
                    const Gap(12),
                    Row(
                      children: [
                        ActionButton(
                          label: '取消',
                          expand: true,
                          onTap: () => Navigator.of(context).pop(),
                        ),
                        const SizedBox(width: 8),
                        ActionButton(
                          label: '手电筒',
                          expand: true,
                          onTap: () => _controller.toggleTorch(),
                        ),
                      ],
                    ),
                  ],
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

/// 取景框。
class _ScanFrame extends StatelessWidget {
  const _ScanFrame();

  @override
  Widget build(BuildContext context) {
    return IgnorePointer(
      child: Center(
        child: Container(
          width: 240,
          height: 240,
          decoration: BoxDecoration(
            border: Border.all(color: kAccent, width: 3),
            borderRadius: BorderRadius.circular(16),
          ),
        ),
      ),
    );
  }
}
