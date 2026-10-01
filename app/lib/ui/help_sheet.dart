/// 使用说明。内容跟网页版 help 一致，只是把"浏览器"换成了 App 的说法。
library;

import 'package:flutter/material.dart';

import 'common.dart';
import 'theme.dart';

const List<String> _lines = <String>[
  '手机和电脑连同一个局域网即可（同一路由器 / 同一 Wi-Fi）。',
  '连不上时：先确认电脑上的托盘程序在运行（任务栏小图标），再重新扫码或搜一次局域网。',
  '想从外网控制：先在电脑托盘菜单打开「IPv6 外网访问」，然后扫「显示外网二维码（含 token）」。token 只出现在链接里，局域网访问不需要。',
  '也可以不扫码，直接在输入框里填地址：局域网填 192.168.x.x，外网填 DDNS 域名或 IPv6 地址，IPv4 / IPv6 / 域名都认；带端口的写法（如 pc.example.com:8765）也行。外网那条必须把 ?k= 口令一起带上，把整条链接粘进去最稳妥。连成功过的那串地址会记住，下次进连接页自动填回输入框。',
  '点左上角标题叫出菜单：触摸板、屏幕、使用说明都在里面。',
  '触摸板：单指滑动移动光标，轻点＝左键，双指轻点＝右键，双指上下滑动＝滚轮；灵敏度可调。',
  '屏幕：一块显示器一个模块，点「刷新」重新抓图，点「自动」每 2 秒自动更新（费流量，外网慎用）。',
  '媒体：中间那个大按钮是播放/暂停，图标跟着电脑上真实的播放状态走（在电脑上手动暂停，这里也会变）；它两边是上一曲 / 下一曲，最外侧两个是快退 / 快进 10 秒。标题右边写着这排键当前控制的是哪个播放器 —— 电脑上同时开着好几个时，只有那一个会动。当前播放器做不了的操作会直接把键灰掉、按不动 —— 比如网易云音乐没实现跳转，快退/快进就是灰的；Edge 里放单个视频时无处切歌，上一曲/下一曲就是灰的。',
  '键盘输入：先在电脑上点一下要输入的位置，再在手机上打字发送；支持中文和 emoji，下面还有回车、退格、空格、方向键等按键。',
  '音频输出：点设备名即可把系统默认输出切过去，正在播放的声音会立刻改道。',
  '关闭显示器后电脑仍在运行，随时点「唤醒屏幕」即可；这时媒体键、鼠标、打字都能用。',
  '锁定之后 Windows 会拦截模拟输入，鼠标/键盘/媒体键将无法使用（系统安全机制，无法绕过）。',
  '睡眠 / 休眠后服务随系统一起挂起，需要用开机卡或电源键唤醒，唤醒后 App 会自动重连。',
];

void showHelpSheet(BuildContext context) {
  showModalBottomSheet<void>(
    context: context,
    backgroundColor: kCard,
    isScrollControlled: true,
    shape: RoundedRectangleBorder(
      borderRadius: const BorderRadius.vertical(top: Radius.circular(16)),
      side: const BorderSide(color: kLine),
    ),
    builder: (sheet) => SafeArea(
      child: ConstrainedBox(
        constraints: BoxConstraints(
          maxHeight: MediaQuery.sizeOf(context).height * 0.82,
        ),
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(18),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const Text(
                '使用说明',
                style: TextStyle(fontSize: 16, fontWeight: FontWeight.w600),
              ),
              const Gap(12),
              for (final line in _lines)
                Padding(
                  padding: const EdgeInsets.only(bottom: 10),
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Padding(
                        padding: EdgeInsets.only(top: 7, right: 8),
                        child: _Bullet(),
                      ),
                      Expanded(
                        child: Text(
                          line,
                          style: const TextStyle(
                            fontSize: 13,
                            color: kMuted,
                            height: 1.6,
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
              const Gap(6),
              // 不能用 expand：Expanded 放进单列滚动区里的 Column 会抛
              // "incoming height constraints are unbounded"。Column 已经 stretch，不展开也是满宽。
              ActionButton(
                label: '知道了',
                primary: true,
                onTap: () => Navigator.of(sheet).pop(),
              ),
            ],
          ),
        ),
      ),
    ),
  );
}

class _Bullet extends StatelessWidget {
  const _Bullet();

  @override
  Widget build(BuildContext context) {
    return Container(
      width: 5,
      height: 5,
      decoration: const BoxDecoration(color: kMuted, shape: BoxShape.circle),
    );
  }
}
