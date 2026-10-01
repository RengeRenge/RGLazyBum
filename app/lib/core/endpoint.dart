/// 电脑端服务的地址，以及"怎么找到一个能用的地址"。
///
/// 候选端口列表必须和电脑端 settings.py 里的 CANDIDATE_PORTS 完全一致：
/// 两端共用这一份列表，服务端起在列表里的第一个空闲端口上，手机端按同样的
/// 顺序挨个试。谁改了都要同步另一边。
library;

import 'dart:async';
import 'dart:convert';
import 'dart:io';

const List<int> kCandidatePorts = <int>[8765, 38765, 38766, 38767, 38768];

class Endpoint {
  const Endpoint({required this.host, required this.port, this.token = ''});

  final String host;
  final int port;

  /// 外网访问口令，来自二维码链接里的 ?k=。局域网访问时为空字符串。
  final String token;

  bool get isIpv6 => host.contains(':');

  /// 显示用。IPv6 加方括号，和浏览器地址栏一个样子。
  String get label => isIpv6 ? '[$host]:$port' : '$host:$port';

  /// 拼一个 HTTP 地址。带上口令时统一挂在查询串上 —— 原生客户端不会像浏览器
  /// 那样自动保存服务端种的 cookie，所以每次都显式带一次。
  Uri http(String path, [Map<String, String>? query]) {
    final params = <String, String>{...?query};
    if (token.isNotEmpty) params['k'] = token;
    return Uri(
      scheme: 'http',
      host: host,
      port: port,
      path: path,
      queryParameters: params.isEmpty ? null : params,
    );
  }

  Uri get websocket => Uri(
    scheme: 'ws',
    host: host,
    port: port,
    path: '/ws',
    queryParameters: token.isEmpty ? null : {'k': token},
  );

  String encode() => jsonEncode({'host': host, 'port': port, 'token': token});

  static Endpoint? decode(String? raw) {
    if (raw == null || raw.isEmpty) return null;
    try {
      final data = jsonDecode(raw);
      if (data is! Map) return null;
      final host = data['host'];
      final port = data['port'];
      if (host is! String || host.isEmpty || port is! int) return null;
      final token = data['token'];
      return Endpoint(host: host, port: port, token: token is String ? token : '');
    } catch (_) {
      return null;
    }
  }
}

/// 解析出来但还没验证过的目标：端口可能缺省（那就挨个候选端口试）。
class ParsedTarget {
  const ParsedTarget({required this.host, this.port, this.token = ''});

  final String host;
  final int? port;
  final String token;
}

/// 解析用户输入或二维码内容。
///
/// 以下写法都认（IPv4 / IPv6 / 域名一视同仁）：
///   http://192.168.3.10:8765/          （浏览器地址栏整串粘过来）
///   http://[240e:xxx::1]:8765/?k=abc   （外网二维码，带口令）
///   192.168.3.10:8765
///   192.168.3.10                        （端口留空，按候选列表试）
///   240e:xxx::1                         （裸 IPv6 字面量）
///   pc.example.com                      （外网 DDNS 域名）
///   pc.example.com:8765/?k=abc          （外网域名 + 口令）
ParsedTarget? parseTarget(String raw) {
  var text = raw.trim();
  if (text.isEmpty) return null;

  if (!text.contains('://')) {
    // 不带协议的裸地址。含两个以上冒号的是 IPv6，直接塞进方括号，
    // 免得被当成"主机:端口"切错。
    final bareIpv6 = !text.startsWith('[') && RegExp(r':.*:').hasMatch(text);
    text = 'http://${bareIpv6 ? '[$text]' : text}';
  }

  Uri uri;
  try {
    uri = Uri.parse(text);
  } catch (_) {
    return null;
  }

  if (uri.host.isEmpty) return null;
  return ParsedTarget(
    host: uri.host,
    port: uri.hasPort ? uri.port : null,
    token: uri.queryParameters['k'] ?? '',
  );
}

/// 首页里出现这串字才算"是本程序"。和 web/index.html 的品牌名一致，
/// 电脑端改名了这里要跟着改，否则安卓端的自动发现会全部失效。
const String kAppMarker = '懒狗';

/// 探测结果。
enum ProbeOutcome {
  /// 是本程序，可以连。
  ok,

  /// 是本程序，但走的是外网入口且没带口令（电脑端只对公网 IPv6 来源要 ?k=）。
  needsToken,

  /// 连不上，或者连上了但不是本程序。
  failed,
}

/// 探测这个地址上跑的是不是 懒狗。
///
/// 只连端口不够：同一台机器上别的程序也可能占着候选端口，所以要抓一次首页
/// 认品牌名。要口令这一档必须单独分出来 —— 外网入口不带 ?k= 时电脑端回的是
/// 403 口令页，也拿不到首页内容，跟"连不上"混在一起的话，用户只会看到一句
/// "没找到电脑"，根本想不到要贴带 token 的完整链接。
Future<ProbeOutcome> probeOutcome(
  Endpoint endpoint, {
  Duration timeout = const Duration(milliseconds: 900),
  HttpClient? client,
}) async {
  final owned = client == null;
  final http = client ?? (HttpClient()..connectionTimeout = timeout);
  try {
    final request = await http.getUrl(endpoint.http('/')).timeout(timeout);
    final response = await request.close().timeout(timeout);
    final body = await response.transform(utf8.decoder).join().timeout(timeout);
    if (response.statusCode == 200 && body.contains(kAppMarker)) {
      return ProbeOutcome.ok;
    }
    if (response.statusCode == 403 && body.contains('需要访问口令')) {
      return ProbeOutcome.needsToken;
    }
    return ProbeOutcome.failed;
  } catch (_) {
    return ProbeOutcome.failed;
  } finally {
    if (owned) http.close(force: true);
  }
}

Future<bool> probeEndpoint(
  Endpoint endpoint, {
  Duration timeout = const Duration(milliseconds: 900),
  HttpClient? client,
}) async {
  final outcome = await probeOutcome(endpoint, timeout: timeout, client: client);
  return outcome == ProbeOutcome.ok;
}

/// 把一个（可能没写端口的）目标解析成一个确实能用的地址。
///
/// 顺带把探测结论带回去：没连上时要靠它区分"要口令"和"真的够不着"，
/// 两者给用户的下一步完全不一样。
Future<(Endpoint?, ProbeOutcome)> resolveTarget(
  ParsedTarget target, {
  Duration timeout = const Duration(milliseconds: 900),
}) async {
  final ports = target.port != null ? <int>[target.port!] : kCandidatePorts;
  final client = HttpClient()..connectionTimeout = timeout;
  try {
    // 并行试，再按候选顺序取第一个通的 —— 串行的话最坏要等 5 个超时。
    final results = await Future.wait(
      ports.map(
        (port) => probeOutcome(
          Endpoint(host: target.host, port: port, token: target.token),
          timeout: timeout,
          client: client,
        ),
      ),
    );
    final index = results.indexOf(ProbeOutcome.ok);
    if (index >= 0) {
      return (
        Endpoint(host: target.host, port: ports[index], token: target.token),
        ProbeOutcome.ok,
      );
    }
    // 一个都没通：只要有一处是"要口令"，就按要口令提示
    final outcome = results.contains(ProbeOutcome.needsToken)
        ? ProbeOutcome.needsToken
        : ProbeOutcome.failed;
    return (null, outcome);
  } finally {
    client.close(force: true);
  }
}

/// 粗略判断是不是"局域网里的地址"，只用来决定连不上时给哪句提示。
///
/// 认不出来的（域名、公网 IP）一律当外网 —— 外网那句"手机自己要有 IPv6"
/// 在局域网场景下只是多余，反过来漏掉就是让人白折腾。
bool looksLocalHost(String host) {
  final h = host.toLowerCase();
  if (h.contains(':')) {
    // IPv6：链路本地 fe80::/10 和 ULA fc00::/7 都是本地
    return h == '::1' ||
        h.startsWith('fe8') ||
        h.startsWith('fe9') ||
        h.startsWith('fea') ||
        h.startsWith('feb') ||
        h.startsWith('fc') ||
        h.startsWith('fd');
  }
  final parts = h.split('.');
  if (parts.length == 4 && parts.every((p) => int.tryParse(p) != null)) {
    final a = int.parse(parts[0]);
    final b = int.parse(parts[1]);
    return a == 10 ||
        a == 127 ||
        (a == 192 && b == 168) ||
        (a == 172 && b >= 16 && b <= 31) ||
        (a == 169 && b == 254);
  }
  return !h.contains('.'); // 单段主机名（mypc 这种）算本地
}
