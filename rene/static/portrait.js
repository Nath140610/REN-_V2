/* Tablette tenue verticalement : barre d'onglets en bas (comme sur iPad) et feuille « Plus ».
   La barre est construite à partir du menu latéral, qui reste la source unique des sections. */
(() => {
  'use strict';
  const MAIN = ['overview', 'members', 'tickets', 'gifts'];
  const node = (tag, className = '', text = '') => { const n = document.createElement(tag); n.className = className; n.textContent = text; return n; };
  const sideButtons = [...document.querySelectorAll('.sidebar .nav[data-view]')];
  const label = button => [...button.childNodes].filter(n => n.nodeType === Node.TEXT_NODE).map(n => n.textContent).join('').trim();
  const iconOf = button => button.querySelector('.nav-icon')?.cloneNode(true) || node('span', 'nav-icon gray', '•');
  const short = {overview: 'Accueil', members: 'Membres', tickets: 'Tickets', gifts: 'Cadeaux'};

  /* ---------- Barre d'onglets ---------- */

  const bar = node('nav', 'tabbar');
  bar.setAttribute('aria-label', 'Navigation');
  const tabs = new Map();
  for (const view of MAIN) {
    const source = sideButtons.find(button => button.dataset.view === view);
    if (!source) continue;
    const tab = node('button', 'tab');
    tab.type = 'button';
    tab.dataset.view = view;
    const icon = iconOf(source);
    icon.classList.add('tab-icon');
    tab.append(icon, node('span', 'tab-label', short[view] || label(source)));
    const badge = source.querySelector('.badge');
    if (badge) tab.append(mirrorBadge(badge));
    tab.onclick = () => navigate(view);
    bar.append(tab);
    tabs.set(view, tab);
  }

  const more = node('button', 'tab tab-more');
  more.type = 'button';
  const moreIcon = node('span', 'nav-icon gray tab-icon', '•••');
  const moreSlot = node('span', 'tab-slot');
  moreSlot.append(moreIcon);
  const moreLabel = node('span', 'tab-label', 'Plus');
  more.append(moreSlot, moreLabel);
  const extraBadges = sideButtons.filter(b => !MAIN.includes(b.dataset.view)).map(b => b.querySelector('.badge')).filter(Boolean);
  const moreBadge = node('b', 'badge tab-badge hidden');
  more.append(moreBadge);
  more.onclick = openMore;
  bar.append(more);
  $('#app').append(bar);

  // Les badges (tickets, assistance) suivent ceux du menu latéral.
  function mirrorBadge(source, className = 'badge tab-badge') {
    const copy = node('b', className);
    const sync = () => { copy.textContent = source.textContent; copy.classList.toggle('hidden', source.classList.contains('hidden')); };
    new MutationObserver(sync).observe(source, {childList: true, characterData: true, subtree: true, attributes: true, attributeFilter: ['class']});
    sync();
    return copy;
  }
  function syncMoreBadge() {
    const total = extraBadges.reduce((sum, b) => sum + (b.classList.contains('hidden') ? 0 : parseInt(b.textContent, 10) || 0), 0);
    moreBadge.textContent = total > 99 ? '99+' : String(total);
    moreBadge.classList.toggle('hidden', !total);
  }
  extraBadges.forEach(b => new MutationObserver(syncMoreBadge).observe(b, {childList: true, characterData: true, subtree: true, attributes: true, attributeFilter: ['class']}));
  syncMoreBadge();

  /* ---------- Feuille « Plus » ---------- */

  const sheet = node('div', 'dialog hidden more-dialog');
  sheet.id = 'more-sheet';
  sheet.setAttribute('role', 'dialog');
  sheet.setAttribute('aria-modal', 'true');
  sheet.setAttribute('aria-label', 'Toutes les sections');
  const card = node('div', 'sheet more-sheet');
  const head = node('div', 'sheet-head');
  head.append(node('h2', 'more-title', 'Plus'));
  const close = node('button', 'link-button sheet-close', 'Fermer');
  close.type = 'button';
  head.append(close);
  card.append(head);
  const list = node('div', 'group more-list');
  for (const source of sideButtons.filter(b => !MAIN.includes(b.dataset.view))) {
    const row = node('button', 'group-row more-row');
    row.type = 'button';
    row.dataset.view = source.dataset.view;
    row.append(iconOf(source), node('span', 'more-label', label(source)));
    const badge = source.querySelector('.badge');
    if (badge) row.append(mirrorBadge(badge, 'badge more-badge'));
    row.append(node('i', '', '›'));
    row.onclick = () => { closeMore(true); navigate(source.dataset.view); };
    list.append(row);
  }
  card.append(list);
  const logout = node('button', 'button danger wide more-logout', 'Se déconnecter');
  logout.type = 'button';
  logout.onclick = () => { closeMore(true); $('#logout').click(); };
  card.append(logout);
  sheet.append(card);
  document.body.append(sheet);

  function openMore() {
    window.reneHaptic?.('open');
    sheet.classList.remove('hidden', 'closing');
  }
  function closeMore(instant = false) {
    if (sheet.classList.contains('hidden')) return;
    if (instant) { sheet.classList.add('hidden'); return; }
    window.reneHaptic?.('close');
    sheet.classList.add('closing');
    setTimeout(() => { sheet.classList.remove('closing'); sheet.classList.add('hidden'); }, 260);
  }
  close.onclick = () => closeMore();
  sheet.onclick = event => { if (event.target === sheet) closeMore(); };
  document.addEventListener('keydown', event => { if (event.key === 'Escape') closeMore(); });

  /* ---------- Onglet actif ---------- */

  function syncActive() {
    const view = state.view;
    for (const [id, tab] of tabs) tab.classList.toggle('active', id === view);
    const inMore = !MAIN.includes(view);
    more.classList.toggle('active', inMore);
    const source = sideButtons.find(b => b.dataset.view === view);
    if (inMore && source) {
      moreLabel.textContent = label(source);
      const icon = iconOf(source);
      icon.classList.add('tab-icon');
      moreSlot.replaceChildren(icon);
    } else {
      moreLabel.textContent = 'Plus';
      moreSlot.replaceChildren(moreIcon);
    }
    for (const row of list.querySelectorAll('.more-row')) row.classList.toggle('active', row.dataset.view === view);
  }
  new MutationObserver(syncActive).observe(document.querySelector('.sidebar nav'), {subtree: true, attributes: true, attributeFilter: ['class']});
  syncActive();

  // En repassant à l'horizontale, la feuille « Plus » n'a plus de raison d'être ouverte.
  const portrait = matchMedia('(orientation: portrait) and (max-width: 1100px)');
  const onOrientation = () => {
    document.body.classList.toggle('portrait', portrait.matches);
    if (!portrait.matches) closeMore(true);
    requestAnimationFrame(() => window.dispatchEvent(new Event('resize')));
  };
  portrait.addEventListener?.('change', onOrientation);
  onOrientation();
})();
