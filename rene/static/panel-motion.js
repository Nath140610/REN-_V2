/* Mouvements et vibrations du panel René.
   DA : un seul geste à la fois, accélérations naturelles, jamais de saut ni de clignotement.
   Les vibrations suivent le sens de l'action (sélection, succès, erreur, danger…). */
(() => {
  'use strict';
  const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;

  /* ---------- Vibrations ---------- */

  const PATTERNS = {
    tap: [25],
    tick: [22],
    select: [32],
    toggleOn: [30, 60, 40],
    toggleOff: [30],
    open: [25, 50, 35],
    close: [25],
    success: [40, 70, 60],
    error: [70, 60, 70, 60, 70],
    warning: [55, 80, 55],
    danger: [90],
    notify: [35, 90, 35, 90, 50],
    longPress: [60],
    refresh: [28, 50, 28],
  };
  const LEVELS = {light: 0.75, normal: 1, strong: 1.6};
  const MIN_PULSE = 20;
  let lastHaptic = 0;
  const diagnostics = {api: typeof navigator.vibrate === 'function', lastResult: null, calls: 0};

  function settings() {
    try {
      return {on: localStorage.getItem('rene_haptics') !== 'off',
              level: localStorage.getItem('rene_haptics_level') || 'normal',
              sound: localStorage.getItem('rene_touch_sound') === 'on'};
    } catch { return {on: true, level: 'normal', sound: false}; }
  }

  /* ---------- Retour sonore (pour les tablettes sans moteur de vibration) ---------- */

  let audio = null;
  function audioContext() {
    if (audio) return audio;
    const Context = window.AudioContext || window.webkitAudioContext;
    if (!Context) return null;
    audio = new Context();
    return audio;
  }
  // Le navigateur n'autorise le son qu'après un toucher : on débloque au premier appui.
  addEventListener('pointerdown', () => { if (settings().sound) audioContext()?.resume?.(); }, {passive: true});

  function click(ac, at, length, frequency, volume) {
    const osc = ac.createOscillator();
    const gain = ac.createGain();
    osc.type = 'sine';
    osc.frequency.setValueAtTime(frequency, at);
    osc.frequency.exponentialRampToValueAtTime(frequency * 0.55, at + length);
    gain.gain.setValueAtTime(0.0001, at);
    gain.gain.exponentialRampToValueAtTime(volume, at + 0.004);
    gain.gain.exponentialRampToValueAtTime(0.0001, at + length);
    osc.connect(gain).connect(ac.destination);
    osc.start(at);
    osc.stop(at + length + 0.02);
  }

  // Chaque impulsion devient un « toc » doux ; succès et erreur ont leur propre tonalité.
  function sound(name, steps, level) {
    const ac = audioContext();
    if (!ac || ac.state !== 'running') return;
    const volume = {light: 0.05, normal: 0.09, strong: 0.16}[level] || 0.09;
    const tone = {success: 1320, error: 330, danger: 260, warning: 520, notify: 990}[name] || 1700;
    let at = ac.currentTime + 0.005;
    steps.forEach((ms, i) => {
      if (i % 2 === 0) click(ac, at, Math.min(0.09, Math.max(0.025, ms / 1000)), name === 'success' && i ? tone * 1.5 : tone, volume);
      at += ms / 1000;
    });
  }

  function toPattern(pattern) {
    if (typeof pattern === 'string') return PATTERNS[pattern] || PATTERNS.tap;
    if (typeof pattern === 'number') return [pattern];
    return Array.isArray(pattern) ? pattern : PATTERNS.tap;
  }

  // Remplace haptic() de panel-extra.js : premier geste prioritaire, intensité réglable.
  function vibrate(pattern = 'select', force = false) {
    const {on, level, sound: withSound} = settings();
    if (!on && !force) return;
    const now = performance.now();
    // Le clic générique arrive juste après le geste précis : on garde le premier.
    if (!force && now - lastHaptic < 70) return;
    lastHaptic = now;
    const scale = LEVELS[level] || 1;
    const name = typeof pattern === 'string' ? pattern : 'tap';
    const steps = toPattern(pattern).map((ms, i) => i % 2 ? ms : Math.min(150, Math.max(MIN_PULSE, Math.round(ms * scale))));
    if (diagnostics.api) {
      try {
        diagnostics.lastResult = navigator.vibrate(steps);
        diagnostics.calls += 1;
      } catch { diagnostics.lastResult = false; }
    }
    if (withSound) sound(name, steps, level);
  }
  haptic = vibrate;
  window.reneHaptic = vibrate;

  // Chaque message suit son sens : succès ou erreur.
  const noticeBase = notice;
  notice = (text, bad = false) => {
    vibrate(bad ? 'error' : 'success');
    noticeBase(text, bad);
    const box = $('#notice');
    box.classList.remove('pop');
    void box.offsetWidth;
    box.classList.add('pop');
  };

  /* ---------- Gestes du quotidien ---------- */

  document.addEventListener('change', event => {
    const target = event.target;
    if (target.matches?.('input.switch')) vibrate(target.checked ? 'toggleOn' : 'toggleOff');
    else if (target.matches?.('select')) vibrate('select');
  }, true);

  document.addEventListener('click', event => {
    const button = event.target.closest?.('button, [role=button], .list-row, .member-row');
    if (!button) return;
    if (button.closest('.segmented')) vibrate('tick');
    else if (button.matches('.button.danger, .mini.ban, .danger-text, #restart-bot')) vibrate('danger');
    else if (button.matches('.picker-option, .reward-option, .chip-remove')) vibrate('select');
    else if (button.matches('.member-row, #gift-list .list-row, [data-action]')) vibrate('open');
  }, true);

  // Appui visuel immédiat sur tablette (avant même le relâchement).
  document.addEventListener('pointerdown', event => {
    const target = event.target.closest?.('.tab, .button, .mini, .nav, .group-row, .list-row, .member-row, .prompt, .chip, .icon-button, .segmented button');
    if (!target) return;
    target.classList.add('pressed');
    const release = () => { target.classList.remove('pressed'); window.removeEventListener('pointerup', release); window.removeEventListener('pointercancel', release); };
    window.addEventListener('pointerup', release);
    window.addEventListener('pointercancel', release);
  }, {passive: true});

  // Appui long sur un membre : ouvre directement sa fiche.
  let pressTimer = null;
  document.addEventListener('pointerdown', event => {
    const row = event.target.closest?.('.member-row');
    if (!row || event.pointerType === 'mouse') return;
    clearTimeout(pressTimer);
    pressTimer = setTimeout(() => { vibrate('longPress', true); row.click(); }, 480);
    const cancel = () => { clearTimeout(pressTimer); row.removeEventListener('pointerup', cancel); row.removeEventListener('pointerleave', cancel); };
    row.addEventListener('pointerup', cancel);
    row.addEventListener('pointerleave', cancel);
  }, {passive: true});

  /* ---------- Démarrage, connexion et changement de page ---------- */

  const started = performance.now();
  const showBase = show;
  show = id => {
    const boot = $('#boot');
    const login = $('#login');
    if (id !== 'boot' && !boot.classList.contains('hidden')) {
      // HELLO : on laisse le point blanc s'éveiller et la lumière courir avant de partir.
      const wait = reduced ? 0 : Math.max(0, 1700 - (performance.now() - started));
      setTimeout(() => {
        boot.classList.add('leaving');
        setTimeout(() => { boot.classList.remove('leaving'); showBase(id); enterPage(); }, reduced ? 0 : 520);
      }, wait);
      return;
    }
    if (id === 'app' && !login.classList.contains('hidden')) {
      vibrate('success', true);
      login.classList.add('leaving');
      setTimeout(() => { login.classList.remove('leaving'); showBase(id); enterPage(); }, reduced ? 0 : 480);
      return;
    }
    showBase(id);
  };

  function enterPage() {
    document.body.dataset.entering = '1';
    clearTimeout(enterPage.timer);
    enterPage.timer = setTimeout(() => { delete document.body.dataset.entering; }, 1400);
    requestAnimationFrame(updateAllThumbs);
  }

  const navigateBase = navigate;
  navigate = view => {
    if (view === state.view && !$(`#view-${view}`)?.classList.contains('hidden')) {
      vibrate('tick');
      return;
    }
    vibrate('select');
    const run = () => { navigateBase(view); enterPage(); };
    if (document.startViewTransition && !reduced) document.startViewTransition(run);
    else run();
  };
  for (const button of document.querySelectorAll('[data-view]')) button.onclick = () => navigate(button.dataset.view);
  for (const button of document.querySelectorAll('[data-go]')) button.onclick = () => navigate(button.dataset.go);

  /* ---------- Actualiser ---------- */

  const refreshBase = refresh;
  refresh = async () => {
    const button = $('#refresh');
    button.classList.add('spinning');
    try { await refreshBase(); } finally {
      setTimeout(() => button.classList.remove('spinning'), 350);
    }
  };
  $('#refresh').onclick = () => { vibrate('refresh'); enterPage(); refresh(); };

  /* ---------- Chiffres qui comptent (jamais de saut) ---------- */

  const numberFormat = new Intl.NumberFormat('fr-FR');
  const parseNumber = text => {
    const match = /^([+-]?)(\d(?:[\d\s  ]*\d)?)(,\d+)?(.*)$/.exec(text.trim());
    if (!match) return null;
    const value = Number(match[2].replace(/[\s  ]/g, '') + (match[3] ? match[3].replace(',', '.') : ''));
    return Number.isFinite(value) ? {sign: match[1], value, decimals: match[3] ? match[3].length - 1 : 0, suffix: match[4]} : null;
  };

  function countUp(strong) {
    const node = strong.firstChild;
    if (!node || node.nodeType !== Node.TEXT_NODE) return;
    const parsed = parseNumber(node.textContent);
    const key = strong.closest('[id]')?.id + '|' + strong.closest('.metric')?.querySelector('.label')?.firstChild?.textContent;
    if (!parsed) return;
    const from = countUp.memory.get(key) ?? 0;
    countUp.memory.set(key, parsed.value);
    if (reduced || from === parsed.value) return;
    const duration = 900, begin = performance.now();
    const ease = t => 1 - Math.pow(1 - t, 3);
    const step = now => {
      const t = Math.min(1, (now - begin) / duration);
      const current = from + (parsed.value - from) * ease(t);
      const shown = parsed.decimals ? current.toFixed(parsed.decimals).replace('.', ',') : numberFormat.format(Math.round(current));
      node.textContent = `${parsed.sign}${shown}${parsed.suffix}`;
      if (t < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }
  countUp.memory = new Map();

  /* ---------- Entrées en douceur des listes, cartes et graphiques ---------- */

  const ROW = '.list-row, .member-row, .top-row, .audit-row, .gift-row, .presence-row, .ticket, .poll-card, .metric, .chip';
  const observer = new MutationObserver(records => {
    for (const record of records) {
      record.addedNodes.forEach(added => {
        if (!(added instanceof Element)) return;
        if (added.matches(ROW)) {
          const index = Array.prototype.indexOf.call(added.parentNode?.children || [], added);
          added.style.setProperty('--i', Math.min(index, 14));
        }
        if (added.matches('.metric')) { const strong = added.querySelector('strong'); if (strong) countUp(strong); }
        added.querySelectorAll?.('path[stroke]').forEach(path => {
          path.setAttribute('pathLength', '1');
          path.classList.add('draw');
        });
      });
    }
  });
  observer.observe($('#app'), {childList: true, subtree: true});

  /* ---------- Contrôles segmentés : la pastille glisse ---------- */

  // Un contrôle caché (fiche fermée, page inactive) n'a pas de taille : on replace la pastille
  // dès qu'il devient visible.
  const thumbSizes = 'ResizeObserver' in window
    ? new ResizeObserver(entries => entries.forEach(entry => updateThumb(entry.target)))
    : null;

  function updateThumb(control) {
    let thumb = control.querySelector(':scope > .seg-thumb');
    const active = control.querySelector(':scope > button.active');
    const fresh = !thumb || thumb.dataset.placed !== '1';
    if (!thumb) {
      thumb = document.createElement('span');
      thumb.className = 'seg-thumb';
      control.prepend(thumb);
      control.classList.add('has-thumb');
      thumbSizes?.observe(control);
    }
    if (!active || !control.offsetWidth) { thumb.style.opacity = 0; thumb.dataset.placed = ''; return; }
    if (fresh) thumb.style.transition = 'none';
    thumb.style.opacity = 1;
    thumb.style.width = `${active.offsetWidth}px`;
    thumb.style.height = `${active.offsetHeight}px`;
    thumb.style.transform = `translate(${active.offsetLeft}px, ${active.offsetTop}px)`;
    if (fresh) { void thumb.offsetWidth; thumb.style.transition = ''; thumb.dataset.placed = '1'; }
  }
  function updateAllThumbs() { document.querySelectorAll('.segmented').forEach(updateThumb); }
  const segmentObserver = new MutationObserver(records => {
    const controls = new Set();
    for (const record of records) {
      const control = record.target.closest?.('.segmented') || (record.target.matches?.('.segmented') && record.target);
      if (control) controls.add(control);
      record.addedNodes?.forEach(node => node.querySelectorAll?.('.segmented').forEach(c => controls.add(c)));
    }
    controls.forEach(control => requestAnimationFrame(() => updateThumb(control)));
  });
  segmentObserver.observe(document.body, {subtree: true, childList: true, attributes: true, attributeFilter: ['class']});
  addEventListener('resize', () => requestAnimationFrame(updateAllThumbs));
  requestAnimationFrame(updateAllThumbs);

  /* ---------- Fiches : elles descendent avant de disparaître ---------- */

  function closing(selector, base) {
    return (...args) => {
      const dialog = $(selector);
      if (dialog.classList.contains('hidden') || reduced) { base(...args); return; }
      vibrate('close');
      dialog.classList.add('closing');
      setTimeout(() => { dialog.classList.remove('closing'); base(...args); }, 260);
    };
  }
  closeMemberSheet = closing('#member-sheet', closeMemberSheet);
  closeGiftSheet = closing('#gift-sheet', closeGiftSheet);
  $('#sheet-close').onclick = () => closeMemberSheet();
  $('#member-sheet').onclick = event => { if (event.target.id === 'member-sheet') closeMemberSheet(); };
  $('#gift-sheet-close').onclick = () => closeGiftSheet();
  $('#gift-sheet').onclick = event => { if (event.target.id === 'gift-sheet') closeGiftSheet(); };

  const openSheetBase = openMemberSheet;
  openMemberSheet = member => { vibrate('open'); openSheetBase(member); };
  const showPaneBase = showPane;
  showPane = name => {
    showPaneBase(name);
    const pane = document.querySelector(`#member-sheet [data-pane="${name}"]`);
    if (name === 'ban' || name === 'tempban') vibrate('warning');
    pane?.classList.remove('slide-in');
    void pane?.offsetWidth;
    pane?.classList.add('slide-in');
  };

  /* ---------- Moments forts : un éclat de halo, puis le calme ---------- */

  const halo = document.createElement('div');
  halo.className = 'halo-sweep';
  halo.setAttribute('aria-hidden', 'true');
  document.body.append(halo);
  function haloMoment() {
    if (reduced) return;
    halo.classList.remove('run');
    void halo.offsetWidth;
    halo.classList.add('run');
  }
  window.reneHalo = haloMoment;

  // Cadeau confirmé, sondage publié, envoi à tous lancé, gain enregistré.
  const confirmQrMotion = confirmQr;
  confirmQr = async text => {
    const before = qrChallenge;
    await confirmQrMotion(text);
    if (before && !qrChallenge) haloMoment();
  };
  const withButtonBase = withButton;
  withButton = async (button, action) => {
    const result = await withButtonBase(button, action);
    if (result && button?.matches?.('#poll-form button[type=submit], #broadcast-form button[type=submit], #gift-reward-save, #confirm-warn')) {
      if (!button.matches('#confirm-warn')) haloMoment();
    }
    return result;
  };

  /* ---------- Nouveautés en direct : une vibration discrète ---------- */

  const counters = new Map();
  function watchBadge(selector) {
    const badge = $(selector);
    new MutationObserver(() => {
      const value = badge.classList.contains('hidden') ? 0 : parseInt(badge.textContent, 10) || 0;
      const previous = counters.get(selector) ?? value;
      counters.set(selector, value);
      if (value > previous) {
        vibrate('notify', true);
        badge.classList.remove('bump');
        void badge.offsetWidth;
        badge.classList.add('bump');
      }
    }).observe(badge, {childList: true, characterData: true, subtree: true, attributes: true, attributeFilter: ['class']});
  }
  watchBadge('#ticket-badge');
  watchBadge('#assist-badge');

  // Sondages : un léger tic quand de nouveaux votes arrivent.
  const pollVotes = new Map();
  new MutationObserver(() => {
    if (state.view !== 'polls' || document.hidden) return;
    let changed = false;
    document.querySelectorAll('#poll-list .poll-card').forEach(card => {
      const text = card.querySelector('.poll-meta')?.textContent || '';
      const votes = parseInt(text.split('·')[1], 10) || 0;
      const key = card.querySelector('a')?.href;
      if (key && pollVotes.has(key) && pollVotes.get(key) < votes) changed = true;
      if (key) pollVotes.set(key, votes);
    });
    if (changed) vibrate('tick', true);
  }).observe($('#poll-list'), {subtree: true, characterData: true, childList: true});

  /* ---------- Réglages des vibrations ---------- */

  const levelControl = $('#haptic-level');
  function renderLevel() {
    const {on, level} = settings();
    for (const button of levelControl.querySelectorAll('button')) button.classList.toggle('active', button.dataset.level === level);
    levelControl.classList.toggle('disabled', !on);
    $('#haptic-test').disabled = !on && !settings().sound;
  }
  for (const button of levelControl.querySelectorAll('button')) {
    button.onclick = () => {
      try { localStorage.setItem('rene_haptics_level', button.dataset.level); } catch {}
      renderLevel();
      vibrate('success', true);
    };
  }
  $('#haptic-toggle').onchange = event => {
    try { localStorage.setItem('rene_haptics', event.target.checked ? 'on' : 'off'); } catch {}
    renderLevel();
    if (event.target.checked) vibrate('toggleOn', true);
  };
  function diagnose() {
    const activated = navigator.userActivation ? navigator.userActivation.hasBeenActive : true;
    if (!diagnostics.api) {
      return 'Ce navigateur ne gère pas les vibrations. Ouvre le panel dans Chrome ou Samsung Internet, ou active le retour sonore.';
    }
    if (!activated) return 'Touche l’écran une fois : le navigateur n’autorise les vibrations qu’après un premier toucher.';
    if (diagnostics.lastResult === false) {
      return 'Le navigateur a refusé la vibration. Vérifie que le mode économie d’énergie ou « Ne pas déranger » ne coupe pas les vibrations, puis réessaie.';
    }
    return 'Le signal a bien été envoyé à la tablette. Si tu n’as rien senti, ta tablette n’a sans doute pas de moteur de vibration '
      + '(c’est le cas de la plupart des Galaxy Tab : regarde dans Paramètres → Sons et vibrations s’il existe une intensité des vibrations) '
      + 'ou les vibrations sont coupées dans Android. Active alors le retour sonore.';
  }

  $('#haptic-test').onclick = () => {
    if (settings().sound) audioContext()?.resume?.();
    const sequence = ['select', 'success', 'warning', 'error'];
    sequence.forEach((name, i) => setTimeout(() => vibrate(name, true), i * 700));
    setTimeout(() => { $('#haptic-support').textContent = diagnose(); }, 120);
  };

  const soundToggle = $('#sound-toggle');
  soundToggle.checked = settings().sound;
  soundToggle.onchange = () => {
    try { localStorage.setItem('rene_touch_sound', soundToggle.checked ? 'on' : 'off'); } catch {}
    if (soundToggle.checked) {
      audioContext()?.resume?.().then?.(() => vibrate('toggleOn', true));
    }
  };
  if (!diagnostics.api) {
    $('#haptic-support').textContent = 'Ce navigateur ne gère pas les vibrations. Active le retour sonore.';
  }
  window.reneHapticDiagnostics = () => ({...diagnostics, activated: navigator.userActivation?.hasBeenActive, message: diagnose()});
  renderLevel();
})();
