/* Île dynamique du panel René : une pastille noire en haut de l'écran qui change de forme
   selon ce que fait René (repos, activité en cours, message, détail au toucher). */
(() => {
  'use strict';
  const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const buzz = name => window.reneHaptic?.(name);
  const node = (tag, className = '', text = '') => { const n = document.createElement(tag); n.className = className; n.textContent = text; return n; };
  const clock = date => date.toLocaleTimeString('fr-FR', {hour: '2-digit', minute: '2-digit'});

  const island = node('div', 'island idle');
  island.id = 'island';
  island.setAttribute('role', 'status');
  island.setAttribute('aria-live', 'polite');
  const body = node('button', 'island-body');
  body.type = 'button';
  body.setAttribute('aria-label', 'Activités de René');
  const content = node('div', 'island-content');
  body.append(content);
  island.append(body);
  $('#app').prepend(island);
  // Copie invisible pour mesurer la taille naturelle du contenu avant de déformer l'île.
  const measurer = node('div', 'island-measure');
  measurer.setAttribute('aria-hidden', 'true');
  document.body.append(measurer);
  function measure(view, width) {
    measurer.style.width = width ? `${width}px` : 'max-content';
    measurer.replaceChildren(view.cloneNode(true));
    const result = {width: Math.ceil(measurer.scrollWidth), height: Math.ceil(measurer.scrollHeight)};
    measurer.replaceChildren();
    return result;
  }

  const s = {
    online: true, pending: 0, loading: false, expanded: false,
    activities: new Map(), transient: null, history: [], guildName: '',
  };

  /* ---------- Rendu ---------- */

  function ring(progress) {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', '0 0 20 20');
    svg.classList.add('island-ring');
    const track = document.createElementNS(svg.namespaceURI, 'circle');
    track.setAttribute('cx', 10); track.setAttribute('cy', 10); track.setAttribute('r', 8);
    track.setAttribute('class', 'track');
    const bar = track.cloneNode();
    bar.setAttribute('class', 'bar');
    bar.setAttribute('pathLength', 100);
    bar.style.strokeDashoffset = String(100 - Math.round(progress * 100));
    svg.append(track, bar);
    return svg;
  }

  function lead(icon, tone = '') {
    const span = node('span', `island-lead ${tone}`);
    if (icon === 'rene') {
      const img = node('img');
      img.src = '/assets/IDLE.png';
      img.alt = '';
      span.classList.add('avatar');
      span.append(img);
    } else span.textContent = icon;
    return span;
  }

  function topActivity() {
    let best = null;
    for (const activity of s.activities.values()) if (!best || activity.priority > best.priority) best = activity;
    return best;
  }

  function compactView(activity) {
    const row = node('div', 'island-row');
    row.append(lead(activity.icon, activity.tone), node('span', 'island-text', activity.text));
    const trail = node('span', 'island-trail');
    if (activity.progress != null) trail.append(ring(activity.progress));
    if (activity.trail) trail.append(node('span', 'island-value', activity.trail));
    if (activity.comet) trail.append(node('span', 'island-comet'));
    row.append(trail);
    return row;
  }

  function idleView() {
    const row = node('div', 'island-row');
    row.append(lead('rene'));
    const trail = node('span', 'island-trail');
    trail.append(s.loading ? node('span', 'island-spinner') : node('span', `island-dot ${s.online ? 'on' : 'off'}`));
    row.append(trail);
    return row;
  }

  function noticeView(item) {
    const row = node('div', 'island-row');
    row.append(lead(item.icon, item.tone), node('span', 'island-text', item.text));
    if (item.action) row.append(node('span', 'island-trail island-go', '›'));
    return row;
  }

  function expandedView() {
    const panel = node('div', 'island-panel');
    const head = node('div', 'island-head');
    const who = node('div', 'island-who');
    who.append(node('strong', '', 'René'), node('small', '', s.online ? `Au bureau${s.guildName ? ` · ${s.guildName}` : ''}` : 'Se reconnecte à Discord…'));
    head.append(lead('rene'), who, node('span', 'island-time', clock(new Date())));
    panel.append(head);

    const activities = [...s.activities.values()].sort((a, b) => b.priority - a.priority);
    if (activities.length) {
      panel.append(node('p', 'island-label', 'EN COURS'));
      for (const activity of activities) {
        const row = node('div', 'island-activity');
        const top = node('div', 'island-activity-top');
        top.append(lead(activity.icon, activity.tone), node('span', 'island-text', activity.detail || activity.text));
        row.append(top);
        if (activity.progress != null) {
          const track = node('div', 'island-bar');
          const fill = node('span');
          fill.style.width = `${Math.round(activity.progress * 100)}%`;
          track.append(fill);
          row.append(track);
        }
        if (activity.actions?.length) {
          const buttons = node('div', 'island-actions');
          for (const action of activity.actions) {
            const button = node('button', `island-button ${action.tone || ''}`, action.label);
            button.type = 'button';
            button.onclick = event => { event.stopPropagation(); action.run(); collapse(); };
            buttons.append(button);
          }
          row.append(buttons);
        }
        panel.append(row);
      }
    }

    panel.append(node('p', 'island-label', 'NOTIFICATIONS'));
    if (!s.history.length) panel.append(node('p', 'island-empty', 'Tout est calme au bureau.'));
    for (const item of s.history.slice(0, 4)) {
      const row = node('button', 'island-history');
      row.type = 'button';
      row.append(lead(item.icon, item.tone), node('span', 'island-text', item.text), node('span', 'island-time', clock(item.at)));
      row.disabled = !item.action;
      row.onclick = event => { event.stopPropagation(); if (item.action) { item.action(); collapse(); } };
      panel.append(row);
    }
    return panel;
  }

  let lastKey = '';
  function render() {
    const activity = topActivity();
    const mode = s.expanded ? 'expanded' : s.transient ? 'notice' : activity ? 'compact' : 'idle';
    const view = mode === 'expanded' ? expandedView() : mode === 'notice' ? noticeView(s.transient)
      : mode === 'compact' ? compactView(activity) : idleView();
    const key = `${mode}|${view.textContent}|${s.loading}|${s.online}|${activity?.progress}`;
    if (key === lastKey) return;
    const modeChanged = !island.classList.contains(mode);
    lastKey = key;

    island.className = `island ${mode} ${s.transient?.tone || activity?.tone || ''}`;
    const swap = () => {
      content.replaceChildren(view);
      content.classList.remove('swap');
    };
    size(mode, view);
    if (modeChanged && !reduced) {
      content.classList.add('swap');
      setTimeout(swap, 130);
    } else swap();
  }

  // La taille suit le contenu : l'île s'étire ou se rétracte, jamais de saut.
  function size(mode, view) {
    const max = Math.min(window.innerWidth - 24, mode === 'expanded' ? 460 : 440);
    if (mode === 'idle') { island.style.width = s.loading ? '138px' : '124px'; island.style.height = '36px'; return; }
    if (mode === 'expanded') {
      island.style.width = `${max}px`;
      island.style.height = `${Math.min(measure(view, max).height, window.innerHeight * 0.8)}px`;
      return;
    }
    island.style.width = `${Math.min(max, Math.max(200, measure(view).width + 6))}px`;
    island.style.height = '40px';
  }

  /* ---------- Gestes ---------- */

  function collapse() {
    if (!s.expanded) return;
    s.expanded = false;
    buzz('close');
    render();
  }

  body.onclick = () => {
    if (s.transient?.action && !s.expanded) {
      const action = s.transient.action;
      clearTransient();
      action();
      return;
    }
    s.expanded = !s.expanded;
    if (s.expanded) clearTransient(false);
    buzz(s.expanded ? 'open' : 'close');
    render();
  };
  document.addEventListener('pointerdown', event => { if (s.expanded && !island.contains(event.target)) collapse(); }, true);
  document.addEventListener('keydown', event => { if (event.key === 'Escape') collapse(); });
  addEventListener('resize', () => { lastKey = ''; render(); });

  /* ---------- Messages éphémères ---------- */

  let transientTimer = null;
  function clearTransient(redraw = true) {
    clearTimeout(transientTimer);
    s.transient = null;
    if (redraw) render();
  }

  function flash(text, {tone = '', icon = '✓', action = null, duration = 3400, keep = true} = {}) {
    const item = {text, tone, icon, action, at: new Date()};
    if (keep) { s.history.unshift(item); s.history = s.history.slice(0, 12); }
    if (s.expanded) { render(); return; }
    s.transient = item;
    clearTimeout(transientTimer);
    transientTimer = setTimeout(() => clearTransient(), duration);
    render();
  }

  // Les notifications du panel passent désormais par l'île.
  const noticeBefore = notice;
  notice = (text, bad = false) => {
    noticeBefore(text, bad);
    flash(text, bad ? {tone: 'bad', icon: '!'} : {tone: 'good', icon: '✓'});
  };

  /* ---------- Activités suivies ---------- */

  function setActivity(id, activity) {
    if (activity) s.activities.set(id, activity); else s.activities.delete(id);
    render();
  }

  // Chargements et connexion : on observe chaque appel au serveur.
  let loadingTimer = null;
  const apiBefore = api;
  api = async (...args) => {
    s.pending += 1;
    clearTimeout(loadingTimer);
    loadingTimer = setTimeout(() => { s.loading = s.pending > 0; render(); }, 450);
    try {
      const result = await apiBefore(...args);
      if (!s.online) { s.online = true; setActivity('offline', null); flash('René est de retour au bureau.', {tone: 'good', icon: '✓'}); }
      return result;
    } catch (error) {
      if (/se connecte|Failed to fetch|NetworkError|Load failed|ne répond pas/i.test(error.message)) {
        s.online = false;
        setActivity('offline', {icon: '◌', text: 'René se reconnecte', tone: 'warn', priority: 50,
                                detail: 'René se reconnecte à Discord. Les actions reprendront toutes seules.'});
      }
      throw error;
    } finally {
      s.pending = Math.max(0, s.pending - 1);
      if (!s.pending) { clearTimeout(loadingTimer); if (s.loading) { s.loading = false; render(); } }
    }
  };

  // Nom du serveur pour l'île déployée.
  const guildSelect = $('#guild-select');
  new MutationObserver(() => { s.guildName = guildSelect.selectedOptions[0]?.textContent || ''; }).observe(guildSelect, {childList: true});
  guildSelect.addEventListener('change', () => { s.guildName = guildSelect.selectedOptions[0]?.textContent || ''; });

  // MP à tous : progression en direct, même depuis une autre page.
  let broadcastTimer = null;
  function trackBroadcast(data) {
    const job = data?.job;
    clearTimeout(broadcastTimer);
    if (job && data.running) {
      const progress = job.total ? job.done / job.total : 0;
      setActivity('broadcast', {
        icon: '✉', text: 'Envoi à tous', trail: `${job.done}/${job.total}`, progress, priority: 40,
        detail: `MP à ${job.role_name} · ${job.sent} reçus, ${job.failed} MP fermés`,
        actions: [
          {label: 'Voir', run: () => navigate('messages')},
          {label: 'Arrêter', tone: 'danger', run: () => post(`/api/guild/${state.guild}/broadcast/cancel`).then(() => pollBroadcast()).catch(e => notice(e.message, true))},
        ],
      });
      broadcastTimer = setTimeout(pollBroadcast, 3000);
    } else {
      if (s.activities.has('broadcast') && job) {
        const states = {finished: 'Envoi terminé', cancelled: 'Envoi arrêté', error: 'Envoi interrompu'};
        flash(`${states[job.state] || 'Envoi terminé'} · ${job.sent} reçus sur ${job.total}`,
              {tone: job.state === 'finished' ? 'good' : 'warn', icon: '✉', action: () => navigate('messages')});
        if (job.state === 'finished') window.reneHalo?.();
      }
      setActivity('broadcast', null);
    }
  }
  function pollBroadcast() {
    if (!state.guild || !state.csrf) return;
    api(`/api/guild/${state.guild}/broadcast`).then(trackBroadcast).catch(() => { broadcastTimer = setTimeout(pollBroadcast, 6000); });
  }
  const renderBroadcastBefore = renderBroadcast;
  renderBroadcast = data => { renderBroadcastBefore(data); trackBroadcast(data); };
  setTimeout(pollBroadcast, 3500);

  // René IA : la comète tourne tant qu'il réfléchit.
  new MutationObserver(() => {
    const thinking = $('#ai-chat .bubble.thinking');
    setActivity('ai', thinking ? {icon: '✦', text: 'René réfléchit', comet: true, tone: 'halo', priority: 30,
                                   detail: 'René analyse les statistiques avec NathGPT.',
                                   actions: [{label: 'Voir', run: () => navigate('ai')}]} : null);
  }).observe($('#ai-chat'), {childList: true, subtree: true, attributes: true, attributeFilter: ['class']});

  // Vérification du cadeau par QR.
  new MutationObserver(() => {
    const open = !$('#qr-dialog').classList.contains('hidden');
    setActivity('qr', open ? {icon: '⌁', text: 'Scanne le QR', tone: 'halo', priority: 60,
                              detail: 'René attend le QR envoyé en MP pour confirmer le cadeau.'} : null);
  }).observe($('#qr-dialog'), {attributes: true, attributeFilter: ['class']});

  // Nouveaux tickets et demandes d'assistance.
  function watchBadge(selector, text, view, icon) {
    const badge = $(selector);
    let previous = null;
    new MutationObserver(() => {
      const value = badge.classList.contains('hidden') ? 0 : parseInt(badge.textContent, 10) || 0;
      if (previous !== null && value > previous) {
        flash(value - previous > 1 ? `${value - previous} ${text.plural}` : text.one, {tone: 'notify', icon, action: () => navigate(view), duration: 5200});
      }
      previous = value;
    }).observe(badge, {childList: true, characterData: true, subtree: true, attributes: true, attributeFilter: ['class']});
  }
  watchBadge('#ticket-badge', {one: 'Nouveau ticket', plural: 'nouveaux tickets'}, 'tickets', '✉');
  watchBadge('#assist-badge', {one: 'Nouvelle demande d’assistance', plural: 'nouvelles demandes d’assistance'}, 'assistance', '✚');

  // Moments forts : le halo entoure l'île un court instant.
  const haloBefore = window.reneHalo;
  window.reneHalo = () => {
    haloBefore?.();
    island.classList.remove('glow');
    void island.offsetWidth;
    island.classList.add('glow');
    setTimeout(() => island.classList.remove('glow'), 1600);
  };

  // Changer de page referme l'île.
  const navigateBefore = navigate;
  navigate = view => { if (s.expanded) { s.expanded = false; render(); } navigateBefore(view); };
  for (const button of document.querySelectorAll('[data-view]')) button.onclick = () => navigate(button.dataset.view);

  // L'heure de l'île déployée reste juste.
  setInterval(() => { if (s.expanded) { lastKey = ''; render(); } }, 30000);

  window.reneIsland = {flash, setActivity};
  render();
})();
