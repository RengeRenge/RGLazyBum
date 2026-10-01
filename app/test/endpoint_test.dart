import 'package:flutter_test/flutter_test.dart';
import 'package:rglazybum_app/core/endpoint.dart';

void main() {
  group('parseTarget', () {
    test('认裸 IP 和带端口的写法', () {
      expect(parseTarget('192.168.3.10')?.host, '192.168.3.10');
      expect(parseTarget('192.168.3.10')?.port, isNull);

      final withPort = parseTarget('192.168.3.10:8765');
      expect(withPort?.host, '192.168.3.10');
      expect(withPort?.port, 8765);
    });

    test('浏览器地址栏整串粘过来也能认', () {
      final target = parseTarget('http://192.168.3.10:38765/');
      expect(target?.host, '192.168.3.10');
      expect(target?.port, 38765);
      expect(target?.token, '');
    });

    test('外网二维码：IPv6 加方括号，口令在 k 参数里', () {
      final target = parseTarget('http://[240e:1:2::3]:8765/?k=abc123');
      expect(target?.host, '240e:1:2::3');
      expect(target?.port, 8765);
      expect(target?.token, 'abc123');
    });

    test('没有方括号的裸 IPv6 不会把最后一段当成端口', () {
      final target = parseTarget('240e:1:2::3');
      expect(target?.host, '240e:1:2::3');
      expect(target?.port, isNull);
    });

    test('空串和垃圾输入返回 null', () {
      expect(parseTarget('   '), isNull);
      expect(parseTarget('http://'), isNull);
    });
  });

  test('IPv6 地址拼出来要带方括号', () {
    const endpoint = Endpoint(host: '240e:1:2::3', port: 8765);
    expect(endpoint.label, '[240e:1:2::3]:8765');
    expect(endpoint.http('/').toString(), 'http://[240e:1:2::3]:8765/');
  });

  test('带口令时 HTTP 地址会带上 k 参数', () {
    const endpoint = Endpoint(host: '192.168.3.10', port: 8765, token: 'abc');
    expect(endpoint.http('/api/screens').queryParameters['k'], 'abc');
  });
}
