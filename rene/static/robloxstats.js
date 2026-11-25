/* Statistiques des jeux Roblox : en ligne maintenant, 30 derniers jours, serveurs et joueurs les plus actifs. */
const rbxState = {game: 'christmasrun', timer: null, busy: false};

function rbxServerName(server, index) {
  if (server.studio) return 'Studio (test)';
  return `Serveur ${index + 1}`;
}

function rbxServers(host, game) {
  host.replaceChildren();
  if (!game.servers.length) {
    empty(host, game.public.playing ? 'Les serveurs sont privés ou pas encore visibles.' : 'Aucun serveur en ligne.');
    return;
  }
  game.servers.forEach((server, index) => {
    const row = el('div', 'rbx-server');
    const top = el('div', 'rbx-server-top');
    const name = el('strong', '', rbxServerName(server, index));
    if (server.private) name.append(el('span', 'rbx-tag', 'Privé'));
    const max = server.max_players || Math.max(server.playing, 1);
    top.append(name, el('span', 'rbx-count', `${fmt(server.playing)} / ${fmt(max)}`));
    const track = el('div', 'poll-track');
    const fill = el('div', 'poll-fill');
    track.append(fill);
    const details = [];
    if (server.fps != null) details.push(`${server.fps} fps`);
    if (server.ping != null) details.push(`${server.ping} ms`);
    if (server.uptime != null) details.push(`ouvert depuis ${humanDuration(server.uptime)}`);
    if (server.source === 'roblox') details.push(server.playing ? 'vu par Roblox seulement : ReneStats ne tourne pas sur ce serveur' : 'vu par Roblox seulement : chiffre en retard de quelques minutes, ReneStats ne tourne pas sur ce serveur');
    else details.push('suivi en direct par ReneStats');
    row.append(top, track, el('small', 'rbx-sub', details.join(' · ')));
    if (server.players.length) {
      row.append(el('small', 'rbx-names', server.players.map(p => p.name).join(', ')));
    }
    host.append(row);
    requestAnimationFrame(() => { fill.style.width = `${Math.min(100, server.playing / max * 100)}%`; });
  });
}

function rbxTop(host, game) {
  host.replaceChildren(...game.top.map((player, index) => {
    const row = el('a', 'top-row rbx-player');
    row.href = `https://www.roblox.com/users/${encodeURIComponent(player.id)}/profile`;
    row.target = '_blank';
    row.rel = 'noopener noreferrer';
    const picture = player.avatar ? Object.assign(el('img', 'avatar'), {src: player.avatar, alt: ''}) : el('span', 'avatar rbx-avatar', player.name.slice(0, 1).toUpperCase());
    const main = el('div', 'row-main');
    main.append(el('strong', '', player.name),
      el('small', '', `${fmt(player.sessions)} session(s) · ${fmt(player.days)} jour(s) de jeu`));
    row.append(el('span', 'rank', String(index + 1)), picture, main, el('span', 'row-value', humanDuration(player.seconds)));
    return row;
  }));
  if (!game.top.length) {
    empty(host, game.last_heartbeat ? 'Personne n’a joué sur cette période.'
      : 'Ajoute le Script serveur ReneStats dans le jeu pour voir les joueurs.');
  }
}

function rbxHead(host, game) {
  host.replaceChildren();
  const p = game.public;
  if (p.icon) host.append(Object.assign(el('img', 'rbx-icon'), {src: p.icon, alt: ''}));
  const main = el('div', 'row-main');
  main.append(el('strong', '', p.name || game.name));
  const bits = [];
  if (p.updated) bits.push(`mis à jour le ${date(p.updated)}`);
  if (p.created) bits.push(`créé le ${date(p.created)}`);
  if (game.last_heartbeat) bits.push(`dernier signal du jeu ${new Date(game.last_heartbeat).toLocaleTimeString('fr-FR', {hour: '2-digit', minute: '2-digit'})}`);
  main.append(el('small', '', bits.join(' · ') || 'Infos publiques de Roblox'));
  const live = el('div', 'rbx-live');
  live.append(el('i', game.online.players ? 'on' : ''), el('span', '', `${fmt(game.online.players)} en jeu`));
  host.append(main, live);
  if (p.error) host.append(el('small', 'rbx-error', p.error));
}

function rbxRender(game) {
  const box = $('#rbx-body');
  $('#rbx-missing').classList.toggle('hidden', game.configured);
  box.classList.toggle('hidden', !game.configured);
  if (!game.configured) return;
  const p = game.public, o = game.online, d = game.period, days = statsState.days;
  rbxHead($('#rbx-head'), game);
  $('#rbx-now').replaceChildren(
    statCard('Joueurs en ligne', fmt(o.players), `${fmt(o.script_players)} via ReneStats · ${fmt(o.roblox_players)} selon Roblox`, '◉'),
    statCard('Serveurs en ligne', fmt(o.servers), o.private_servers ? `dont ${fmt(o.private_servers)} privé(s)` : 'serveurs actifs', '▦'),
    statCard('Visites', fmt(p.visits), d.visits ? `+${fmt(d.visits)} en ${days} jours` : 'au total', '↗'),
    statCard('J’aime', pct(p.like_rate), `${fmt(p.likes)} j’aime · ${fmt(p.dislikes)} non · ${fmt(p.favorites)} favoris`, '♥'),
  );
  const detail = d.detail_days < days ? ` (${d.detail_days} derniers jours)` : '';
  $('#rbx-period').replaceChildren(
    statCard('Joueurs uniques', fmt(d.unique), `${String(d.avg_daily_unique).replace('.', ',')} par jour en moyenne${detail}`, '♙'),
    statCard('Nouveaux joueurs', fmt(d.new), `${fmt(d.returning)} sont revenus plusieurs jours`, '✦'),
    statCard('Temps de jeu', `${String(d.hours).replace('.', ',')} h`, d.avg_session_minutes != null ? `${fmt(d.avg_session_minutes)} min par session · ${fmt(d.sessions)} sessions` : 'pas encore de sessions', '⏱'),
    statCard('Record de joueurs', fmt(d.peak), d.peak_date ? `connectés en même temps le ${date(d.peak_date)}` : 'pas encore de relevé', '★'),
  );
  $('#rbx-days').textContent = `${days} jours`;
  lineChart($('#rbx-peak-chart'), game.daily, 'peak');
  barChart($('#rbx-unique-chart'), game.daily, [
    {label: 'Joueurs uniques', className: 'blue', value: row => row.unique},
    {label: 'Nouveaux', className: 'pink', value: row => row.new},
  ]);
  rbxServers($('#rbx-servers'), game);
  $('#rbx-servers-count').textContent = `${fmt(o.servers)} en ligne`;
  rbxTop($('#rbx-top'), game);
}

async function loadRobloxStats() {
  if (rbxState.busy) return;
  rbxState.busy = true;
  try {
    const data = await api(`/api/roblox-stats?days=${statsState.days}&game=${rbxState.game}`);
    if (data.items[0]) rbxRender(data.items[0]);
  } finally {
    rbxState.busy = false;
  }
}

const loadStatsWithoutRoblox = loadStats;
loadStats = async () => {
  await Promise.all([loadStatsWithoutRoblox(), loadRobloxStats().catch(error => notice(error.message, true))]);
};

for (const button of document.querySelectorAll('#rbx-game button')) {
  button.onclick = () => {
    rbxState.game = button.dataset.game;
    for (const other of document.querySelectorAll('#rbx-game button')) other.classList.toggle('active', other === button);
    loadRobloxStats().catch(error => notice(error.message, true));
  };
}

$('#rbx-open-settings').onclick = () => document.querySelector('[data-view=settings]')?.click();

// Les joueurs en ligne se mettent à jour toutes les 30 secondes tant que les statistiques sont ouvertes.
rbxState.timer = setInterval(() => {
  if (state.view === 'stats' && document.visibilityState === 'visible') loadRobloxStats().catch(() => {});
}, 30000);

/* ---------- Réglages : ID de place de chaque jeu ---------- */

async function loadRobloxGames() {
  const data = await api('/api/system/roblox/games');
  $('#roblox-games').replaceChildren(...data.items.map(game => {
    const input = el('input');
    Object.assign(input, {name: game.id, value: game.place_id, inputMode: 'numeric', maxLength: 20,
      placeholder: `${game.name} : ID de la place`});
    input.setAttribute('aria-label', `ID de la place ${game.name}`);
    return input;
  }));
}

const loadSettingsWithoutGames = loadSettings;
loadSettings = async () => { await Promise.all([loadSettingsWithoutGames(), loadRobloxGames()]); };

$('#roblox-games-form').onsubmit = async event => {
  event.preventDefault();
  const body = {};
  for (const input of $('#roblox-games').querySelectorAll('input')) body[input.name] = input.value.trim();
  await withButton(event.submitter || $('#roblox-games-form button'), () => post('/api/system/roblox/games', body));
};

$('#roblox-copy-stats').onclick = async () => {
  try { await copyText((await api('/api/system/roblox/script?name=stats')).script, 'Script copié. Colle-le dans un Script « ReneStats » de ServerScriptService.'); }
  catch (error) { notice(error.message, true); }
};
