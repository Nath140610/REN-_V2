/* Modération, tickets et voix de René depuis la tablette. */
const sheet = {member: null, roles: null, hours: 24};
let ticketFilter = 'open';
let ticketCache = [];

async function post(path, body = {}) {
  return api(path, {method: 'POST', body: JSON.stringify(body)});
}

async function withButton(button, action) {
  button.disabled = true;
  try {
    const result = await action();
    if (result?.message) notice(result.message);
    haptic([20, 30, 20]);
    return result;
  } catch (error) {
    notice(error.message, true);
    haptic([35, 35, 35]);
    return null;
  } finally {
    button.disabled = false;
  }
}

/* ---------- Fiche membre ---------- */

function showPane(name) {
  for (const pane of document.querySelectorAll('#member-sheet .sheet-pane')) pane.classList.toggle('hidden', pane.dataset.pane !== name);
  $('#sheet-back').classList.toggle('hidden', name === 'actions');
  const first = document.querySelector(`#member-sheet [data-pane="${name}"] textarea`);
  if (first) setTimeout(() => first.focus(), 50);
}

function openMemberSheet(member) {
  sheet.member = member;
  $('#sheet-avatar').src = member.avatar;
  $('#sheet-name').textContent = member.name;
  $('#sheet-meta').textContent = `${member.username} · ${fmt(member.warnings)}/10 avertissements`;
  for (const id of ['#warn-reason', '#tempban-reason', '#ban-reason']) $(id).value = '';
  showPane('actions');
  $('#member-sheet').classList.remove('hidden');
}

function closeMemberSheet() {
  sheet.member = null;
  $('#member-sheet').classList.add('hidden');
}

async function renderRoles() {
  const host = $('#role-list');
  if (!sheet.roles) {
    empty(host, 'Chargement…');
    sheet.roles = (await api(`/api/guild/${state.guild}/roles`)).items;
  }
  const owned = new Set(sheet.member.roles || []);
  host.replaceChildren();
  for (const role of sheet.roles) {
    const row = el('label', `group-row switch-row ${role.editable ? '' : 'locked'}`);
    const name = el('span', 'role-name');
    const dot = el('i', 'role-dot');
    dot.style.background = role.color || '#8E8E93';
    name.append(dot, document.createTextNode(role.name));
    const input = Object.assign(el('input', 'switch'), {type: 'checkbox', checked: owned.has(role.id), disabled: !role.editable});
    input.onchange = async () => {
      input.disabled = true;
      try {
        const result = await post(`/api/guild/${state.guild}/roles`, {user_id: sheet.member.id, role_id: role.id, enabled: input.checked});
        sheet.member.roles = result.roles;
        notice(result.message);
        haptic([15, 25, 15]);
      } catch (error) {
        input.checked = !input.checked;
        notice(error.message, true);
        haptic([35, 35, 35]);
      } finally { input.disabled = false; }
    };
    row.append(name, input);
    host.append(row);
  }
  if (!sheet.roles.length) empty(host, 'Aucun rôle sur ce serveur.');
}

const sheetActions = {
  warn() {
    $('#warn-count').textContent = `Actuellement ${sheet.member.warnings}/10. À 10, René bannit 24 h.`;
    showPane('warn');
  },
  tempban() { showPane('tempban'); },
  ban() { showPane('ban'); },
  roles() { showPane('roles'); renderRoles().catch(error => notice(error.message, true)); },
  async express(button) {
    if (!window.confirm(`Lancer un rendez-vous express avec ${sheet.member.name} ?`)) return;
    const result = await withButton(button, () => post(`/api/guild/${state.guild}/express`, {user_id: sheet.member.id}));
    if (result) closeMemberSheet();
  },
  dm() { const member = sheet.member; closeMemberSheet(); navigate('messages'); selectPicker('dm', member); },
  gift() { const member = sheet.member; closeMemberSheet(); navigate('gifts'); selectPicker('gift', member); },
};

for (const button of document.querySelectorAll('#member-sheet [data-action]')) {
  button.onclick = () => sheetActions[button.dataset.action](button);
}
$('#sheet-back').onclick = () => showPane('actions');
$('#sheet-close').onclick = closeMemberSheet;
$('#member-sheet').onclick = event => { if (event.target.id === 'member-sheet') closeMemberSheet(); };
document.addEventListener('keydown', event => { if (event.key === 'Escape' && sheet.member) closeMemberSheet(); });

for (const button of document.querySelectorAll('#tempban-duration button')) {
  button.onclick = () => {
    sheet.hours = Number(button.dataset.hours);
    for (const other of document.querySelectorAll('#tempban-duration button')) other.classList.toggle('active', other === button);
  };
}

$('#confirm-warn').onclick = async () => {
  const reason = $('#warn-reason').value.trim();
  if (reason.length < 3) { notice('Indique un motif.', true); return; }
  const result = await withButton($('#confirm-warn'), () => post(`/api/guild/${state.guild}/warn`, {user_id: sheet.member.id, reason}));
  if (result) { closeMemberSheet(); await loadMembers(); }
};

$('#confirm-tempban').onclick = async () => {
  const reason = $('#tempban-reason').value.trim();
  if (reason.length < 3) { notice('Indique un motif.', true); return; }
  if (!window.confirm(`Bannir ${sheet.member.name} temporairement ?`)) return;
  const result = await withButton($('#confirm-tempban'), () => post(`/api/guild/${state.guild}/tempban`, {user_id: sheet.member.id, reason, hours: sheet.hours}));
  if (result) { closeMemberSheet(); await loadMembers(); }
};

$('#confirm-ban').onclick = async () => {
  const reason = $('#ban-reason').value.trim();
  if (reason.length < 5) { notice('Indique un motif d’au moins cinq caractères.', true); return; }
  if (!window.confirm(`Bannir ${sheet.member.name} définitivement ?`)) return;
  const result = await withButton($('#confirm-ban'), () => post(`/api/guild/${state.guild}/ban`, {user_id: sheet.member.id, reason}));
  if (result) { closeMemberSheet(); await loadMembers(); }
};

/* ---------- Rendez-vous express ---------- */

$('#express-form').onsubmit = async event => {
  event.preventDefault();
  const form = event.target;
  const memberId = form.elements.namedItem('user_id').value;
  if (!memberId) { notice('Choisis un membre dans la recherche.', true); return; }
  const result = await withButton(form.querySelector('button[type=submit]'), () => post(`/api/guild/${state.guild}/express`, {user_id: memberId}));
  if (result) { resetPicker('express'); await loadAppointments(); }
};

/* ---------- Sanctions ---------- */

async function loadTempBans() {
  const data = await api(`/api/guild/${state.guild}/tempbans`);
  const host = $('#tempban-list');
  host.replaceChildren();
  for (const item of data.items) {
    const row = el('div', 'list-row');
    const avatar = item.avatar ? Object.assign(el('img', 'avatar'), {src: item.avatar, alt: ''}) : el('span', 'audit-icon', '⏳');
    const main = el('div', 'row-main');
    main.append(el('strong', '', item.name), el('small', '', `Jusqu’au ${new Date(item.until).toLocaleString('fr-FR', {dateStyle:'medium', timeStyle:'short'})}`));
    const lift = el('button', 'mini', 'Lever');
    lift.type = 'button';
    lift.onclick = async () => {
      if (!window.confirm(`Lever le bannissement de ${item.name} ?`)) return;
      if (await withButton(lift, () => post(`/api/guild/${state.guild}/tempbans/${item.id}/lift`))) await loadTempBans();
    };
    row.append(avatar, main, lift);
    host.append(row);
  }
  if (!data.items.length) empty(host, 'Aucun bannissement en cours.');
}

/* ---------- Tickets ---------- */

function ticketCard(ticket) {
  const card = el('article', `card ticket ${ticket.answered ? 'done' : ''}`);
  const head = el('div', 'ticket-head');
  if (ticket.avatar) head.append(Object.assign(el('img', 'avatar'), {src: ticket.avatar, alt: ''}));
  const who = el('div', 'row-main');
  who.append(el('strong', '', ticket.author), el('small', '', new Date(ticket.created_at).toLocaleString('fr-FR', {dateStyle:'medium', timeStyle:'short'})));
  head.append(who);
  const link = Object.assign(el('a', 'text-button', 'Discord ↗'), {href: ticket.url, target: '_blank', rel: 'noopener'});
  head.append(link);
  card.append(head, el('p', 'ticket-question', ticket.content));
  if (ticket.answered) {
    const answer = el('div', 'ticket-answer');
    answer.append(el('small', '', ticket.closed ? `Clos par ${ticket.answered_by || 'le staff'}` : `Réponse de ${ticket.answered_by || 'staff'}`));
    if (ticket.answer) answer.append(el('p', '', ticket.answer));
    card.append(answer);
    return card;
  }
  const form = el('form', 'ticket-form');
  const input = Object.assign(el('textarea'), {rows: 2, maxLength: 1800, required: true, placeholder: 'Répondre en tant que René'});
  const actions = el('div', 'ticket-actions');
  const close = Object.assign(el('button', 'button subtle', 'Clore'), {type: 'button'});
  const send = Object.assign(el('button', 'button primary', 'Répondre'), {type: 'submit'});
  close.onclick = async () => {
    if (!window.confirm('Clore ce ticket sans réponse ?')) return;
    if (await withButton(close, () => post(`/api/guild/${state.guild}/tickets/${ticket.id}/close`))) await loadTickets();
  };
  form.onsubmit = async event => {
    event.preventDefault();
    const message = input.value.trim();
    if (!message) return;
    if (await withButton(send, () => post(`/api/guild/${state.guild}/tickets/${ticket.id}/reply`, {message}))) await loadTickets();
  };
  actions.append(close, send);
  form.append(input, actions);
  card.append(form);
  return card;
}

function renderTickets() {
  const host = $('#ticket-list');
  const items = ticketCache.filter(ticket => ticketFilter === 'open' ? !ticket.answered : ticket.answered);
  host.replaceChildren(...items.map(ticketCard));
  if (!items.length) empty(host, ticketFilter === 'open' ? 'Aucun ticket en attente.' : 'Aucun ticket traité.');
}

function updateTicketBadge(count) {
  const badge = $('#ticket-badge');
  badge.textContent = count > 99 ? '99+' : String(count);
  badge.classList.toggle('hidden', !count);
}

async function loadTickets() {
  const data = await api(`/api/guild/${state.guild}/tickets`);
  ticketCache = data.items;
  updateTicketBadge(data.open);
  renderTickets();
}

for (const button of document.querySelectorAll('#ticket-filter button')) {
  button.onclick = () => {
    ticketFilter = button.dataset.filter;
    for (const other of document.querySelectorAll('#ticket-filter button')) other.classList.toggle('active', other === button);
    renderTickets();
  };
}

/* ---------- Parler en René ---------- */

let channelGuild = '';
async function loadChannels() {
  if (channelGuild === state.guild) return;
  const data = await api(`/api/guild/${state.guild}/channels`);
  const select = $('#say-channel');
  select.replaceChildren(Object.assign(el('option', '', 'Choisir un salon'), {value: ''}));
  for (const channel of data.items) {
    const option = el('option', '', `# ${channel.name}${channel.category ? ` · ${channel.category}` : ''}`);
    option.value = channel.id;
    select.append(option);
  }
  channelGuild = state.guild;
}

$('#say-form').onsubmit = async event => {
  event.preventDefault();
  const form = event.target;
  const channel = form.elements.namedItem('channel_id').value;
  if (!channel) { notice('Choisis un salon.', true); return; }
  if (!window.confirm('Publier ce message au nom de René ?')) return;
  const result = await withButton(form.querySelector('button[type=submit]'), () => post(`/api/guild/${state.guild}/say`, {channel_id: channel, message: form.elements.namedItem('message').value}));
  if (result) form.elements.namedItem('message').value = '';
};

/* ---------- Changement de serveur ---------- */

const previousGuildChange = $('#guild-select').onchange;
$('#guild-select').onchange = () => {
  sheet.roles = null;
  channelGuild = '';
  ticketCache = [];
  previousGuildChange();
  refreshTicketBadge();
};

function refreshTicketBadge() {
  if (!state.csrf || !state.guild) return;
  api(`/api/guild/${state.guild}/tickets`).then(data => updateTicketBadge(data.open)).catch(() => {});
}
setInterval(() => { if (!document.hidden) refreshTicketBadge(); }, 90000);
setTimeout(refreshTicketBadge, 4000);

/* ---------- Cartes cadeau à gratter ---------- */

const GIFT_LABELS = {sent:'Pas ouverte', opened:'Ouverte', scratched:'Grattée', expired:'Expirée', used:'Utilisé',
                     replaced:'Remplacé', legacy:'Ancien code', dm_failed:'MP fermé'};
const GIFT_TONE = {sent:'idle', opened:'blue', scratched:'', expired:'fail', used:'violet', replaced:'idle', legacy:'warn', dm_failed:'fail'};
const giftState = {items: [], filter: 'all', text: ''};
const when = value => value ? new Date(value).toLocaleString('fr-FR', {dateStyle:'medium', timeStyle:'short'}) : '';

function remainingText(expiresAt) {
  const left = Math.max(0, new Date(expiresAt).getTime() - Date.now());
  const hours = Math.floor(left / 3600000), minutes = Math.floor(left / 60000) % 60;
  return hours ? `${hours} h ${String(minutes).padStart(2, '0')}` : `${minutes} min`;
}

function giftLabel(entry) {
  if (entry.status === 'scratched') return `Grattée · ${remainingText(entry.expires_at)}`;
  if (entry.status === 'used') return entry.used_by_roblox_name ? `Utilisé · ${entry.used_by_roblox_name}` : 'Utilisé';
  return GIFT_LABELS[entry.status] || entry.status;
}

function giftRow(entry) {
  const row = el('div', 'list-row');
  row.tabIndex = 0;
  row.append(el('span', 'audit-icon', entry.status === 'used' ? '✓' : entry.status === 'scratched' ? '✦' : '◇'));
  const main = el('div', 'row-main');
  let step = date(entry.created_at);
  if (entry.used_at) step = `utilisé le ${when(entry.used_at)}`;
  else if (entry.scratched_at) step = `grattée le ${when(entry.scratched_at)}`;
  else if (entry.opened_at) step = `lien ouvert ${entry.views || 1}×`;
  else if (entry.card_sent_at) step = 'lien pas encore ouvert';
  main.append(el('strong', 'gift-code', entry.code), el('small', '', [entry.recipient_name, entry.reason, step].filter(Boolean).join(' · ')));
  const pill = el('span', `pill ${GIFT_TONE[entry.status] || ''}`, giftLabel(entry));
  if (entry.status === 'scratched') pill.dataset.expires = entry.expires_at;
  row.append(main, pill, el('span', 'chevron', '›'));
  row.onclick = () => openGiftSheet(entry);
  row.onkeydown = event => { if (event.key === 'Enter') openGiftSheet(entry); };
  return row;
}

function renderGiftList() {
  const needle = giftState.text.toLowerCase();
  const groups = {sent: ['sent', 'dm_failed'], opened: ['opened'], scratched: ['scratched'], used: ['used'], expired: ['expired']};
  const items = giftState.items.filter(entry =>
    (giftState.filter === 'all' || groups[giftState.filter].includes(entry.status)) &&
    (!needle || [entry.code, entry.recipient_name, entry.reason, entry.used_by_roblox_name].some(v => String(v || '').toLowerCase().includes(needle))));
  const host = $('#gift-list');
  host.replaceChildren(...items.map(giftRow));
  if (!items.length) empty(host, giftState.items.length ? 'Aucun code ne correspond.' : 'Aucune carte envoyée.');
}

function timelineStep(title, detail, status) {
  const step = el('div', `step ${status}`);
  const text = el('div');
  text.append(el('strong', '', title));
  if (detail) text.append(el('small', '', detail));
  step.append(el('i'), text);
  return step;
}

function openGiftSheet(entry) {
  $('#gift-sheet-code').textContent = entry.code;
  $('#gift-sheet-meta').textContent = [entry.recipient_name, entry.reason].filter(Boolean).join(' · ');
  const legacy = entry.status === 'legacy' || entry.status === 'replaced';
  const steps = [];
  steps.push(timelineStep(legacy ? 'Code envoyé en clair' : 'Lien envoyé en MP',
                          entry.status === 'dm_failed' ? 'MP fermé' : when(entry.card_sent_at || entry.created_at),
                          entry.status === 'dm_failed' ? 'bad' : 'done'));
  if (!legacy) {
    steps.push(entry.opened_at
      ? timelineStep('Lien ouvert', `${when(entry.opened_at)} · ${entry.views || 1} visite(s), dernière ${when(entry.last_seen_at)}`, 'done')
      : timelineStep('Lien pas encore ouvert', '', 'todo'));
    steps.push(entry.scratched_at
      ? timelineStep('Code gratté', `${when(entry.scratched_at)} · valable jusqu’au ${when(entry.expires_at)}`, 'done')
      : timelineStep('Pas encore gratté', 'Le code n’est pas encore activé.', 'todo'));
  }
  if (entry.used_at) {
    const who = entry.used_manually ? 'Marqué depuis le panel'
      : `${entry.used_by_roblox_name || 'Joueur'} (${entry.used_by_roblox_id || '?'})${entry.used_place_id ? ` · place ${entry.used_place_id}` : ''}`;
    steps.push(timelineStep('Utilisé dans Roblox', `${when(entry.used_at)} · ${who}`, 'done'));
  } else if (entry.status === 'expired') {
    steps.push(timelineStep('Expiré sans être utilisé', when(entry.expires_at), 'bad'));
  } else if (entry.status === 'replaced') {
    steps.push(timelineStep('Remplacé par une carte', entry.replaced_by || '', 'bad'));
  } else {
    steps.push(timelineStep('Pas encore utilisé', entry.status === 'scratched' ? `Disponible encore ${remainingText(entry.expires_at)}` : '', 'todo'));
  }
  $('#gift-timeline').replaceChildren(...steps);

  const actions = [];
  const action = (label, kind, question, call) => {
    const button = Object.assign(el('button', `button ${kind}`, label), {type: 'button'});
    button.onclick = async () => {
      if (question && !window.confirm(question)) return;
      if (await withButton(button, call)) { closeGiftSheet(); await loadGifts(); }
    };
    actions.push(button);
  };
  if (['sent', 'opened', 'dm_failed'].includes(entry.status)) {
    action('Renvoyer le lien', 'subtle', 'Renvoyer la carte ? L’ancien MP sera supprimé.',
           () => post(`/api/guild/${state.guild}/gifts/${entry.code}/resend`));
  }
  if (entry.status === 'scratched' || entry.status === 'legacy') {
    action('Marquer utilisé', 'primary', '', () => post(`/api/guild/${state.guild}/gifts/${entry.code}/used`, {used: true}));
  }
  if (entry.status === 'used') {
    action('Annuler l’utilisation', 'danger', 'Rendre ce code de nouveau disponible ?',
           () => post(`/api/guild/${state.guild}/gifts/${entry.code}/used`, {used: false}));
  }
  $('#gift-sheet-actions').replaceChildren(...actions);
  $('#gift-sheet').classList.remove('hidden');
}

function closeGiftSheet() { $('#gift-sheet').classList.add('hidden'); }
$('#gift-sheet-close').onclick = closeGiftSheet;
$('#gift-sheet').onclick = event => { if (event.target.id === 'gift-sheet') closeGiftSheet(); };

async function loadGifts() {
  const data = await api(`/api/guild/${state.guild}/gifts`);
  const c = data.counts || {};
  const sent = ['sent', 'opened', 'scratched', 'expired', 'used', 'dm_failed'].reduce((n, k) => n + (c[k] || 0), 0);
  const opened = (c.opened || 0) + (c.scratched || 0) + (c.expired || 0) + (c.used || 0);
  $('#gift-stats').replaceChildren(
    metric('Liens envoyés', fmt(sent), `${fmt((c.sent || 0) + (c.dm_failed || 0))} pas encore ouverts`, '◇'),
    metric('Liens ouverts', fmt(opened), 'au moins une fois', '◎'),
    metric('Grattés', fmt((c.scratched || 0) + (c.expired || 0) + (c.used || 0)), `${fmt(c.scratched || 0)} disponibles`, '✦'),
    metric('Utilisés', fmt(c.used || 0), `${fmt(c.expired || 0)} expirés`, '✓'),
  );
  const legacy = c.legacy || 0;
  $('#gift-legacy').classList.toggle('hidden', !legacy);
  $('#gift-legacy-title').textContent = `${fmt(legacy)} ancien(s) code(s) envoyé(s) en clair`;
  $('#gift-count').textContent = `· ${fmt(data.total)}`;
  $('#gift-note').textContent = data.public_url ? data.note : 'PUBLIC_URL manquant : René ne peut pas créer les liens des cartes.';
  giftState.items = data.items;
  renderGiftList();
}

let giftFilterTimer;
$('#gift-filter-text').oninput = event => {
  clearTimeout(giftFilterTimer);
  giftFilterTimer = setTimeout(() => { giftState.text = event.target.value.trim(); renderGiftList(); }, 150);
};
for (const button of document.querySelectorAll('#gift-filter button')) {
  button.onclick = () => {
    giftState.filter = button.dataset.filter;
    for (const other of document.querySelectorAll('#gift-filter button')) other.classList.toggle('active', other === button);
    renderGiftList();
  };
}

$('#gift-legacy-run').onclick = async () => {
  const button = $('#gift-legacy-run');
  if (!window.confirm('Envoyer une carte à gratter à chaque ancien gagnant ? Chacun reçoit un nouveau code, l’ancien est désactivé et son MP supprimé.')) return;
  button.textContent = 'Envoi en cours…';
  const result = await withButton(button, () => post(`/api/guild/${state.guild}/gifts/replace-legacy`));
  button.textContent = 'Remplacer';
  if (result) await loadGifts();
};

setInterval(() => {
  for (const pill of document.querySelectorAll('#gift-list [data-expires]')) {
    const left = new Date(pill.dataset.expires).getTime() - Date.now();
    pill.textContent = left > 0 ? `Grattée · ${remainingText(pill.dataset.expires)}` : 'Expirée';
    if (left <= 0) { pill.classList.add('fail'); delete pill.dataset.expires; }
  }
}, 30000);

/* ---------- Roblox ---------- */

const roblox = {key: '', shown: false};

function renderRobloxKey() {
  $('#roblox-key').textContent = !roblox.key ? 'Aucune clé : crée-en une.'
    : roblox.shown ? roblox.key : `${roblox.key.slice(0, 9)}••••••••••••`;
  $('#roblox-show').textContent = roblox.shown ? 'Masquer' : 'Afficher';
  $('#roblox-regenerate').textContent = roblox.key ? 'Nouvelle clé' : 'Créer une clé';
}

async function loadRoblox() {
  const data = await api('/api/system/roblox');
  roblox.key = data.key || '';
  $('#roblox-url').textContent = data.base_url;
  $('#roblox-regenerate').classList.toggle('hidden', data.from_env);
  renderRobloxKey();
}

const loadSettingsBase = loadSettings;
loadSettings = async () => { await Promise.all([loadSettingsBase(), loadRoblox()]); };

async function copyText(text, message) {
  try { await navigator.clipboard.writeText(text); notice(message); haptic([15, 25, 15]); }
  catch { notice('Copie impossible sur cet appareil.', true); }
}

$('#roblox-show').onclick = () => { roblox.shown = !roblox.shown; renderRobloxKey(); };
$('#roblox-copy-key').onclick = () => roblox.key ? copyText(roblox.key, 'Clé copiée.') : notice('Crée d’abord une clé.', true);
$('#roblox-copy-script').onclick = async () => {
  try { await copyText((await api('/api/system/roblox/script')).script, 'Script copié. Colle-le dans un ModuleScript « ReneGiftCodes ».'); }
  catch (error) { notice(error.message, true); }
};
$('#roblox-regenerate').onclick = async () => {
  if (roblox.key && !window.confirm('Créer une nouvelle clé ? L’ancienne cessera de marcher dans Roblox.')) return;
  const result = await withButton($('#roblox-regenerate'), () => post('/api/system/roblox'));
  if (result) { roblox.key = result.key; roblox.shown = true; renderRobloxKey(); }
};
