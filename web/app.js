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
      if (dx || dy) send('mouse.move', { dx, dy }, true);
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

  /* ------------------------------------------------------- 菜单与整页浮层 */

  const sheetOverlays = [$('#menuOverlay'), $('#helpOverlay')];
  const pageOverlays = [$('#padPage'), $('#screenPage')];
  const allOverlays = sheetOverlays.concat(pageOverlays);
  let lockedScroll = 0;

  function showOverlay(el) {
    allOverlays.forEach((item) => item.classList.toggle('hidden', item !== el));
    // 锁住背后主页：body 变 position:fixed 并上移 scrollY，看着没变但滚不动了
    if (el && !document.documentElement.classList.contains('modal-open')) {
      lockedScroll = window.scrollY;
      document.body.style.top = -lockedScroll + 'px';
      document.documentElement.classList.add('modal-open');
    }
    if (el === $('#screenPage')) loadScreens();
    else stopAutoRefresh();
  }

  function hideOverlays() {
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
  $('#closeHelpBtn').addEventListener('click', hideOverlays);

  $$('.menu-item').forEach((item) => {
    item.addEventListener('click', () => {
      const target = $(item.dataset.page === 'pad' ? '#padPage'
        : item.dataset.page === 'screen' ? '#screenPage' : '#helpOverlay');
      showOverlay(target);
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
