/* Carte cadeau à gratter de René. Le code n'arrive du serveur qu'au premier grattage. */
(() => {
  'use strict';
  const $ = selector => document.querySelector(selector);
  const token = location.pathname.split('/').filter(Boolean).pop();
  const scene = $('#scene'), card = $('#card'), scratchBox = $('#scratch');
  const codeEl = $('#code'), hint = $('#hint'), statusEl = $('#status');
  const flipButton = $('#flip'), copyButton = $('#copy');
  const timerBox = $('#timer'), timerLabel = $('#timer-label'), timerValue = $('#timer-value');
  const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
  let canvas = $('#foil-canvas');
  let ctx = null;

  const s = {
    ry: -34, rx: 12, vy: 0, vx: 0, base: -34, hoverX: 0, hoverY: 0,
    dragging: false, scratching: false, requested: false, wantReveal: false,
    revealed: false, locked: false, code: null, ready: false,
  };
  const clamp = (value, min, max) => Math.min(max, Math.max(min, value));
  const facingOf = angle => { const r = ((angle % 360) + 360) % 360; return r > 90 && r < 270; };
  const facingBack = () => facingOf(s.ry);
  const settled = () => Math.abs(s.ry - s.base) < 1.5 && Math.abs(s.rx) < 1.5 && Math.abs(s.vy) < 0.4;
  const vibrate = pattern => { try { navigator.vibrate?.(pattern); } catch {} };

  /* ---------- Rotation 3D ---------- */

  function flip() {
    if (!s.ready) return;
    s.base = Math.round(s.ry / 180) * 180 + 180;
    vibrate(8);
  }

  let drag = null;
  scene.addEventListener('pointerdown', event => {
    if (event.button > 0 || !s.ready) return;
    if (canvas && event.target === canvas && facingBack() && !s.revealed && !s.locked && settled()) {
      startScratch(event);
      return;
    }
    const now = performance.now();
    drag = {id: event.pointerId, x: event.clientX, y: event.clientY, ry: s.ry, rx: s.rx, t: now, lastT: now, moved: 0};
    s.dragging = true;
    s.vy = 0;
    s.vx = 0;
    scene.setPointerCapture(event.pointerId);
    scene.classList.add('grabbing');
  });

  scene.addEventListener('pointermove', event => {
    if (s.scratching) { moveScratch(event); return; }
    if (drag && event.pointerId === drag.id) {
      const dx = event.clientX - drag.x, dy = event.clientY - drag.y;
      drag.moved = Math.max(drag.moved, Math.hypot(dx, dy));
      const now = performance.now();
      const ry = drag.ry + dx * 0.45;
      s.vy = clamp((ry - s.ry) / Math.max(1, now - drag.lastT) * 16, -40, 40);
      drag.lastT = now;
      s.ry = ry;
      s.rx = clamp(drag.rx - dy * 0.3, -30, 30);
    } else if (event.pointerType === 'mouse') {
      const rect = scene.getBoundingClientRect();
      s.hoverY = ((event.clientX - rect.left) / rect.width - 0.5) * 16;
      s.hoverX = -((event.clientY - rect.top) / rect.height - 0.5) * 12;
    }
  });

  function endDrag(event) {
    if (s.scratching) { endScratch(); return; }
    if (!drag || event.pointerId !== drag.id) return;
    const tap = drag.moved < 6 && performance.now() - drag.t < 300;
    drag = null;
    s.dragging = false;
    scene.classList.remove('grabbing');
    if (tap) { flip(); return; }
    s.base = Math.round((s.ry + s.vy * 10) / 180) * 180;
  }
  scene.addEventListener('pointerup', endDrag);
  scene.addEventListener('pointercancel', endDrag);
  scene.addEventListener('pointerleave', () => { s.hoverX = 0; s.hoverY = 0; });
  scene.addEventListener('contextmenu', event => event.preventDefault());
  scene.addEventListener('keydown', event => {
    if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); flip(); }
    if (event.key === 'ArrowLeft') s.base -= 180;
    if (event.key === 'ArrowRight') s.base += 180;
  });
  flipButton.onclick = flip;

  let lastFacing = null;
  function onFacing(back) {
    if (s.locked && !s.revealed) return;
    if (s.revealed) hint.textContent = back ? 'Ton code est prêt.' : 'Retourne la carte pour voir ton code.';
    else hint.textContent = back ? 'Gratte la zone argentée.' : 'Fais-la tourner, puis retourne-la.';
  }

  /* ---------- Paillettes ---------- */

  const flakeCanvas = $('#flakes');
  const fctx = flakeCanvas.getContext('2d');
  const SILVER = ['#eef0f4', '#d5d9e0', '#b8bdc7', '#c9ced6', '#fff8ff'];
  const HALO = ['#286EFF', '#965AFF', '#FF46AA', '#FF5F50', '#FFA53C', '#BE50FF', '#fff8ff'];
  let flakes = [];
  let hadFlakes = false;

  function sizeFlakes() {
    const ratio = Math.min(2, devicePixelRatio || 1);
    flakeCanvas.width = innerWidth * ratio;
    flakeCanvas.height = innerHeight * ratio;
    fctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  }

  function spawn(x, y, count, push = 0, palette = SILVER, power = 1) {
    if (reduced) return;
    for (let i = 0; i < count; i++) {
      flakes.push({
        x, y, life: 1,
        vx: ((Math.random() - 0.5) * 2.4 + push * 0.08) * power,
        vy: (-Math.random() * 2.2 - 0.3) * power,
        size: 1.2 + Math.random() * 2.6, r: Math.random() * 6.28, vr: (Math.random() - 0.5) * 0.4,
        color: palette[(Math.random() * palette.length) | 0],
      });
    }
    if (flakes.length > 450) flakes.splice(0, flakes.length - 450);
  }

  function drawFlakes() {
    if (!flakes.length && !hadFlakes) return;
    fctx.clearRect(0, 0, innerWidth, innerHeight);
    hadFlakes = flakes.length > 0;
    flakes = flakes.filter(f => {
      f.vy += 0.18; f.vx *= 0.99; f.x += f.vx; f.y += f.vy; f.r += f.vr; f.life -= 0.014;
      if (f.life <= 0 || f.y > innerHeight + 20) return false;
      fctx.save();
      fctx.translate(f.x, f.y);
      fctx.rotate(f.r);
      fctx.globalAlpha = f.life;
      fctx.fillStyle = f.color;
      fctx.fillRect(-f.size / 2, -f.size * 0.35, f.size, f.size * 0.7);
      fctx.restore();
      return true;
    });
  }

  /* ---------- Son : grattage et carillon ---------- */

  let audio = null;
  function ensureAudio() {
    if (audio) return audio;
    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    if (!AudioCtx) return null;
    const ac = new AudioCtx();
    const buffer = ac.createBuffer(1, ac.sampleRate * 2, ac.sampleRate);
    const data = buffer.getChannelData(0);
    for (let i = 0; i < data.length; i++) data[i] = Math.random() * 2 - 1;
    const source = ac.createBufferSource();
    source.buffer = buffer;
    source.loop = true;
    const band = ac.createBiquadFilter();
    band.type = 'bandpass'; band.frequency.value = 2600; band.Q.value = 0.9;
    const high = ac.createBiquadFilter();
    high.type = 'highpass'; high.frequency.value = 900;
    const gain = ac.createGain();
    gain.gain.value = 0;
    source.connect(band).connect(high).connect(gain).connect(ac.destination);
    source.start();
    audio = {ac, band, gain};
    return audio;
  }
  function scratchSound(speed) {
    if (!audio) return;
    const t = audio.ac.currentTime;
    audio.gain.gain.setTargetAtTime(Math.min(0.22, speed * 0.09), t, 0.012);
    audio.band.frequency.setTargetAtTime(1800 + Math.min(2600, speed * 900), t, 0.03);
  }
  function silence() {
    if (audio) audio.gain.gain.setTargetAtTime(0, audio.ac.currentTime, 0.03);
  }
  function chime() {
    if (!audio) return;
    const {ac} = audio;
    [1318.5, 1975.5, 2637].forEach((frequency, index) => {
      const osc = ac.createOscillator();
      const gain = ac.createGain();
      const t = ac.currentTime + index * 0.09;
      osc.type = 'sine';
      osc.frequency.value = frequency;
      gain.gain.setValueAtTime(0, t);
      gain.gain.linearRampToValueAtTime(0.07, t + 0.015);
      gain.gain.exponentialRampToValueAtTime(0.0001, t + 1.4);
      osc.connect(gain).connect(ac.destination);
      osc.start(t);
      osc.stop(t + 1.5);
    });
  }

  /* ---------- Grattage ---------- */

  function setupCanvas() {
    if (!canvas) return;
    const ratio = Math.min(2, devicePixelRatio || 1);
    const w = scratchBox.offsetWidth, h = scratchBox.offsetHeight;
    if (!w || !h) return;
    canvas.width = Math.round(w * ratio);
    canvas.height = Math.round(h * ratio);
    ctx = canvas.getContext('2d', {willReadFrequently: true});
    const W = canvas.width, H = canvas.height;
    const silver = ctx.createLinearGradient(0, 0, W, H);
    [[0, '#e9ebf0'], [0.35, '#b8bdc7'], [0.55, '#f4f5f8'], [0.8, '#a9afba'], [1, '#d7dae1']].forEach(([o, c]) => silver.addColorStop(o, c));
    ctx.fillStyle = silver;
    ctx.fillRect(0, 0, W, H);
    const halo = ctx.createLinearGradient(0, 0, W, 0);
    HALO.slice(0, 6).forEach((c, i) => halo.addColorStop(i / 5, c));
    ctx.globalCompositeOperation = 'overlay';
    ctx.globalAlpha = 0.18;
    ctx.fillStyle = halo;
    ctx.fillRect(0, 0, W, H);
    ctx.globalAlpha = 1;
    ctx.globalCompositeOperation = 'source-over';
    for (let i = 0; i < (W * H) / 40; i++) {
      ctx.fillStyle = Math.random() < 0.5 ? 'rgba(255,255,255,.2)' : 'rgba(0,0,0,.07)';
      ctx.fillRect(Math.random() * W, Math.random() * H, 1.3, 1.3);
    }
    ctx.strokeStyle = 'rgba(255,255,255,.13)';
    ctx.lineWidth = 1;
    for (let x = -H; x < W; x += 6 * ratio) {
      ctx.beginPath(); ctx.moveTo(x, H); ctx.lineTo(x + H, 0); ctx.stroke();
    }
    ctx.fillStyle = 'rgba(70,72,86,.55)';
    ctx.font = `600 ${Math.round(H * 0.24)}px -apple-system, "SF Pro Text", system-ui, sans-serif`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    if ('letterSpacing' in ctx) ctx.letterSpacing = `${Math.round(H * 0.06)}px`;
    ctx.fillText('GRATTE ICI', W / 2, H / 2);
    ctx.font = `${Math.round(H * 0.2)}px system-ui, sans-serif`;
    ctx.fillText('✦', W * 0.1, H / 2);
    ctx.fillText('✦', W * 0.9, H / 2);
  }

  let lastPoint = null, lastMoveTime = 0, lastVibe = 0, moves = 0;

  function canvasPoint(event) {
    const rect = canvas.getBoundingClientRect();
    return {x: (event.clientX - rect.left) * canvas.width / rect.width,
            y: (event.clientY - rect.top) * canvas.height / rect.height,
            cx: event.clientX, cy: event.clientY, t: event.timeStamp || performance.now()};
  }

  function scrape(from, to) {
    const H = canvas.height;
    ctx.globalCompositeOperation = 'destination-out';
    ctx.globalAlpha = 1;
    ctx.strokeStyle = '#000';
    ctx.fillStyle = '#000';
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    ctx.lineWidth = H * 0.34;
    ctx.beginPath();
    ctx.moveTo(from.x, from.y);
    ctx.lineTo(to.x, to.y);
    ctx.stroke();
    // Bords irréguliers, comme une vraie pellicule qui s'arrache.
    const steps = Math.max(1, Math.round(Math.hypot(to.x - from.x, to.y - from.y) / 6));
    for (let i = 0; i < steps; i++) {
      const k = i / steps;
      const x = from.x + (to.x - from.x) * k, y = from.y + (to.y - from.y) * k;
      const angle = Math.random() * 6.28, dist = H * 0.17 + Math.random() * H * 0.05;
      ctx.beginPath();
      ctx.arc(x + Math.cos(angle) * dist, y + Math.sin(angle) * dist, H * (0.02 + Math.random() * 0.03), 0, 6.28);
      ctx.fill();
    }
    ctx.globalCompositeOperation = 'source-over';
  }

  function startScratch(event) {
    s.scratching = true;
    ensureAudio()?.ac.resume?.();
    scene.setPointerCapture(event.pointerId);
    lastPoint = canvasPoint(event);
    scrape(lastPoint, {...lastPoint, x: lastPoint.x + 0.1});
    spawn(lastPoint.cx, lastPoint.cy, 4);
    hint.style.opacity = 0.4;
    lastMoveTime = performance.now();
  }

  function moveScratch(event) {
    if (!ctx || !lastPoint) return;
    const events = event.getCoalescedEvents ? event.getCoalescedEvents() : [event];
    for (const item of events.length ? events : [event]) {
      const point = canvasPoint(item);
      const distance = Math.hypot(point.cx - lastPoint.cx, point.cy - lastPoint.cy);
      if (distance < 0.5) continue;
      scrape(lastPoint, point);
      const dt = Math.max(1, point.t - lastPoint.t);
      scratchSound(distance / dt);
      spawn(point.cx, point.cy, Math.min(6, Math.ceil(distance / 4)), point.cx - lastPoint.cx);
      lastPoint = point;
    }
    const now = performance.now();
    lastMoveTime = now;
    if (now - lastVibe > 45) { vibrate(4); lastVibe = now; }
    if (++moves % 6 === 0) measure();
  }

  function endScratch() {
    s.scratching = false;
    lastPoint = null;
    silence();
    hint.style.opacity = 1;
    measure();
  }

  function measure() {
    if (!ctx || s.revealed) return;
    const {width, height} = canvas;
    const data = ctx.getImageData(0, 0, width, height).data;
    const step = 8;
    let clear = 0, total = 0;
    for (let y = 0; y < height; y += step) {
      for (let x = 0; x < width; x += step) {
        total++;
        if (data[(y * width + x) * 4 + 3] < 32) clear++;
      }
    }
    const ratio = clear / total;
    if (!s.requested && ratio > 0.015) requestCode();
    if (ratio >= 0.58) { s.wantReveal = true; tryReveal(); }
  }

  async function requestCode() {
    s.requested = true;
    try {
      const response = await fetch(`/api/cadeau/${token}/scratch`, {
        method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}', cache: 'no-store',
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.error || 'René n’arrive pas à lire cette carte.');
      if (data.status === 'expired' || !data.code) { showExpired(); return; }
      s.code = data.code;
      codeEl.classList.remove('loading');
      codeEl.textContent = data.code;
      startTimer(data.remaining);
      tryReveal();
    } catch (error) {
      s.requested = false;
      s.locked = true;
      s.scratching = false;
      silence();
      statusEl.textContent = `${error.message} Recharge la page.`;
    }
  }

  function tryReveal() {
    if (s.wantReveal && s.code && !s.revealed) reveal();
  }

  function reveal() {
    s.revealed = true;
    s.scratching = false;
    silence();
    scene.classList.add('dim');
    setTimeout(() => {
      scene.classList.remove('dim');
      scene.classList.add('burst');
      if (canvas) canvas.style.opacity = 0;
      scratchBox.classList.add('revealed');
      chime();
      vibrate([18, 40, 28]);
      const rect = scratchBox.getBoundingClientRect();
      spawn(rect.left + rect.width / 2, rect.top + rect.height / 2, 80, 0, HALO, 1.8);
      setTimeout(() => scene.classList.remove('burst'), 900);
      setTimeout(() => { canvas?.remove(); canvas = null; }, 900);
    }, reduced ? 0 : 240);
    copyButton.classList.remove('hidden');
    onFacing(true);
  }

  /* ---------- Décompte de 24 h ---------- */

  let endAt = null, lastTimerText = '';
  function startTimer(remaining) {
    endAt = performance.now() + Math.max(0, remaining || 0) * 1000;
    timerLabel.textContent = 'Valable encore';
  }
  function updateTimer(now) {
    if (endAt === null) return;
    const left = Math.max(0, endAt - now);
    const total = Math.ceil(left / 1000);
    const text = [Math.floor(total / 3600), Math.floor(total / 60) % 60, total % 60]
      .map(n => String(n).padStart(2, '0')).join(':');
    if (text !== lastTimerText) { timerValue.textContent = text; lastTimerText = text; }
    if (left <= 0) showExpired();
  }

  function showExpired() {
    endAt = null;
    s.code = null;
    s.locked = true;
    s.scratching = false;
    silence();
    canvas?.remove();
    canvas = null;
    codeEl.className = 'code expired';
    codeEl.textContent = 'Code expiré';
    timerBox.classList.add('expired');
    timerLabel.textContent = 'Ce code a expiré';
    timerValue.textContent = '00:00:00';
    copyButton.classList.add('hidden');
    hint.textContent = 'Demande une nouvelle carte au staff.';
  }

  copyButton.onclick = async () => {
    if (!s.code) return;
    try {
      await navigator.clipboard.writeText(s.code);
      copyButton.textContent = 'Copié ✓';
      vibrate(10);
    } catch {
      const range = document.createRange();
      range.selectNodeContents(codeEl);
      getSelection().removeAllRanges();
      getSelection().addRange(range);
      copyButton.textContent = 'Code sélectionné';
    }
    setTimeout(() => { copyButton.textContent = 'Copier le code'; }, 1600);
  };

  /* ---------- Boucle d'animation ---------- */

  function frame(now) {
    if (!s.dragging) {
      const still = (facingOf(s.base) && !s.revealed) || s.scratching;
      const targetY = s.base + (still ? 0 : s.hoverY);
      const targetX = still ? 0 : s.hoverX;
      s.vy += (targetY - s.ry) * 0.06; s.vy *= 0.82; s.ry += s.vy;
      s.vx += (targetX - s.rx) * 0.06; s.vx *= 0.82; s.rx += s.vx;
    }
    card.style.transform = `rotateX(${s.rx.toFixed(2)}deg) rotateY(${s.ry.toFixed(2)}deg)`;
    const offset = s.ry - Math.round(s.ry / 180) * 180;
    card.style.setProperty('--mx', `${(50 - offset * 1.6).toFixed(1)}%`);
    card.style.setProperty('--my', `${(32 + s.rx * 2).toFixed(1)}%`);
    card.style.setProperty('--shift', `${(50 + offset * 1.2 + s.rx * 0.8).toFixed(1)}%`);
    const back = facingBack();
    if (back !== lastFacing) { lastFacing = back; onFacing(back); }
    if (s.scratching && now - lastMoveTime > 60) silence();
    drawFlakes();
    updateTimer(now);
    requestAnimationFrame(frame);
  }

  /* ---------- Chargement ---------- */

  function intro(showBack) {
    setTimeout(() => {
      scene.classList.add('ready');
      s.ready = true;
      s.base = 0;
      if (showBack) setTimeout(() => { s.base = 180; }, reduced ? 0 : 1300);
    }, reduced ? 0 : 520);
  }

  function apply(data) {
    $('#name').textContent = data.recipient || 'toi';
    $('#guild').textContent = data.guild || '';
    $('#reason').textContent = data.reason ? `« ${data.reason} »` : '';
    if (data.status === 'expired') {
      showExpired();
      intro(true);
    } else if (data.code) {
      s.code = data.code;
      s.revealed = true;
      canvas?.remove();
      canvas = null;
      codeEl.classList.remove('loading');
      codeEl.textContent = data.code;
      scratchBox.classList.add('done');
      copyButton.classList.remove('hidden');
      startTimer(data.remaining);
      intro(true);
    } else {
      setupCanvas();
      intro(false);
    }
  }

  async function load() {
    try {
      const response = await fetch(`/api/cadeau/${token}`, {cache: 'no-store'});
      const data = await response.json().catch(() => ({}));
      if (response.status === 503) {
        statusEl.textContent = 'René se réveille. Nouvelle tentative dans un instant…';
        setTimeout(load, 5000);
        return;
      }
      statusEl.textContent = '';
      if (!response.ok) {
        $('#name').textContent = '…';
        s.locked = true;
        hint.textContent = '';
        flipButton.classList.add('hidden');
        statusEl.textContent = data.error || 'Cette carte n’existe pas.';
        intro(false);
        return;
      }
      apply(data);
    } catch {
      statusEl.textContent = 'Connexion impossible. Nouvelle tentative…';
      setTimeout(load, 5000);
    }
  }

  addEventListener('resize', () => {
    sizeFlakes();
    if (canvas && !s.requested && !s.scratching) setupCanvas();
  });
  sizeFlakes();
  requestAnimationFrame(frame);
  load();
})();
