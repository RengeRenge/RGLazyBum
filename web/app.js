/* RGLazyBum 手机端控制页面 */
(() => {
  'use strict';

  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => Array.from(document.querySelectorAll(sel));

  const els = {
    status: $('#status'),
    volSlider: $('#volSlider'),
    volValue: $('#volValue'),
    muteBtn: $('#muteBtn'),
    devices: $('#devices'),
    toast: $('#toast'),
    textInput: $('#textInput'),
    playBtn: $('#playBtn'),
    mediaHint: $('#mediaHint'),
    winPick: $('#winPick'),
    winTitle: $('#winTitle'),
    winPop: $('#winPop'),
    winPopList: $('#winPopList'),
    winMaxBtn: $('#winMaxBtn'),
    prevBtn: $('#prevBtn'),
    nextBtn: $('#nextBtn'),
    seekBackBtn: $('#seekBackBtn'),
    seekFwdBtn: $('#seekFwdBtn'),
  };

  /* ------------------------------------------------------------ WebSocket */

  let ws = null;
  let reconnectTimer = 0;
  let reconnectDelay = 400;

  function setStatus(kind, text) {
    els.status.className = 'status ' + kind;
    els.status.querySelector('span').textContent = text;
  }

  function connect() {
    clearTimeout(reconnectTimer);
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    let sock;
    try {
      sock = new WebSocket(`${proto}//${location.host}/ws`);
    } catch (err) {
      scheduleReconnect();
      return;
    }
    ws = sock;
    setStatus('', '连接中…');

    sock.onopen = () => {
      reconnectDelay = 400;
      setStatus('online', '已连接');
      send('audio.refresh');
    };
    sock.onmessage = (ev) => {
      let msg;
      try { msg = JSON.parse(ev.data); } catch (err) { return; }
      if (msg.t === 'state') applyState(msg.d);
      else if (msg.t === 'err') toast(msg.msg || '操作失败', true);
      else if (msg.t === 'notice') toast(msg.msg);
    };
    sock.onclose = () => {
      if (ws === sock) ws = null;
      setStatus('offline', '已断开，重连中…');
      scheduleReconnect();
    };
    sock.onerror = () => { try { sock.close(); } catch (err) { /* 交给 onclose */ } };
  }

  function scheduleReconnect() {
    clearTimeout(reconnectTimer);
    reconnectTimer = setTimeout(connect, reconnectDelay);
    reconnectDelay = Math.min(reconnectDelay * 1.6, 3000);
  }

  function send(action, params, quiet) {
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      if (!quiet) toast('还没连上电脑', true);
      return false;
    }
    ws.send(JSON.stringify({ a: action, p: params || {} }));
    return true;
  }

  /* ---------------------------------------------------------------- 状态 */

  // 前台窗口是"以管理员身份运行"的进程（游戏基本都是）时，Windows 的 UIPI 会
  // 把我们发过去的鼠标键盘静默丢掉 —— SendInput 返回成功但什么也没发生，
  // 前端一条报错都收不到。所以只能主动解释，并给出解法。
  const BLOCKED_HINT =
    '电脑上当前窗口是「以管理员身份」运行的（游戏基本都是），' +
    'Windows 会直接丢掉我们发过去的鼠标和键盘：滑了、按了都不会有反应。' +
    '在电脑托盘的右键菜单里点一下「以管理员身份重启」就好（会弹一次 UAC 确认）。';

  let volumeDragging = false;
  let volumeDragTimer = 0;
  let devicesSignature = null;

  function applyState(d) {
    if (!d) return;
    // 电脑上没有媒体会话时服务端发 null，退回"播放"图标。
    // 播放/暂停两个 SVG 都在按钮里，切 playing 类由 CSS 决定显示哪个。
    if (d.media !== undefined) {
      els.playBtn.classList.toggle('playing', !!(d.media && d.media.playing));
      // 电脑上可能同时有好几个播放器，这里显示的才是按钮真正会控制的那一个
      els.mediaHint.textContent = (d.media && d.media.app) || '';
      // 播放器没实现的操作（网易云音乐不会跳转、Edge 放单个视频时无处切歌）
      // 服务端会报 false，这里把对应的键禁掉，别让人以为按坏了
      const can = (key) => !!(d.media && d.media[key]);
      els.prevBtn.disabled = !can('canPrev');
      els.nextBtn.disabled = !can('canNext');
      els.seekBackBtn.disabled = !can('canSeek');
      els.seekFwdBtn.disabled = !can('canSeek');
    }
    if (typeof d.focus === 'string') {
      // 当前前台窗口的标题，完整内容挂在 title 上，鼠标悬停能看全
      els.winTitle.textContent = d.focus;
      els.winTitle.title = d.focus;
    }
    // 前台窗口最大化了就换成「还原」那个图标，跟 Windows 标题栏一致
    if (typeof d.maximized === 'boolean') {
      els.winMaxBtn.classList.toggle('maximized', d.maximized);
      els.winMaxBtn.setAttribute('aria-label', d.maximized ? '还原' : '最大化');
    }
    // window.list 的答复。列表只在用户点了标题之后才要，所以收到就弹。
    if (Array.isArray(d.windows)) openWindowPop(d.windows);
    // 触摸板页 / 键盘页顶部那条红框提示
    if (typeof d.blocked === 'boolean') {
      $$('[data-blocked-warn]').forEach((el) => {
        el.textContent = d.blocked ? BLOCKED_HINT : '';
        el.classList.toggle('hidden', !d.blocked);
      });
    }
    if (typeof d.volume === 'number' && !volumeDragging) {
      els.volSlider.value = Math.round(d.volume * 100);
    }
    if (typeof d.volume === 'number') {
      els.volValue.textContent = Math.round(d.volume * 100) + '%';
    }
    if (typeof d.muted === 'boolean') {
      els.volValue.classList.toggle('muted', d.muted);
      els.muteBtn.classList.toggle('active', d.muted);
      els.muteBtn.textContent = d.muted ? '已静音' : '静音';
    }
    if (d.devices) {
      const signature = JSON.stringify(d.devices);
      if (signature !== devicesSignature) {
        devicesSignature = signature;
        renderDevices(d.devices, d.deviceId);
        return;
      }
    }
    if (d.deviceId) markActiveDevice(d.deviceId);
  }

  function renderDevices(devices, currentId) {
    els.devices.textContent = '';
    if (!devices.length) {
      const empty = document.createElement('div');
      empty.className = 'empty';
      empty.textContent = '没有找到可用的输出设备';
      els.devices.appendChild(empty);
      return;
    }
    devices.forEach((dev) => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'device' + (dev.id === currentId ? ' active' : '');
      btn.dataset.id = dev.id;

      const dot = document.createElement('span');
      dot.className = 'dot';
      const name = document.createElement('span');
      name.className = 'name';
      name.textContent = dev.name;
      btn.append(dot, name);

      btn.addEventListener('click', () => {
        if (btn.classList.contains('active')) return;
        markActiveDevice(dev.id);
        send('audio.set', { id: dev.id });
      });
      els.devices.appendChild(btn);
    });
  }

  function markActiveDevice(currentId) {
    els.devices.querySelectorAll('.device').forEach((el) => {
      el.classList.toggle('active', el.dataset.id === currentId);
    });
  }

  /* ---------------------------------------------------------------- 提示 */

  let toastTimer = 0;
  function toast(text, isError) {
    els.toast.textContent = text;
    els.toast.classList.toggle('error', !!isError);
    els.toast.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => els.toast.classList.remove('show'), 1800);
  }

  /* ---------------------------------------------------------------- 音量 */

  els.volSlider.addEventListener('input', () => {
    volumeDragging = true;
    clearTimeout(volumeDragTimer);
    volumeDragTimer = setTimeout(() => { volumeDragging = false; }, 500);
    els.volValue.textContent = els.volSlider.value + '%';
    send('vol.set', { value: Number(els.volSlider.value) / 100 }, true);
  });

  els.muteBtn.addEventListener('click', () => send('vol.toggle'));

  $$('[data-vol-step]').forEach((btn) => {
    btn.addEventListener('click', () => send('vol.step', { delta: Number(btn.dataset.volStep) }));
  });

  /* ---------------------------------------------------------------- 媒体 */

  els.playBtn.addEventListener('click', () => send('media.playpause'));
  els.prevBtn.addEventListener('click', () => send('media.prev'));
  els.nextBtn.addEventListener('click', () => send('media.next'));
  // delta 单位是秒：负数是快退，正数是快进。播放器不支持的键是禁用的，
  // 原生 disabled 会直接吞掉点击，这里不用再拦一道。
  els.seekBackBtn.addEventListener('click', () => send('media.seek', { delta: -10 }));
  els.seekFwdBtn.addEventListener('click', () => send('media.seek', { delta: 10 }));
  $('#refreshAudio').addEventListener('click', () => send('audio.refresh'));

  /* ------------------------------------------------------------ 窗口/电源 */

  $$('[data-window]').forEach((btn) => {
    btn.addEventListener('click', () => send('window.move', { direction: btn.dataset.window }));
  });

  // 中间三个键对应标题栏的「—／最大化还原／✕」，动作对象是电脑上当前前台窗口
  $$('[data-win-ctl]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const action = btn.dataset.winCtl;
      // 关窗口跟点标题栏的 ✕ 一样会丢未保存的东西，先问一句。
      // 保存提示还是由那个程序自己弹，这里只是拦一道手滑。
      if (action === 'close' && !confirm('确定关闭电脑上这个窗口吗？\n没保存的内容会按那个程序自己的提示处理。')) {
        return;
      }
      send('window.' + action);
    });
  });

  function closeWindowPop() {
    els.winPop.classList.add('hidden');
    els.winPick.setAttribute('aria-expanded', 'false');
  }

  function openWindowPop(windows) {
    els.winPopList.textContent = '';
    windows.forEach((win) => {
      const item = document.createElement('button');
      item.type = 'button';
      item.className = 'win-item' + (win.current ? ' current' : '');
      item.setAttribute('role', 'option');

      const dot = document.createElement('i');
      dot.className = 'dot';
      const name = document.createElement('span');
      name.className = 'name';
      name.textContent = win.title;
      item.append(dot, name);

      item.addEventListener('click', () => {
        send('window.activate', { id: win.id });
        closeWindowPop();
      });
      els.winPopList.appendChild(item);
    });

    els.winPop.classList.remove('hidden');
    els.winPick.setAttribute('aria-expanded', 'true');
    // 贴着标题右下角展开，放不下就翻到上面，左右再夹紧进屏幕
    const anchor = els.winPick.getBoundingClientRect();
    const box = els.winPop.getBoundingClientRect();
    let left = anchor.right - box.width;
    let top = anchor.bottom + 6;
    if (top + box.height > window.innerHeight - 8) top = Math.max(8, anchor.top - box.height - 6);
    left = Math.min(Math.max(8, left), window.innerWidth - box.width - 8);
    els.winPop.style.left = left + 'px';
    els.winPop.style.top = top + 'px';
  }

  els.winPick.addEventListener('click', (ev) => {
    ev.stopPropagation();
    if (els.winPop.classList.contains('hidden')) send('window.list');
    else closeWindowPop();
  });
  els.winPop.addEventListener('click', (ev) => ev.stopPropagation());
  document.addEventListener('click', closeWindowPop);
  window.addEventListener('resize', closeWindowPop);
  document.addEventListener('scroll', (ev) => {
    if (!els.winPop.contains(ev.target)) closeWindowPop();
  }, true);

  $$('[data-power]').forEach((btn) => {
    const action = btn.dataset.power;
    btn.addEventListener('click', () => {
      if (action === 'sleep' || action === 'hibernate') {
        const label = action === 'sleep' ? '睡眠' : '休眠';
        if (!confirm(`确定让电脑${label}吗？\n${label}后需要用开机卡或电源键唤醒。`)) return;
      }
      send('power.' + action);
    });
  });

  /* ---------------------------------------------------------------- 鼠标键 */

  $$('[data-mouse]').forEach((btn) => {
    btn.addEventListener('click', () => {
      send('mouse.button', { button: btn.dataset.mouse, action: 'click' });
    });
  });

  /* -------------------------------------------------------------- 键盘输入 */

  $('#sendTextBtn').addEventListener('click', () => {
    const text = els.textInput.value;
    if (!text) { toast('先输入内容'); return; }
    if (!send('text.send', { text })) return;
    toast('已发送 ' + [...text].length + ' 个字符');
  });

  $('#clearTextBtn').addEventListener('click', () => {
    els.textInput.value = '';
    els.textInput.focus();
  });

  /* --------------------------------------------------------------- 触摸板 */

  const sensInput = $('#sens');
  const sensOutput = $('#sensValue');
  let sensitivity = Number(sensInput.value);

  sensInput.addEventListener('input', () => {
    sensitivity = Number(sensInput.value);
    sensOutput.textContent = sensitivity.toFixed(1) + '×';
  });

  // 游戏模式：移动改成发相对位移。游戏把光标 ClipCursor 锁在窗口中间时，
  // 常规那套"读坐标 + 绝对定位"的位移会被吃掉，只有相对位移能转视角。
  // 存 localStorage，免得每次进触摸板都要重开一遍。
  const padGame = $('#padGame');
  let padGameMode = localStorage.getItem('pad.game') === '1';
  padGame.checked = padGameMode;
  padGame.addEventListener('change', () => {
    padGameMode = padGame.checked;
    localStorage.setItem('pad.game', padGameMode ? '1' : '0');
  });

  function attachPad(el) {
    let gesture = null;
    let pendingDx = 0;
    let pendingDy = 0;
    let rafId = 0;

    function flushMove() {
      rafId = 0;
      const dx = Math.round(pendingDx);
      const dy = Math.round(pendingDy);
      pendingDx -= dx;
      pendingDy -= dy;
      if (dx || dy) send('mouse.move', { dx, dy, rel: padGameMode }, true);
    }

    function queueMove(dx, dy) {
      pendingDx += dx;
      pendingDy += dy;
      if (!rafId) rafId = requestAnimationFrame(flushMove);
    }

    function pointOf(touch) {
      return { x: touch.clientX, y: touch.clientY };
    }

    function midOf(touches) {
      const a = touches[0];
      const b = touches[1];
      return { x: (a.clientX + b.clientX) / 2, y: (a.clientY + b.clientY) / 2 };
    }

    el.addEventListener('touchstart', (e) => {
      e.preventDefault();
      const n = e.touches.length;
      if (!gesture) {
        gesture = { maxFingers: 0, moved: 0, started: Date.now(), fingers: 0, anchor: null, scrollAcc: 0 };
      }
      gesture.maxFingers = Math.max(gesture.maxFingers, n);
      gesture.fingers = n;
      gesture.anchor = n >= 2 ? midOf(e.touches) : pointOf(e.touches[0]);
      el.classList.add('pressed');
    }, { passive: false });

    el.addEventListener('touchmove', (e) => {
      e.preventDefault();
      if (!gesture) return;
      const n = e.touches.length;

      if (n !== gesture.fingers) {
        // 手指数量变了（比如双指变单指），重新取锚点，避免光标跳一下
        gesture.fingers = n;
        gesture.anchor = n >= 2 ? midOf(e.touches) : pointOf(e.touches[0]);
        return;
      }

      const cur = n >= 2 ? midOf(e.touches) : pointOf(e.touches[0]);
      const dx = cur.x - gesture.anchor.x;
      const dy = cur.y - gesture.anchor.y;
      gesture.anchor = cur;
      gesture.moved += Math.abs(dx) + Math.abs(dy);

      if (n >= 2) {
        // 双指滑动 = 滚轮，和触屏上的自然滚动方向一致
        gesture.scrollAcc += -dy;
        const notches = Math.trunc(gesture.scrollAcc / 20);
        if (notches) {
          gesture.scrollAcc -= notches * 20;
          send('mouse.wheel', { delta: -notches * 120 }, true);
        }
      } else {
        queueMove(dx * sensitivity, dy * sensitivity);
      }
    }, { passive: false });

    el.addEventListener('touchend', (e) => {
      e.preventDefault();
      if (e.touches.length > 0) {
        if (gesture) {
          gesture.fingers = e.touches.length;
          gesture.anchor = pointOf(e.touches[0]);
        }
        return;
      }
      const g = gesture;
      gesture = null;
      el.classList.remove('pressed');
      if (!g) return;
      // 轻点：时间短 + 几乎没移动，算一次点击；双指轻点 = 右键
      if (Date.now() - g.started < 260 && g.moved < 12) {
        send('mouse.button', { button: g.maxFingers >= 2 ? 'right' : 'left', action: 'click' });
      }
    }, { passive: false });

    el.addEventListener('touchcancel', () => {
      gesture = null;
      el.classList.remove('pressed');
    }, { passive: false });
  }

  attachPad($('#padBig'));
  // 键盘页里嵌的那块共用同一套手势和同一个灵敏度
  attachPad($('#kbdPad'));

  /* ------------------------------------------------------------ 功能键面板 */

  const keyRow = $('#keyRow');
  // 按在按键上时别让输入框失焦：一失焦手机软键盘就收起来了，连着按几下很难受。
  // 代价是浏览器不给 :active，反馈效果得自己加，否则按下去毫无动静。
  keyRow.addEventListener('pointerdown', (e) => e.preventDefault());
  keyRow.addEventListener('click', (e) => {
    const btn = e.target.closest('.key');
    if (!btn) return;
    btn.classList.add('hit');
    setTimeout(() => btn.classList.remove('hit'), 110);
    send('key.press', { key: btn.dataset.key });
  });

  /* ---------------------------------------------------------- 虚拟键盘整页 */

  const kbdArea = $('#kbdArea');
  // 这四个是"点一下锁定"的修饰键，其余键都是按住＝按下
  const KBD_MODS = new Set(['ctrl', 'shift', 'alt', 'win']);

  // 布局表，每行一个数组。元素三种写法：
  //   'a'                  键名和键帽文字都是 a，占 1 份宽
  //   ['esc', 'Esc', 1.3]  [键名, 键帽文字, 宽度权重]
  //   null                 空位（导航键簇右侧那格空着，跟真键盘一样）
  const KBD_MAIN = [
    [['esc', 'Esc', 1.3], ['grave', '`'], '1', '2', '3', '4', '5', '6', '7', '8', '9', '0',
      ['minus', '-'], ['equal', '='], ['backspace', '⌫', 2]],
    [['tab', 'Tab', 1.5], 'q', 'w', 'e', 'r', 't', 'y', 'u', 'i', 'o', 'p',
      ['lbracket', '['], ['rbracket', ']'], ['backslash', '\\', 1.5]],
    [['capslock', 'Caps', 1.8], 'a', 's', 'd', 'f', 'g', 'h', 'j', 'k', 'l',
      ['semicolon', ';'], ['quote', "'"], ['enter', 'Enter', 2.2]],
    [['shift', 'Shift', 2.3], 'z', 'x', 'c', 'v', 'b', 'n', 'm',
      ['comma', ','], ['period', '.'], ['slash', '/', 1.3]],
    [['ctrl', 'Ctrl', 1.3], ['win', 'Win', 1.2], ['alt', 'Alt', 1.2], ['space', '空格', 6]],
  ];
  const KBD_FUNC = [
    [['f1', 'F1'], ['f2', 'F2'], ['f3', 'F3'], ['f4', 'F4']],
    [['f5', 'F5'], ['f6', 'F6'], ['f7', 'F7'], ['f8', 'F8']],
    [['f9', 'F9'], ['f10', 'F10'], ['f11', 'F11'], ['f12', 'F12']],
    [['esc', 'Esc'], ['printscreen', 'PrtSc'], ['scrolllock', 'ScrLk'], ['pause', 'Pause']],
    [['insert', 'Ins'], ['home', 'Home'], ['pageup', 'PgUp'], null],
    [['delete', 'Del'], ['end', 'End'], ['pagedown', 'PgDn'], null],
    [['left', '←'], ['up', '↑'], ['down', '↓'], ['right', '→']],
  ];
  const KBD_NUMPAD = [
    [['numlock', 'NumLock'], ['numdiv', '÷'], ['nummul', '×'], ['numsub', '−']],
    [['num7', '7'], ['num8', '8'], ['num9', '9'], ['numadd', '+']],
    [['num4', '4'], ['num5', '5'], ['num6', '6'], ['numenter', 'Enter']],
    [['num1', '1'], ['num2', '2'], ['num3', '3'], ['numdot', '.']],
    [['num0', '0']],
  ];

  // 锁定中的修饰键，以及各手指正按着的普通键（pointerId -> {key, el}）
  const kbdLatched = new Set();
  const kbdHeld = new Map();

  // 键帽的"上档字符"：Shift 锁定着的时候，这些键显示它真正会打出来的那个符号。
  // 字母不在这里 —— 上档是大写，但把一堆字母全变成大写反而更难看，就没做。
  const KBD_SHIFTED = {
    '1': '!', '2': '@', '3': '#', '4': '$', '5': '%',
    '6': '^', '7': '&', '8': '*', '9': '(', '0': ')',
    '-': '_', '=': '+', '`': '~', '[': '{', ']': '}',
    '\\': '|', ';': ':', "'": '"', ',': '<', '.': '>', '/': '?',
  };

  function kbdLabel(base) {
    return kbdLatched.has('shift') ? (KBD_SHIFTED[base] || base) : base;
  }

  /// Shift 锁定状态变了之后，把已经画好的键帽文字刷一遍
  function applyShiftLabels() {
    kbdArea.querySelectorAll('.kbd-key').forEach((el) => {
      if (el.dataset.base === undefined) return;
      el.textContent = kbdLabel(el.dataset.base);
    });
  }

  function kbdKeyEl(spec) {
    // 空位：占一格宽但不画键（导航键簇右侧那格空着，跟真键盘的错位一样）
    if (spec === null) {
      const gap = document.createElement('span');
      gap.className = 'kbd-gap';
      return gap;
    }
    const [name, label, weight] = Array.isArray(spec) ? spec : [spec, spec];
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.dataset.key = name;
    // 键帽文字会随 Shift 在"本档 / 上档"之间切，所以原始文字记在 dataset 上
    btn.dataset.base = label;
    btn.className = 'kbd-key' + (KBD_MODS.has(name) ? ' mod' : '');
    btn.textContent = kbdLabel(label);
    // 长短键靠 flex 权重拉开（Backspace / Shift / 空格）
    if (weight && weight !== 1) btn.style.flexGrow = String(weight);
    return btn;
  }

  function kbdRender(tab) {
    kbdArea.textContent = '';
    const rows = tab === 'main' ? KBD_MAIN : tab === 'func' ? KBD_FUNC : KBD_NUMPAD;
    rows.forEach((row) => {
      const rowEl = document.createElement('div');
      rowEl.className = 'kbd-row';
      row.forEach((spec) => rowEl.appendChild(kbdKeyEl(spec)));
      kbdArea.appendChild(rowEl);
    });
  }

  function kbdClearUi() {
    kbdLatched.clear();
    kbdHeld.clear();
    kbdArea.querySelectorAll('.kbd-key.on').forEach((el) => el.classList.remove('on'));
    // 锁定被清掉了，键帽也要从上档字符还原本档（Shift 的显示状态就靠它）
    applyShiftLabels();
  }

  /// 离开键盘页时调用。只要还有键按着或锁着，就补一条"全部松开" ——
  /// 卡住的 Ctrl / Win 会把之后敲的每个键都变成组合键。
  function kbdReleaseIfNeeded() {
    if (!kbdLatched.size && !kbdHeld.size) return;
    kbdClearUi();
    send('key.release_all');
  }

  kbdArea.addEventListener('pointerdown', (ev) => {
    const el = ev.target.closest('.kbd-key');
    if (!el) return;
    // 挡掉默认行为，否则按住一个键滑动会变成选择文字 / 滚动页面
    ev.preventDefault();
    const name = el.dataset.key;

    if (KBD_MODS.has(name)) {
      // 修饰键：点一下锁定（等于一直按着），再点一下解锁
      if (kbdLatched.delete(name)) {
        el.classList.remove('on');
        send('key.up', { key: name }, true);
      } else {
        kbdLatched.add(name);
        el.classList.add('on');
        send('key.down', { key: name }, true);
      }
      // Shift 的锁定状态变了，整块键盘的键帽要跟着换成上档字符
      if (name === 'shift') applyShiftLabels();
      return;
    }

    kbdHeld.set(ev.pointerId, { key: name, el });
    el.classList.add('on');
    send('key.down', { key: name }, true);
  });

  function kbdReleasePointer(ev) {
    const held = kbdHeld.get(ev.pointerId);
    if (!held) return;
    kbdHeld.delete(ev.pointerId);
    held.el.classList.remove('on');
    send('key.up', { key: held.key }, true);
  }
  kbdArea.addEventListener('pointerup', kbdReleasePointer);
  kbdArea.addEventListener('pointercancel', kbdReleasePointer);

  $('#kbdReleaseBtn').addEventListener('click', () => {
    kbdClearUi();
    send('key.release_all');
  });

  $$('.kbd-tab').forEach((tab) => {
    tab.addEventListener('click', () => {
      $$('.kbd-tab').forEach((t) => t.classList.toggle('active', t === tab));
      kbdRender(tab.dataset.kbdTab);
    });
  });

  kbdRender('main');

  /* ------------------------------- 键盘 + 触摸板：排布与那根小横杆 */

  const kbdSplit = $('#kbdSplit');
  const kbdHandle = $('#kbdHandle');
  const kbdPadEl = $('#kbdPad');
  const kbdTip = $('#kbdTip');
  const kbdPadBtn = $('#kbdPadBtn');

  // 上下排至少要这么高。低于它就左右排 —— 上下排时键盘占 3/5，五行的主键区
  // 每行还要剩下 40 上下的高度才按得住。
  const KBD_STACK_MIN = 380;
  // 横杆判定区的高度 / 面板之间留的缝（要和 style.css 里的 .kbd-handle、
  // .kbd-split 对上）
  const KBD_HANDLE_SIZE = 26;
  const KBD_PANEL_GAP = 8;

  // 单行键最高多少。主键区一行 15 个键、每个才 18 上下宽，不封顶的话竖屏上
  // 会被拉成细高条，高宽比很难看。
  const KBD_MAX_ROW = 44;
  const KBD_ROW_GAP = 6;

  function keyboardRowCount() {
    const tab = document.querySelector('.kbd-tab.active');
    const id = tab ? tab.dataset.kbdTab : 'main';
    const rows = id === 'func' ? KBD_FUNC : id === 'numpad' ? KBD_NUMPAD : KBD_MAIN;
    return rows.length;
  }

  /// 键盘按"每行封顶"算出来的自然高度，多出来的地方留给触摸板（或者空着）
  function keyboardNaturalHeight() {
    const rows = keyboardRowCount();
    return rows * KBD_MAX_ROW + (rows - 1) * KBD_ROW_GAP;
  }

  // 触摸板的开关默认就是开的 —— 这一页本来就是"键盘 + 触摸板"一起用
  let kbdPadShown = true;
  let kbdPadFirst = false;

  // 换边时让两块面板滑过去，而不是啪一下跳过去。
  // 用的是 FLIP：先量旧位置 → 改布局 → 再让它从旧位置动画回新位置。
  function withFlip(apply) {
    const els = [kbdArea, kbdPadEl, kbdHandle]
      .filter((el) => !el.classList.contains('hidden'));
    const before = els.map((el) => el.getBoundingClientRect());
    apply();
    els.forEach((el, i) => {
      const after = el.getBoundingClientRect();
      const dx = before[i].left - after.left;
      const dy = before[i].top - after.top;
      if (!dx && !dy) return;
      el.style.transition = 'none';
      el.style.transform = `translate(${dx}px, ${dy}px)`;
      requestAnimationFrame(() => {
        el.style.transition = 'transform .24s cubic-bezier(.2,.7,.3,1)';
        el.style.transform = '';
        el.addEventListener('transitionend', function done() {
          el.style.transition = '';
          el.removeEventListener('transitionend', done);
        });
      });
    });
  }

  // 触摸板的手动大小（px，只算主方向）。上下排记的是高度、左右排记的是宽度，
  // 两维各记各的 —— 换个方向再换回来，还回到之前那个大小。
  // 0 = 这一维还没手动调过，用自动值。
  let kbdPadSizeV = 0;
  let kbdPadSizeH = 0;
  // 下面这几个是布局时顺手算出来给拖动用的
  let kbdPadAuto = 0;
  let kbdRest = 0;
  let kbdLayoutVertical = true;
  // 拖动时把两块限制在这个范围里，免得拖成一条缝或者把键盘挤没
  const KBD_PAD_MIN = 120;
  const KBD_KEYBOARD_MIN = 140;

  function padManual() {
    return kbdLayoutVertical ? kbdPadSizeV : kbdPadSizeH;
  }

  function setPadManual(value) {
    if (kbdLayoutVertical) {
      kbdPadSizeV = value;
    } else {
      kbdPadSizeH = value;
    }
  }

  // animate 只在"展开收起 / 换边"时给 true。打开整页那一下位置还没稳定，
  // 直接摆好就行，别播动画。
  function layoutKbdSplit(animate) {
    kbdHandle.classList.toggle('hidden', !kbdPadShown);
    kbdPadEl.classList.toggle('hidden', !kbdPadShown);
    kbdTip.classList.toggle('hidden', kbdPadShown);
    kbdPadBtn.classList.toggle('active', kbdPadShown);

    const apply = () => {
      // 方向要等它真的显示出来才量得准（隐藏时 clientHeight 是 0）
      const vertical = kbdPadShown && kbdSplit.clientHeight >= KBD_STACK_MIN;
      kbdSplit.classList.toggle('vertical', vertical);
      kbdSplit.classList.toggle('horizontal', kbdPadShown && !vertical);
      kbdSplit.classList.toggle('pad-first', kbdPadFirst);

      // 触摸板占主方向的多少是算出来写死的（不用 flex 比例），拖动才改得动
      const span = vertical ? kbdSplit.clientHeight : kbdSplit.clientWidth;
      const rest = Math.max(0, span - KBD_HANDLE_SIZE - KBD_PANEL_GAP * 2);
      const natural = keyboardNaturalHeight();
      // 自动摆法：键盘先拿 min(3/5, 自然高度)，剩下的全给触摸板
      const autoPad = vertical
        ? rest - Math.min(natural, rest * 0.6)
        : rest * 0.5;
      const maxPad = Math.max(KBD_PAD_MIN, rest - KBD_KEYBOARD_MIN);
      // 这里必须按"这一轮的方向"直接取对应那一维 —— 不能用 padManual()，
      // 它读的是上一轮的方向（触摸板隐藏时会被算成横向，把纵向的值读丢）
      const manual = vertical ? kbdPadSizeV : kbdPadSizeH;
      const padSize = Math.min(Math.max(manual > 0 ? manual : autoPad, KBD_PAD_MIN), maxPad);
      kbdLayoutVertical = vertical;
      kbdRest = rest;
      kbdPadAuto = autoPad;
      kbdPadEl.style.height = vertical ? padSize + 'px' : '';
      kbdPadEl.style.width = vertical ? '' : padSize + 'px';

      // 键盘封顶只在"它自己一个人占这块地方"或者左右排的时候做；
      // 上下排 + 触摸板在场时尺寸是用户拖出来的，不再硬压
      kbdArea.style.maxHeight = vertical && kbdPadShown ? '' : natural + 'px';
    };

    if (animate) withFlip(apply);
    else apply();
  }

  kbdPadBtn.addEventListener('click', () => {
    kbdPadShown = !kbdPadShown;
    layoutKbdSplit(true);
  });

  let kbdDragId = null;
  let kbdDragLast = 0;
  let kbdDragVertical = true;
  let kbdTapStart = null;

  kbdHandle.addEventListener('pointerdown', (ev) => {
    if (kbdDragId !== null) return;
    // 挡掉默认行为，否则按住横杆拖动会变成滚页面
    ev.preventDefault();
    kbdDragId = ev.pointerId;
    kbdDragVertical = kbdSplit.classList.contains('vertical');
    kbdDragLast = kbdDragVertical ? ev.clientY : ev.clientX;
    kbdTapStart = { x: ev.clientX, y: ev.clientY, at: Date.now() };
    // 从当前大小接着拖：这一维还没手动调过的话，先把自动值固化下来
    if (!(padManual() > 0)) setPadManual(kbdPadAuto);
    kbdHandle.classList.add('dragging');
    kbdHandle.setPointerCapture(ev.pointerId);
  });

  kbdHandle.addEventListener('pointermove', (ev) => {
    if (ev.pointerId !== kbdDragId) return;
    const pos = kbdDragVertical ? ev.clientY : ev.clientX;
    kbdDragUpdate(pos - kbdDragLast);
    kbdDragLast = pos;
  });

  /// 拖动改的是触摸板的主方向尺寸（上下排是高度、左右排是宽度）。
  /// 触摸板排在后面时，往下拖＝把它挤小（键盘变大）；排在前面时反过来。
  function kbdDragUpdate(delta) {
    const next = padManual() + (kbdPadFirst ? delta : -delta);
    const maxPad = Math.max(KBD_PAD_MIN, kbdRest - KBD_KEYBOARD_MIN);
    setPadManual(Math.min(Math.max(next, KBD_PAD_MIN), maxPad));
    layoutKbdSplit(false);
  }

  function endKbdDrag(ev) {
    if (ev.pointerId !== kbdDragId) return;
    kbdDragId = null;
    kbdHandle.classList.remove('dragging');
    // 没怎么动过就当是"点了一下" —— 点横杆是直接换到对面
    const tapped = kbdTapStart &&
      Date.now() - kbdTapStart.at < 350 &&
      Math.hypot(ev.clientX - kbdTapStart.x, ev.clientY - kbdTapStart.y) < 8;
    kbdTapStart = null;
    if (tapped) kbdPadFirst = !kbdPadFirst;
    layoutKbdSplit(true);
  }
  kbdHandle.addEventListener('pointerup', endKbdDrag);
  kbdHandle.addEventListener('pointercancel', endKbdDrag);

  // resize 是"屏幕变了要重排"，不是用户操作，别播动画
  window.addEventListener('resize', () => layoutKbdSplit(false));

  layoutKbdSplit(false);

  /* ------------------------------------------------------- 菜单与整页浮层 */

  const sheetOverlays = [$('#menuOverlay'), $('#helpOverlay')];
  const pageOverlays = [$('#padPage'), $('#screenPage'), $('#keyboardPage')];
  const allOverlays = sheetOverlays.concat(pageOverlays);
  let lockedScroll = 0;

  function showOverlay(el) {
    // 从键盘页切走（或者直接关了）时把按着的键松开，别把它们留在电脑上
    if (el !== $('#keyboardPage')) kbdReleaseIfNeeded();
    allOverlays.forEach((item) => item.classList.toggle('hidden', item !== el));
    // 锁住背后主页：body 变 position:fixed 并上移 scrollY，看着没变但滚不动了
    if (el && !document.documentElement.classList.contains('modal-open')) {
      lockedScroll = window.scrollY;
      document.body.style.top = -lockedScroll + 'px';
      document.documentElement.classList.add('modal-open');
    }
    if (el === $('#screenPage')) loadScreens();
    else stopAutoRefresh();
    // 键盘页要等显示出来才量得准高度，所以每次打开都重排一次
    if (el === $('#keyboardPage')) layoutKbdSplit();
  }

  function hideOverlays() {
    kbdReleaseIfNeeded();
    allOverlays.forEach((el) => el.classList.add('hidden'));
    stopAutoRefresh();
    if (!document.documentElement.classList.contains('modal-open')) return;
    document.documentElement.classList.remove('modal-open');
    document.body.style.top = '';
    window.scrollTo(0, lockedScroll);
  }

  $('#menuBtn').addEventListener('click', () => showOverlay($('#menuOverlay')));
  $('#closeMenuBtn').addEventListener('click', hideOverlays);
  $('#closePadBtn').addEventListener('click', hideOverlays);
  $('#closeScreenBtn').addEventListener('click', hideOverlays);
  $('#closeKeyboardBtn').addEventListener('click', hideOverlays);
  $('#closeHelpBtn').addEventListener('click', hideOverlays);

  const menuTargets = {
    pad: '#padPage',
    keyboard: '#keyboardPage',
    screen: '#screenPage',
    help: '#helpOverlay',
  };

  $$('.menu-item').forEach((item) => {
    item.addEventListener('click', () => {
      showOverlay($(menuTargets[item.dataset.page] || '#helpOverlay'));
    });
  });

  // 菜单和说明是底部浮层，点空白处退出；触摸板/屏幕整页占满，只能点关闭
  sheetOverlays.forEach((el) => {
    el.addEventListener('click', (e) => {
      if (e.target === el) hideOverlays();
    });
  });

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') hideOverlays();
  });

  /* ---------------------------------------------------------------- 屏幕 */

  const shotsBox = $('#shots');
  const shotAutoBtn = $('#shotAuto');
  let shotMonitors = [];
  let shotTimer = 0;
  let shotLoading = false;

  function shotUrl(mon) {
    // 带上时间戳，不然浏览器可能把上一张拿回来复用
    return `/api/shot?m=${mon.index}&w=1400&q=70&t=${Date.now()}`;
  }

  function showShotsMessage(text) {
    shotsBox.textContent = '';
    const empty = document.createElement('div');
    empty.className = 'empty';
    empty.textContent = text;
    shotsBox.appendChild(empty);
  }

  function renderShots() {
    shotsBox.textContent = '';
    if (!shotMonitors.length) {
      showShotsMessage('没有检测到显示器');
      return;
    }
    shotMonitors.forEach((mon, i) => {
      const title = `显示器 ${i + 1}` + (mon.primary ? '（主屏）' : '');

      const head = document.createElement('div');
      head.className = 'card-head';
      const h2 = document.createElement('h2');
      h2.textContent = title;
      const hint = document.createElement('span');
      hint.className = 'hint';
      hint.textContent = `${mon.width}×${mon.height}`;
      head.append(h2, hint);

      const img = document.createElement('img');
      img.className = 'shot-img';
      img.alt = title + ' 的画面';
      img.decoding = 'async';
      img.addEventListener('error', () => toast('抓图失败，稍后再试', true));

      const card = document.createElement('section');
      card.className = 'card';
      card.append(head, img);
      shotsBox.appendChild(card);
      img.src = shotUrl(mon);
    });
  }

  function refreshShots() {
    if (!shotMonitors.length) {
      loadScreens();
      return;
    }
    Array.from(shotsBox.querySelectorAll('img')).forEach((img, i) => {
      if (i < shotMonitors.length) img.src = shotUrl(shotMonitors[i]);
    });
  }

  async function loadScreens() {
    if (shotLoading) return;
    shotLoading = true;
    try {
      const resp = await fetch('/api/screens', { cache: 'no-store' });
      if (!resp.ok) throw new Error('HTTP ' + resp.status);
      shotMonitors = await resp.json();
      renderShots();
    } catch (err) {
      shotMonitors = [];
      showShotsMessage('取显示器列表失败：' + (err && err.message ? err.message : err));
    } finally {
      shotLoading = false;
    }
  }

  function stopAutoRefresh() {
    clearInterval(shotTimer);
    shotTimer = 0;
    shotAutoBtn.classList.remove('active');
  }

  $('#shotRefresh').addEventListener('click', refreshShots);
  shotAutoBtn.addEventListener('click', () => {
    if (shotTimer) {
      stopAutoRefresh();
      return;
    }
    shotAutoBtn.classList.add('active');
    shotTimer = setInterval(refreshShots, 2000);
  });

  /* ------------------------------------------------------------------ 启动 */

  document.addEventListener('visibilitychange', () => {
    if (!document.hidden && (!ws || ws.readyState > 1)) {
      reconnectDelay = 400;
      connect();
    }
  });

  connect();
})();
