/// 局域网扫描：手边没二维码、也不想敲 IP 的时候用。
///
/// 只扫本机所在网段的 /24，端口逐个候选值来 —— 先拿第一个候选端口扫完整个
/// 网段，没找到再换下一个。家用路由器基本都开着 /24，先按这个来，够用且简单。
library;

import 'dart:io';

import 'endpoint.dart';

/// 本机所有非回环 IPv4 所在的 /24 网段前缀，例如 "192.168.3"。
Future<List<String>> localSubnets() async {
  final prefixes = <String>{};
  try {
    final interfaces = await NetworkInterface.list(
      type: InternetAddressType.IPv4,
      includeLinkLocal: false,
    );
    for (final interface in interfaces) {
      for (final address in interface.addresses) {
        final parts = address.address.split('.');
        if (parts.length == 4) prefixes.add(parts.take(3).join('.'));
      }
    }
  } catch (_) {
    // 拿不到网卡就当没有网段，交给界面提示用户手填
  }
  return prefixes.toList();
}

/// 在某个网段里按某个端口找 RGLazyBum，返回找到的所有地址。
///
/// [onProgress] 报的是"已试过多少个地址 / 一共多少个"，界面拿它画进度。
Future<List<Endpoint>> scanSubnet(
  String prefix,
  int port, {
  Duration timeout = const Duration(milliseconds: 700),
  int concurrency = 48,
  void Function(int done, int total)? onProgress,
}) async {
  final hosts = <String>[for (var i = 1; i <= 254; i++) '$prefix.$i'];
  final found = <Endpoint>[];
  final client = HttpClient()..connectionTimeout = timeout;

  var next = 0;
  var done = 0;
  try {
    Future<void> worker() async {
      while (true) {
        final index = next++;
        if (index >= hosts.length) return;
        final host = hosts[index];
        if (await probeEndpoint(
          Endpoint(host: host, port: port),
          timeout: timeout,
          client: client,
        )) {
          found.add(Endpoint(host: host, port: port));
        }
        done++;
        onProgress?.call(done, hosts.length);
      }
    }

    await Future.wait([for (var i = 0; i < concurrency; i++) worker()]);
  } finally {
    client.close(force: true);
  }

  found.sort((a, b) => a.host.compareTo(b.host));
  return found;
}
