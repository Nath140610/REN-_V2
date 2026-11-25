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
  const rewardText = entry.reward?.label || (entry.status === 'replaced' ? '' : '⚠ gain à définir');
  main.append(el('strong', 'gift-code', entry.code), el('small', '', [entry.recipient_name, rewardText, entry.reason, step].filter(Boolean).join(' · ')));
  if (!entry.reward && entry.status !== 'replaced') row.classList.add('missing-reward');
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
    (giftState.filter === 'all' || (giftState.filter === 'noreward' ? needsReward(entry) : groups[giftState.filter].includes(entry.status))) &&
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
  renderRewardEditor(entry);
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
  const missing = data.missing_reward || 0;
  $('#gift-missing').classList.toggle('hidden', !missing);
  $('#gift-missing-title').textContent = `${fmt(missing)} code(s) sans gain`;
  await mountGiftPicker();
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

/* ---------- Mots interdits ---------- */

const wordsState = {words: [], filter: ''};

function renderWords() {
  const needle = wordsState.filter.toLowerCase();
  const host = $('#words-list');
  const items = wordsState.words.filter(word => !needle || word.toLowerCase().includes(needle));
  host.replaceChildren(...items.map(word => {
    const chip = el('span', 'chip');
    const remove = Object.assign(el('button', 'chip-remove', '×'), {type: 'button', title: `Retirer « ${word} »`});
    remove.setAttribute('aria-label', `Retirer ${word}`);
    remove.onclick = async () => {
      const result = await withButton(remove, () => post(`/api/guild/${state.guild}/bad-words`, {action: 'remove', word}));
      if (result) applyWords(result);
    };
    chip.append(el('span', '', word), remove);
    return chip;
  }));
  if (!items.length) empty(host, wordsState.words.length ? 'Aucun mot ne correspond.' : 'La liste est vide : René ne filtre plus rien.');
}

function applyWords(data) {
  wordsState.words = data.words;
  $('#words-count').textContent = `${fmt(data.words.length)} mot(s)${data.custom ? '' : ' · liste par défaut'}`;
  $('#words-reset').classList.toggle('hidden', !data.custom);
  renderWords();
}

async function loadWords() {
  applyWords(await api(`/api/guild/${state.guild}/bad-words`));
}

$('#words-form').onsubmit = async event => {
  event.preventDefault();
  const word = $('#words-input').value.trim();
  if (!word) return;
  const result = await withButton(event.target.querySelector('button'), () => post(`/api/guild/${state.guild}/bad-words`, {action: 'add', word}));
  if (result) { $('#words-input').value = ''; applyWords(result); }
};
$('#words-filter').oninput = event => { wordsState.filter = event.target.value.trim(); renderWords(); };
$('#words-reset').onclick = async () => {
  if (!window.confirm('Remplacer ta liste par celle d’origine de René ?')) return;
  const result = await withButton($('#words-reset'), () => post(`/api/guild/${state.guild}/bad-words`, {action: 'reset'}));
  if (result) applyWords(result);
};
$('#words-test').onsubmit = async event => {
  event.preventDefault();
  const text = $('#words-test-input').value.trim();
  if (!text) return;
  try {
    const result = await post(`/api/guild/${state.guild}/bad-words/test`, {text});
    const box = $('#words-test-result');
    box.textContent = result.message;
    box.className = `test-result ${result.blocked ? 'bad' : 'good'}`;
  } catch (error) { notice(error.message, true); }
};

/* ---------- Sondages ---------- */

const pollState = {hours: 24, cards: new Map(), channelsFor: ''};

function answerInput(value = '') {
  const row = el('div', 'poll-answer');
  const input = Object.assign(el('input'), {maxLength: 55, placeholder: 'Réponse', value});
  input.setAttribute('aria-label', 'Réponse');
  const remove = Object.assign(el('button', 'chip-remove', '×'), {type: 'button'});
  remove.setAttribute('aria-label', 'Retirer cette réponse');
  remove.onclick = () => { row.remove(); updateAnswerButtons(); };
  row.append(input, remove);
  return row;
}

function updateAnswerButtons() {
  const rows = $('#poll-answers').children;
  for (const row of rows) row.querySelector('button').classList.toggle('hidden', rows.length <= 2);
  $('#poll-add-answer').classList.toggle('hidden', rows.length >= 10);
  [...rows].forEach((row, i) => { row.querySelector('input').placeholder = `Réponse ${i + 1}`; });
}

function resetPollForm() {
  $('#poll-form').reset();
  $('#poll-answers').replaceChildren(answerInput(), answerInput());
  updateAnswerButtons();
}

$('#poll-add-answer').onclick = () => {
  const row = answerInput();
  $('#poll-answers').append(row);
  updateAnswerButtons();
  row.querySelector('input').focus();
};
for (const button of document.querySelectorAll('#poll-duration button')) {
  button.onclick = () => {
    pollState.hours = Number(button.dataset.hours);
    for (const other of document.querySelectorAll('#poll-duration button')) other.classList.toggle('active', other === button);
  };
}

async function loadPollChannels() {
  if (pollState.channelsFor === state.guild) return;
  const data = await api(`/api/guild/${state.guild}/channels`);
  const select = $('#poll-channel');
  select.replaceChildren(Object.assign(el('option', '', 'Choisir un salon'), {value: ''}));
  for (const channel of data.items) {
    const option = el('option', '', `# ${channel.name}${channel.category ? ` · ${channel.category}` : ''}`);
    option.value = channel.id;
    select.append(option);
  }
  pollState.channelsFor = state.guild;
}

function timeLeft(expiresAt) {
  const left = new Date(expiresAt).getTime() - Date.now();
  if (left <= 0) return 'se termine…';
  const hours = Math.floor(left / 3600000), minutes = Math.floor(left / 60000) % 60;
  if (hours >= 48) return `encore ${Math.round(hours / 24)} jours`;
  return hours ? `encore ${hours} h ${String(minutes).padStart(2, '0')}` : `encore ${minutes} min`;
}

function pollCard(entry) {
  let card = pollState.cards.get(entry.id);
  if (!card) {
    card = el('article', 'card poll-card');
    const head = el('div', 'card-head');
    const titles = el('div');
    titles.append(el('h3', 'poll-question'), el('small', 'muted poll-meta'));
    const actions = el('div', 'poll-actions');
    const link = Object.assign(el('a', 'text-button', 'Discord ↗'), {target: '_blank', rel: 'noopener'});
    const end = Object.assign(el('button', 'mini ban', 'Terminer'), {type: 'button'});
    end.onclick = async () => {
      if (!window.confirm('Terminer ce sondage maintenant ?')) return;
      if (await withButton(end, () => post(`/api/guild/${state.guild}/polls/${entry.id}/end`))) await loadPolls();
    };
    actions.append(link, end);
    head.append(titles, actions);
    const answers = el('div', 'poll-results');
    entry.answers.forEach(() => {
      const row = el('div', 'poll-row');
      const label = el('div', 'poll-label');
      label.append(el('span', 'poll-text'), el('span', 'poll-count'));
      const track = el('div', 'poll-track');
      track.append(el('div', 'poll-fill'));
      row.append(label, track);
      answers.append(row);
    });
    card.append(head, answers);
    pollState.cards.set(entry.id, card);
  }
  card.querySelector('.poll-question').textContent = entry.question;
  const status = entry.deleted ? 'Message supprimé' : entry.finished ? 'Terminé' : timeLeft(entry.expires_at);
  card.querySelector('.poll-meta').textContent =
    `#${entry.channel_name} · ${fmt(entry.total)} vote(s) · ${status}${entry.multiple ? ' · choix multiple' : ''}`;
  card.querySelector('a').href = `https://discord.com/channels/${entry.guild_id}/${entry.channel_id}/${entry.message_id}`;
  card.querySelector('.poll-actions .mini').classList.toggle('hidden', entry.finished);
  card.classList.toggle('finished', !!entry.finished);
  const results = entry.results || [];
  const votes = results.reduce((sum, n) => sum + n, 0);
  const best = Math.max(0, ...results);
  card.querySelectorAll('.poll-row').forEach((row, i) => {
    const count = results[i] || 0;
    const share = votes ? Math.round(count / votes * 100) : 0;
    row.classList.toggle('leader', count > 0 && count === best);
    row.querySelector('.poll-text').textContent = entry.answers[i];
    row.querySelector('.poll-count').textContent = `${share} % · ${fmt(count)}`;
    row.querySelector('.poll-fill').style.width = `${share}%`;
  });
  return card;
}

async function loadPolls(quiet = false) {
  if (!quiet) {
    await loadPollChannels();
    if (!$('#poll-answers').children.length) resetPollForm();
  }
  const data = await api(`/api/guild/${state.guild}/polls`);
  const host = $('#poll-list');
  const cards = data.items.map(pollCard);
  host.replaceChildren(...cards);
  if (!cards.length) empty(host, 'Aucun sondage pour l’instant.');
}

$('#poll-form').onsubmit = async event => {
  event.preventDefault();
  const form = event.target;
  const answers = [...$('#poll-answers').querySelectorAll('input')].map(input => input.value.trim()).filter(Boolean);
  if (!form.elements.namedItem('channel_id').value) { notice('Choisis un salon.', true); return; }
  if (answers.length < 2) { notice('Ajoute au moins deux réponses.', true); return; }
  const result = await withButton(form.querySelector('button[type=submit]'), () => post(`/api/guild/${state.guild}/polls`, {
    channel_id: form.elements.namedItem('channel_id').value,
    question: form.elements.namedItem('question').value,
    answers, hours: pollState.hours, multiple: form.elements.namedItem('multiple').checked,
  }));
  if (result) {
    const channel = form.elements.namedItem('channel_id').value;
    resetPollForm();
    form.elements.namedItem('channel_id').value = channel;
    await loadPolls(true);
  }
};

setInterval(() => {
  if (state.view === 'polls' && state.csrf && !document.hidden) loadPolls(true).catch(() => {});
}, 5000);

const previousGuildChangePolls = $('#guild-select').onchange;
$('#guild-select').onchange = () => {
  pollState.cards.clear();
  pollState.channelsFor = '';
  previousGuildChangePolls();
};

/* ---------- Statistiques ---------- */

const statsState = {days: 30};
const pct = value => value == null ? '—' : `${value} %`;

function humanDuration(seconds) {
  if (seconds == null) return '—';
  if (seconds < 3600) return `${Math.max(1, Math.round(seconds / 60))} min`;
  if (seconds < 86400) { const h = Math.floor(seconds / 3600); const m = Math.round(seconds % 3600 / 60); return m ? `${h} h ${String(m).padStart(2, '0')}` : `${h} h`; }
  return `${Math.round(seconds / 86400)} j`;
}

function statCard(label, value, sub, icon, delta = null, inverse = false) {
  const card = metric(label, value, sub, icon);
  if (delta != null) {
    const good = inverse ? delta <= 0 : delta >= 0;
    const pill = el('span', `delta ${delta === 0 ? 'flat' : good ? 'up' : 'down'}`, `${delta > 0 ? '↑' : delta < 0 ? '↓' : '→'} ${Math.abs(delta)} %`);
    pill.title = 'Par rapport à la période précédente';
    card.querySelector('strong').append(pill);
  }
  return card;
}

function svgNode(tag, attrs, parent) {
  const node = document.createElementNS('http://www.w3.org/2000/svg', tag);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
  parent.append(node);
  return node;
}

function lineChart(host, rows, key) {
  host.replaceChildren();
  const values = rows.map(row => row[key]);
  const w = 620, h = 170, top = 10, max = Math.max(1, ...values);
  const svg = svgNode('svg', {viewBox: '0 0 650 225', preserveAspectRatio: 'none', role: 'img', 'aria-label': 'Messages par jour'}, host);
  const defs = svgNode('defs', {}, svg);
  const grad = svgNode('linearGradient', {id: 'stats-area', x1: 0, x2: 0, y1: 0, y2: 1}, defs);
  svgNode('stop', {offset: '0%', 'stop-color': '#965AFF', 'stop-opacity': '.32'}, grad);
  svgNode('stop', {offset: '100%', 'stop-color': '#286EFF', 'stop-opacity': '0'}, grad);
  const stroke = svgNode('linearGradient', {id: 'stats-line', x1: 0, x2: 1, y1: 0, y2: 0}, defs);
  [['0%', '#286EFF'], ['50%', '#965AFF'], ['100%', '#FF46AA']].forEach(([o, c]) => svgNode('stop', {offset: o, 'stop-color': c}, stroke));
  for (let i = 0; i < 4; i++) {
    const y = top + i * (h / 3);
    svgNode('line', {x1: 0, x2: w, y1: y, y2: y}, svg);
    svgNode('text', {x: w + 8, y: y + 4}, svg).textContent = fmt(max * (3 - i) / 3);
  }
  const step = values.length > 1 ? w / (values.length - 1) : w;
  const d = values.map((v, i) => `${i ? 'L' : 'M'} ${(i * step).toFixed(1)} ${(top + h - v / max * h).toFixed(1)}`).join(' ');
  svgNode('path', {d: `${d} L ${w} ${top + h} L 0 ${top + h} Z`, fill: 'url(#stats-area)'}, svg);
  svgNode('path', {d, fill: 'none', stroke: 'url(#stats-line)', 'stroke-width': 3, 'stroke-linecap': 'round', 'stroke-linejoin': 'round'}, svg);
  const marks = [0, Math.floor((rows.length - 1) / 2), rows.length - 1];
  for (const i of marks) {
    const label = svgNode('text', {x: i * step, y: 215, 'text-anchor': i === 0 ? 'start' : i === rows.length - 1 ? 'end' : 'middle'}, svg);
    label.textContent = new Date(`${rows[i].date}T12:00:00`).toLocaleDateString('fr-FR', {day: 'numeric', month: 'short'});
  }
}

function barChart(host, rows, series) {
  host.replaceChildren();
  const max = Math.max(1, ...rows.flatMap(row => series.map(s => s.value(row))));
  for (const row of rows) {
    const group = el('div', 'flow-group');
    group.title = `${date(row.date)} · ${series.map(s => `${s.label} : ${s.format ? s.format(s.value(row)) : fmt(s.value(row))}`).join(' · ')}`;
    for (const s of series) {
      const bar = el('div', `flow-bar ${s.className}`);
      bar.style.height = `${Math.max(s.value(row) ? 4 : 1, s.value(row) / max * 100)}%`;
      group.append(bar);
    }
    host.append(group);
  }
}

function weekdayChart(host, weekdays) {
  host.replaceChildren();
  const max = Math.max(1, ...weekdays.map(d => d.messages));
  const best = Math.max(...weekdays.map(d => d.messages));
  for (const day of weekdays) {
    const col = el('div', `weekday ${day.messages && day.messages === best ? 'best' : ''}`);
    const track = el('div', 'weekday-track');
    const bar = el('div', 'weekday-bar');
    bar.style.height = `${Math.max(3, day.messages / max * 100)}%`;
    track.append(bar);
    col.append(el('small', 'weekday-value', fmt(day.messages)), track, el('span', '', day.day));
    host.append(col);
  }
}

function topList(host, items, format) {
  host.replaceChildren(...items.map((item, i) => {
    const row = el('div', 'top-row');
    row.append(el('span', 'rank', String(i + 1)), Object.assign(el('img', 'avatar'), {src: item.avatar, alt: ''}));
    const main = el('div', 'row-main');
    main.append(el('strong', '', item.name));
    row.append(main, el('span', 'row-value', format(item.value)));
    return row;
  }));
  if (!items.length) empty(host, 'Pas encore de données sur cette période.');
}

function funnel(host, g) {
  host.replaceChildren();
  host.append(el('h3', '', 'Parcours des cartes'));
  const steps = [['Envoyées', g.cards], ['Ouvertes', g.opened], ['Grattées', g.scratched], ['Utilisées', g.used]];
  const max = Math.max(1, g.cards);
  for (const [label, value] of steps) {
    const row = el('div', 'poll-row');
    const top = el('div', 'poll-label');
    top.append(el('span', 'poll-text', label), el('span', 'poll-count', `${fmt(value)} · ${Math.round(value / max * 100)} %`));
    const track = el('div', 'poll-track');
    const fill = el('div', 'poll-fill');
    track.append(fill);
    row.append(top, track);
    host.append(row);
    requestAnimationFrame(() => { fill.style.width = `${Math.min(100, value / max * 100)}%`; });
  }
  host.append(el('p', 'footnote', `Délai moyen entre l’envoi et le grattage : ${humanDuration(g.avg_scratch_seconds)} · ${fmt(g.assistance)} code(s) activé(s) par l’assistance.`));
}

async function loadStats() {
  const data = await api(`/api/guild/${state.guild}/stats?days=${statsState.days}`);
  const c = data.community, a = data.activity, m = data.moderation, t = data.tickets, g = data.gifts;
  $('#stats-coverage').textContent = data.tracked_days < data.days
    ? `Suivi depuis ${fmt(data.tracked_days)} jour(s) : période incomplète.`
    : data.has_previous ? 'Comparé à la période précédente.' : '';
  $('#stats-community').replaceChildren(
    statCard('Membres', fmt(c.members), `${fmt(c.humans)} humains · ${fmt(c.online)} en ligne`, '♙'),
    statCard('Arrivées', fmt(c.joins), `${statsState.days} jours`, '↗', c.joins_change),
    statCard('Départs', fmt(c.leaves), `${statsState.days} jours`, '↘', c.leaves_change, true),
    statCard('Solde', `${c.net > 0 ? '+' : ''}${fmt(c.net)}`, c.net >= 0 ? 'le serveur grandit' : 'plus de départs', '±'),
  );
  $('#stats-activity').replaceChildren(
    statCard('Messages', fmt(a.messages), `${String(a.per_day).replace('.', ',')} par jour`, '❝', a.messages_change),
    statCard('Membres actifs', fmt(a.active), `${pct(a.active_rate)} des humains`, '◉', a.active_change),
    statCard('Vocal', `${String(a.voice_hours).replace('.', ',')} h`, `${fmt(a.voice_per_active_min)} min par actif`, '◎', a.voice_change),
    statCard('Record', a.busiest ? fmt(a.busiest.messages) : '—', a.busiest ? `messages le ${date(a.busiest.date)}` : 'pas encore de messages', '★'),
  );
  $('#stats-busiest').textContent = `${statsState.days} jours`;
  lineChart($('#stats-messages-chart'), data.daily, 'messages');
  weekdayChart($('#stats-weekdays'), a.weekdays);
  barChart($('#stats-flow'), data.daily, [
    {label: 'Arrivées', className: 'blue', value: row => row.joins},
    {label: 'Départs', className: 'pink', value: row => row.leaves},
  ]);
  barChart($('#stats-voice'), data.daily, [
    {label: 'Vocal', className: 'violet', value: row => row.voice_seconds / 3600, format: v => `${v.toFixed(1)} h`},
  ]);
  topList($('#stats-top-messages'), data.top_messages, v => `${fmt(v)} msg`);
  topList($('#stats-top-voice'), data.top_voice, v => humanDuration(v));
  const reasons = Object.entries(m.reasons).filter(([, n]) => n).map(([k, n]) => `${k} ${n}`).join(' · ') || 'aucun';
  $('#stats-moderation').replaceChildren(
    statCard('Avertissements', fmt(m.warnings), reasons, '⚠', m.warnings_change, true),
    statCard('Bannissements', fmt(m.bans), `${fmt(m.tempbans_now)} en cours · ${fmt(m.members_with_warnings)} membres avertis`, '⚒'),
    statCard('Tickets', fmt(t.received), `${fmt(t.answered)} répondus · ${fmt(t.open)} ouverts`, '✉'),
    statCard('Temps de réponse', humanDuration(t.avg_response_seconds), `${fmt(t.by_rene)} réponse(s) de René`, '⏱'),
  );
  $('#stats-gifts').replaceChildren(
    statCard('Cartes envoyées', fmt(g.cards), `${statsState.days} jours`, '◇'),
    statCard('Ouverture', pct(g.open_rate), `${fmt(g.opened)} lien(s) ouvert(s)`, '◎'),
    statCard('Grattage', pct(g.scratch_rate), `${fmt(g.scratched)} carte(s) grattée(s)`, '✦'),
    statCard('Utilisés dans Roblox', fmt(g.used), `${pct(g.use_rate)} des grattés · ${fmt(g.expired_unused)} expirés`, '✓'),
  );
  funnel($('#stats-funnel'), g);
  const p = data.polls, r = data.appointments;
  $('#stats-other').replaceChildren(
    statCard('Sondages', fmt(p.count), `${fmt(p.votes)} vote(s)`, '▥'),
    statCard('Rendez-vous', fmt(r.count), `${fmt(r.accepted)} accepté(s)`, '▣'),
    statCard('Absences', fmt(r.no_show), `${pct(r.no_show_rate)} des rendez-vous acceptés`, '✕'),
    statCard('Suivi', `${fmt(data.tracked_days)} j`, `depuis le ${date(data.since)}`, '◷'),
  );
}

for (const button of document.querySelectorAll('#stats-period button')) {
  button.onclick = () => {
    statsState.days = Number(button.dataset.days);
    for (const other of document.querySelectorAll('#stats-period button')) other.classList.toggle('active', other === button);
    loadStats().catch(error => notice(error.message, true));
  };
}

/* ---------- MP à tous les membres ---------- */

const broadcastState = {rolesFor: '', roles: [], humans: 0, timer: null};

function broadcastTarget() {
  const id = $('#broadcast-role').value;
  if (!id) return broadcastState.humans;
  return broadcastState.roles.find(role => role.id === id)?.members ?? 0;
}

function updateBroadcastCount() {
  $('#broadcast-count').textContent = `${fmt(broadcastTarget())} destinataire(s)`;
}

function renderBroadcast(data) {
  broadcastState.humans = data.humans;
  updateBroadcastCount();
  const job = data.job;
  const running = data.running;
  $('#broadcast-progress').classList.toggle('hidden', !job);
  $('#broadcast-form').querySelector('button[type=submit]').disabled = running;
  if (job) {
    const share = job.total ? Math.round(job.done / job.total * 100) : 0;
    const states = {running: 'Envoi en cours', finished: 'Envoi terminé', cancelled: 'Envoi arrêté', error: 'Envoi interrompu'};
    $('#broadcast-label').textContent = `${states[job.state] || job.state} · ${job.role_name}`;
    $('#broadcast-numbers').textContent = `${fmt(job.done)} / ${fmt(job.total)} · ${fmt(job.sent)} reçus · ${fmt(job.failed)} MP fermés`;
    $('#broadcast-fill').style.width = `${share}%`;
    $('#broadcast-cancel').classList.toggle('hidden', !running);
  }
  const host = $('#broadcast-history');
  host.replaceChildren(...data.history.filter(item => !job || item.id !== job.id || !running).slice(0, 5).map(item => {
    const row = el('div', 'list-row');
    row.append(el('span', 'audit-icon', '✉'));
    const main = el('div', 'row-main');
    main.append(el('strong', '', item.preview), el('small', '', `${item.role_name} · ${when(item.started_at)} · ${fmt(item.sent)} reçus sur ${fmt(item.total)}`));
    row.append(main);
    return row;
  }));
  clearTimeout(broadcastState.timer);
  if (running) broadcastState.timer = setTimeout(() => { if (state.view === 'messages') loadBroadcast(true).catch(() => {}); }, 2000);
}

async function loadBroadcast(quiet = false) {
  if (!quiet && broadcastState.rolesFor !== state.guild) {
    broadcastState.roles = (await api(`/api/guild/${state.guild}/roles`)).items;
    const select = $('#broadcast-role');
    select.replaceChildren(Object.assign(el('option', '', 'Tous les membres'), {value: ''}),
      ...broadcastState.roles.map(role => Object.assign(el('option', '', `${role.name} (${role.members})`), {value: role.id})));
    broadcastState.rolesFor = state.guild;
  }
  renderBroadcast(await api(`/api/guild/${state.guild}/broadcast`));
}

$('#broadcast-role').onchange = updateBroadcastCount;
$('#broadcast-form').onsubmit = async event => {
  event.preventDefault();
  const message = $('#broadcast-message').value.trim();
  if (!message) return;
  const total = broadcastTarget();
  const minutes = Math.max(1, Math.round(total * 1.5 / 60));
  if (!window.confirm(`Envoyer ce message en MP à ${total} membre(s) ?\nDurée estimée : ${minutes} min. Tu pourras arrêter l’envoi.`)) return;
  const result = await withButton(event.target.querySelector('button[type=submit]'), () => post(`/api/guild/${state.guild}/broadcast`, {
    message, role_id: $('#broadcast-role').value,
  }));
  if (result) { $('#broadcast-message').value = ''; await loadBroadcast(true); }
};
$('#broadcast-cancel').onclick = async () => {
  if (!window.confirm('Arrêter l’envoi ? Ceux qui l’ont déjà reçu le gardent.')) return;
  if (await withButton($('#broadcast-cancel'), () => post(`/api/guild/${state.guild}/broadcast/cancel`))) await loadBroadcast(true);
};

/* ---------- Demandes de l'assistance ---------- */

const assistState = {items: [], filter: 'all', text: ''};
const ASSIST_SEEN = 'rene_assist_seen';

function assistCard(item) {
  const ok = item.outcome === 'accepted';
  const card = el('article', `card ticket assist-request ${ok ? 'ok' : 'no'}`);
  const head = el('div', 'ticket-head');
  head.append(el('span', `audit-icon ${ok ? 'blue' : ''}`, ok ? '✓' : '✕'));
  const who = el('div', 'row-main');
  who.append(el('strong', '', `${item.signature} · ${item.member_name}`), el('small', '', `@${item.member_username} · demande du ${when(item.created_at)}`));
  head.append(who, el('span', `pill ${ok ? '' : 'fail'}`, ok ? 'Activé 24 h' : 'Refusé'));
  const details = el('div', 'assist-details');
  const line = (label, value) => { const row = el('div'); row.append(el('small', '', label), el('span', '', value)); details.append(row); };
  line('Code', item.code);
  line('Problème le', when(item.incident_at));
  line('Gain', item.reward?.label || '—');
  line('Raison', item.reason);
  line('Résultat', ok ? `Activé jusqu’au ${when(item.expires_at)}` : item.detail.replace(/^Impossible : (.)/, (_, first) => first.toUpperCase()));
  if (!ok && item.same_member === false) line('Attention', 'Ce code appartient à un autre membre.');
  details.querySelector('span').className = 'gift-code';
  card.append(head, details);
  return card;
}

function renderAssistance() {
  const needle = assistState.text.toLowerCase();
  const items = assistState.items.filter(item =>
    (assistState.filter === 'all' || item.outcome === assistState.filter) &&
    (!needle || [item.code, item.member_name, item.member_username, item.signature, item.reason].some(v => String(v || '').toLowerCase().includes(needle))));
  const host = $('#assist-list');
  host.replaceChildren(...items.map(assistCard));
  if (!items.length) empty(host, assistState.items.length ? 'Aucune demande ne correspond.' : 'L’assistance n’a encore rien demandé.');
}

function updateAssistBadge(items) {
  let seen = '';
  try { seen = localStorage.getItem(ASSIST_SEEN) || ''; } catch {}
  const fresh = items.filter(item => item.created_at > seen).length;
  const badge = $('#assist-badge');
  badge.textContent = fresh > 99 ? '99+' : String(fresh);
  badge.classList.toggle('hidden', !fresh || state.view === 'assistance');
}

async function loadAssistance() {
  const data = await api(`/api/guild/${state.guild}/assistance`);
  assistState.items = data.items;
  $('#assist-stats').replaceChildren(
    metric('Demandes', fmt(data.total), `${fmt(data.today)} aujourd’hui`, '✚'),
    metric('Codes activés', fmt(data.accepted), 'pendant 24 h', '✓'),
    metric('Refusées', fmt(data.refused), 'code déjà existant', '✕'),
    metric('Assistants', fmt(new Set(data.items.map(item => item.signature.toLowerCase())).size), 'signatures différentes', '✎'),
  );
  if (data.items[0]) { try { localStorage.setItem(ASSIST_SEEN, data.items[0].created_at); } catch {} }
  updateAssistBadge(data.items);
  renderAssistance();
}

$('#assist-filter-text').oninput = event => { assistState.text = event.target.value.trim(); renderAssistance(); };
for (const button of document.querySelectorAll('#assist-filter button')) {
  button.onclick = () => {
    assistState.filter = button.dataset.filter;
    for (const other of document.querySelectorAll('#assist-filter button')) other.classList.toggle('active', other === button);
    renderAssistance();
  };
}

function refreshAssistBadge() {
  if (!state.csrf || !state.guild || state.view === 'assistance') return;
  api(`/api/guild/${state.guild}/assistance`).then(data => updateAssistBadge(data.items)).catch(() => {});
}
setInterval(() => { if (!document.hidden) refreshAssistBadge(); }, 90000);
setTimeout(refreshAssistBadge, 5000);

/* ---------- Réglages : accès Assistance ---------- */

const assistAccess = {password: '', shown: false, url: ''};
function renderAssistAccess() {
  $('#assist-url').textContent = assistAccess.url;
  $('#assist-password-view').textContent = !assistAccess.password ? 'Aucun : crée-en un pour ouvrir l’assistance.'
    : assistAccess.shown ? assistAccess.password : '••••••••••••';
  $('#assist-show').textContent = assistAccess.shown ? 'Masquer' : 'Afficher';
  $('#assist-regenerate').textContent = assistAccess.password ? 'Nouveau mot de passe' : 'Créer un mot de passe';
}
async function loadAssistAccess() {
  const data = await api('/api/system/assistance');
  Object.assign(assistAccess, {password: data.password || '', url: data.url});
  $('#assist-regenerate').classList.toggle('hidden', data.from_env);
  renderAssistAccess();
}
const loadSettingsWithRoblox = loadSettings;
loadSettings = async () => { await Promise.all([loadSettingsWithRoblox(), loadAssistAccess()]); };
$('#assist-show').onclick = () => { assistAccess.shown = !assistAccess.shown; renderAssistAccess(); };
$('#assist-copy-url').onclick = () => copyText(assistAccess.url, 'Lien de l’assistance copié.');
$('#assist-copy-password').onclick = () => assistAccess.password ? copyText(assistAccess.password, 'Mot de passe copié.') : notice('Crée d’abord un mot de passe.', true);
$('#assist-regenerate').onclick = async () => {
  if (assistAccess.password && !window.confirm('Créer un nouveau mot de passe ? Les assistants connectés seront déconnectés.')) return;
  const result = await withButton($('#assist-regenerate'), () => post('/api/system/assistance'));
  if (result) { assistAccess.password = result.password; assistAccess.shown = true; renderAssistAccess(); }
};

const previousGuildChangeStats = $('#guild-select').onchange;
$('#guild-select').onchange = () => {
  broadcastState.rolesFor = '';
  previousGuildChangeStats();
};

/* ---------- Gains par jeu ---------- */

let rewardCatalog = null;
let giftPicker = null;
let sheetPicker = null;
let sheetEntry = null;

async function ensureCatalog() {
  if (!rewardCatalog) rewardCatalog = (await api('/api/rewards')).games;
  return rewardCatalog;
}

async function mountGiftPicker() {
  if (giftPicker) return;
  giftPicker = window.ReneRewards.mount($('#gift-reward'), await ensureCatalog());
}

function needsReward(entry) {
  return !entry.reward && entry.status !== 'replaced';
}

function renderRewardEditor(entry) {
  sheetEntry = entry;
  const box = $('#gift-reward-box');
  box.classList.toggle('hidden', entry.status === 'replaced' || !rewardCatalog);
  if (entry.status === 'replaced' || !rewardCatalog) return;
  $('#gift-reward-current').textContent = entry.reward?.label || 'Pas encore défini';
  $('#gift-reward-current').classList.toggle('warn-text', !entry.reward);
  sheetPicker = window.ReneRewards.mount($('#gift-reward-editor'), rewardCatalog);
  if (entry.reward) sheetPicker.set(entry.reward);
  $('#gift-reward-save').textContent = entry.reward ? 'Modifier le gain' : 'Enregistrer le gain';
}

$('#gift-reward-save').onclick = async () => {
  if (!sheetEntry || !sheetPicker) return;
  const problem = sheetPicker.error();
  if (problem) { notice(problem, true); return; }
  const code = sheetEntry.code;
  const result = await withButton($('#gift-reward-save'), () => post(`/api/guild/${state.guild}/gifts/${code}/reward`, {reward: sheetPicker.value()}));
  if (!result) return;
  await loadGifts();
  // En mode « Sans gain », on enchaîne directement sur le code suivant à compléter.
  const next = giftState.filter === 'noreward' ? giftState.items.find(needsReward) : null;
  if (next) openGiftSheet(next);
  else {
    const updated = giftState.items.find(item => item.code === code);
    if (updated) openGiftSheet(updated); else closeGiftSheet();
  }
};

$('#gift-missing-run').onclick = () => {
  giftState.filter = 'noreward';
  for (const button of document.querySelectorAll('#gift-filter button')) button.classList.toggle('active', button.dataset.filter === 'noreward');
  renderGiftList();
  const first = giftState.items.find(needsReward);
  if (first) openGiftSheet(first);
};

// Envoi d'une carte : le gain est obligatoire et vérifié avant le QR.
$('#gift-form').onsubmit = async event => {
  event.preventDefault();
  const form = event.target;
  const memberId = form.elements.namedItem('user_id').value;
  if (!memberId) { notice('Choisis un membre dans les résultats de recherche.', true); return; }
  const problem = giftPicker ? giftPicker.error() : 'Le choix du gain n’a pas chargé. Recharge la page.';
  if (problem) { notice(problem, true); haptic([35, 35, 35]); return; }
  const button = form.querySelector('button[type=submit]');
  button.disabled = true;
  try {
    const result = await api(`/api/guild/${state.guild}/gift/challenge`, {method: 'POST', body: JSON.stringify({
      user_id: memberId, reason: form.elements.namedItem('reason').value, reward: giftPicker.value(),
    })});
    qrChallenge = result.challenge_id;
    $('#qr-dialog').classList.remove('hidden');
    $('#qr-feedback').textContent = 'Ouverture de la caméra…';
    haptic([20, 40, 20]);
    startQrCamera();
  } catch (error) { notice(error.message, true); haptic([35, 35, 35]); }
  finally { button.disabled = false; }
};

const confirmQrBase = confirmQr;
confirmQr = async text => {
  await confirmQrBase(text);
  if (!qrChallenge) giftPicker?.reset();
};
