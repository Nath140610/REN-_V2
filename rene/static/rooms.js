/* Salons de tickets : lire la conversation d'un ticket et y répondre au nom de René
   (texte, embed construit dans le panel, image jointe, mention du membre). */
(() => {
  'use strict';
  const buzz = name => window.reneHaptic?.(name);
  const node = (tag, className = '', text = '') => { const n = document.createElement(tag); n.className = className; if (text) n.textContent = text; return n; };
  const COLORS = ['#0A84FF', '#286EFF', '#965AFF', '#FF46AA', '#FF5F50', '#FFA53C', '#30D158', '#FFF8FF'];
  const CDN = /^https:\/\/(cdn\.discordapp\.com|media\.discordapp\.net|[a-z0-9-]+\.discordapp\.net)\//i;
  const SEEN_KEY = 'rene_ticket_seen';

  const r = {mode: 'rooms', rooms: [], current: null, lastId: null, timer: null, file: null, color: COLORS[0],
             filter: '', fields: [], embedOpen: false, sending: false};

  function seen() { try { return JSON.parse(localStorage.getItem(SEEN_KEY) || '{}'); } catch { return {}; } }
  function markSeen(id, messageId) {
    if (!messageId) return;
    const all = seen();
    all[id] = messageId;
    try { localStorage.setItem(SEEN_KEY, JSON.stringify(all)); } catch {}
  }
  const newer = (a, b) => a && (!b || BigInt(a) > BigInt(b));
  const ago = iso => {
    const minutes = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
    if (minutes < 1) return 'à l’instant';
    if (minutes < 60) return `il y a ${minutes} min`;
    if (minutes < 1440) return `il y a ${Math.round(minutes / 60)} h`;
    return new Date(iso).toLocaleDateString('fr-FR', {day: 'numeric', month: 'short'});
  };

  /* ---------- Mode : salons ou questions ---------- */

  function setMode(mode) {
    r.mode = mode;
    for (const button of document.querySelectorAll('#ticket-mode button')) button.classList.toggle('active', button.dataset.mode === mode);
    $('#rooms-pane').classList.toggle('hidden', mode !== 'rooms');
    $('#questions-pane').classList.toggle('hidden', mode !== 'questions');
    try { localStorage.setItem('rene_ticket_mode', mode); } catch {}
    if (mode !== 'rooms') stopPolling();
    refresh();
  }
  for (const button of document.querySelectorAll('#ticket-mode button')) button.onclick = () => setMode(button.dataset.mode);
  try { if (localStorage.getItem('rene_ticket_mode') === 'questions') setMode('questions'); } catch {}

  const loadTicketsBefore = loadTickets;
  loadTickets = async () => {
    if (r.mode === 'rooms') {
      await Promise.all([loadRooms(), loadTicketsBefore().catch(() => {})]);
      if (r.current) await pollRoom(true);
    } else await loadTicketsBefore();
  };

  /* ---------- Liste des tickets ---------- */

  async function loadRooms() {
    const data = await api(`/api/guild/${state.guild}/ticket-rooms`);
    r.rooms = data.items;
    $('#rooms-category').textContent = `${data.category.name.toUpperCase()} · ${data.items.length} TICKET(S)`;
    renderRooms();
  }

  function renderRooms() {
    const marks = seen();
    const needle = r.filter.toLowerCase();
    const items = r.rooms.filter(room => !needle || [room.name, room.owner?.name, room.owner?.username]
      .some(v => String(v || '').toLowerCase().includes(needle)));
    const host = $('#rooms-items');
    host.replaceChildren(...items.map(room => {
      const row = node('button', `list-row room-row ${room.id === r.current ? 'active' : ''}`);
      row.type = 'button';
      if (room.owner) row.append(Object.assign(node('img', 'avatar'), {src: room.owner.avatar, alt: ''}));
      else row.append(node('span', 'audit-icon', '#'));
      const main = node('div', 'row-main');
      main.append(node('strong', '', room.owner?.name || room.name), node('small', '', `#${room.name} · ${ago(room.last_activity)}`));
      row.append(main);
      if (newer(room.last_message_id, marks[room.id]) && room.id !== r.current) row.append(node('span', 'unread-dot'));
      if (!room.readable) row.append(node('span', 'pill fail', 'Sans accès'));
      row.onclick = () => openRoom(room.id);
      return row;
    }));
    if (!items.length) host.append(node('div', 'empty', r.rooms.length ? 'Aucun ticket ne correspond.' : 'Aucun ticket ouvert.'));
  }
  $('#rooms-filter').oninput = event => { r.filter = event.target.value.trim(); renderRooms(); };

  /* ---------- Conversation ---------- */

  function safeImage(url) {
    return url && CDN.test(url);
  }

  function renderEmbed(embed) {
    const card = node('div', 'd-embed');
    card.style.setProperty('--embed', embed.color || '#3A3A3C');
    const body = node('div', 'd-embed-body');
    if (embed.author) body.append(node('div', 'd-embed-author', embed.author));
    if (embed.title) {
      const title = embed.url ? Object.assign(node('a', 'd-embed-title', embed.title), {href: embed.url, target: '_blank', rel: 'noopener'})
                              : node('div', 'd-embed-title', embed.title);
      body.append(title);
    }
    if (embed.description) body.append(node('div', 'd-embed-text', embed.description));
    if (embed.fields?.length) {
      const grid = node('div', 'd-embed-fields');
      for (const field of embed.fields) {
        const cell = node('div', `d-embed-field ${field.inline ? 'inline' : ''}`);
        cell.append(node('strong', '', field.name), node('div', 'd-embed-text', field.value));
        grid.append(cell);
      }
      body.append(grid);
    }
    const media = embed.image;
    if (media) {
      if (safeImage(media) || media.startsWith('data:')) body.append(Object.assign(node('img', 'd-embed-image'), {src: media, alt: ''}));
      else body.append(Object.assign(node('a', 'd-embed-link', `Image : ${media}`), {href: media, target: '_blank', rel: 'noopener'}));
    }
    if (embed.footer) body.append(node('div', 'd-embed-footer', embed.footer));
    card.append(body);
    if (embed.thumbnail) {
      if (safeImage(embed.thumbnail) || embed.thumbnail.startsWith('data:')) card.append(Object.assign(node('img', 'd-embed-thumb'), {src: embed.thumbnail, alt: ''}));
    }
    return card;
  }

  function renderMessage(item, previous) {
    const grouped = previous && previous.author.id === item.author.id &&
      new Date(item.created_at) - new Date(previous.created_at) < 5 * 60000;
    const row = node('div', `d-message ${grouped ? 'grouped' : ''} ${item.author.is_rene ? 'from-rene' : ''}`);
    row.dataset.id = item.id;
    if (!grouped) {
      row.append(Object.assign(node('img', 'avatar'), {src: item.author.avatar, alt: ''}));
    } else row.append(node('span', 'd-gutter'));
    const main = node('div', 'd-main');
    if (!grouped) {
      const head = node('div', 'd-head');
      head.append(node('strong', '', item.author.name));
      if (item.author.bot) head.append(node('span', 'd-bot', item.author.is_rene ? 'RENÉ' : 'BOT'));
      head.append(node('time', '', new Date(item.created_at).toLocaleString('fr-FR', {dateStyle: 'short', timeStyle: 'short'})));
      main.append(head);
    }
    if (item.content) main.append(node('div', 'd-text', item.content));
    for (const embed of item.embeds) main.append(renderEmbed(embed));
    for (const file of item.attachments) {
      if (file.image && safeImage(file.url)) main.append(Object.assign(node('img', 'd-attachment'), {src: file.url, alt: file.filename}));
      else main.append(Object.assign(node('a', 'd-embed-link', `📎 ${file.filename}`), {href: file.url, target: '_blank', rel: 'noopener'}));
    }
    row.append(main);
    return row;
  }

  function appendMessages(items, initial) {
    const host = $('#room-messages');
    const nearBottom = host.scrollHeight - host.scrollTop - host.clientHeight < 120;
    let previous = r.lastItem;
    for (const item of items) {
      if (host.querySelector(`[data-id="${item.id}"]`)) continue;
      host.append(renderMessage(item, previous));
      previous = item;
    }
    r.lastItem = previous;
    if (items.length) r.lastId = items[items.length - 1].id;
    if (initial || nearBottom) requestAnimationFrame(() => { host.scrollTop = host.scrollHeight; });
  }

  async function openRoom(id) {
    r.current = id;
    r.lastId = null;
    r.lastItem = null;
    $('#rooms-pane').classList.add('has-room');
    $('#room-empty').classList.add('hidden');
    $('#room-head').classList.remove('hidden');
    $('#room-composer').classList.remove('hidden');
    const host = $('#room-messages');
    host.replaceChildren(node('div', 'empty', 'Chargement de la conversation…'));
    buzz('open');
    renderRooms();
    try {
      const data = await api(`/api/guild/${state.guild}/ticket-rooms/${id}/messages`);
      if (r.current !== id) return;
      const owner = data.channel.owner;
      $('#room-avatar').src = owner?.avatar || '/assets/IDLE.png';
      $('#room-name').textContent = owner?.name || `#${data.channel.name}`;
      $('#room-meta').textContent = [`#${data.channel.name}`, owner ? `@${owner.username}` : 'membre non trouvé', data.channel.topic].filter(Boolean).join(' · ');
      $('#room-mention').disabled = !owner;
      $('#room-mention').checked = false;
      host.replaceChildren();
      appendMessages(data.items, true);
      if (!data.items.length) host.append(node('div', 'empty', 'Aucun message dans ce ticket.'));
      markSeen(id, r.lastId);
      renderRooms();
      startPolling();
    } catch (error) {
      host.replaceChildren(node('div', 'empty', error.message));
    }
  }

  function closeRoom() {
    r.current = null;
    stopPolling();
    $('#rooms-pane').classList.remove('has-room');
    $('#room-empty').classList.remove('hidden');
    $('#room-head').classList.add('hidden');
    $('#room-composer').classList.add('hidden');
    $('#room-messages').replaceChildren();
    renderRooms();
    buzz('close');
  }
  $('#room-back').onclick = closeRoom;
  $('#room-refresh').onclick = () => openRoom(r.current);

  async function pollRoom(force = false) {
    if (!r.current || (!force && (state.view !== 'tickets' || r.mode !== 'rooms' || document.hidden))) return;
    const id = r.current;
    try {
      const after = r.lastId ? `?after=${r.lastId}` : '';
      const data = await api(`/api/guild/${state.guild}/ticket-rooms/${id}/messages${after}`);
      if (r.current !== id || !data.items.length) return;
      $('#room-messages .empty')?.remove();
      appendMessages(data.items, false);
      if (data.items.some(item => !item.author.is_rene)) buzz('tick');
      markSeen(id, r.lastId);
    } catch {}
  }
  function startPolling() { stopPolling(); r.timer = setInterval(pollRoom, 5000); }
  function stopPolling() { clearInterval(r.timer); r.timer = null; }

  /* ---------- Constructeur d'embed ---------- */

  const colorHost = $('#embed-colors');
  for (const color of COLORS) {
    const swatch = node('button', 'swatch');
    swatch.type = 'button';
    swatch.style.background = color;
    swatch.dataset.color = color;
    swatch.setAttribute('aria-label', `Couleur ${color}`);
    swatch.onclick = () => { r.color = color; custom.value = color; renderColors(); preview(); };
    colorHost.append(swatch);
  }
  const custom = Object.assign(node('input', 'swatch custom'), {type: 'color', value: COLORS[0]});
  custom.setAttribute('aria-label', 'Autre couleur');
  custom.oninput = () => { r.color = custom.value; renderColors(); preview(); };
  colorHost.append(custom);
  function renderColors() {
    for (const swatch of colorHost.querySelectorAll('button.swatch')) swatch.classList.toggle('active', swatch.dataset.color.toLowerCase() === r.color.toLowerCase());
  }
  renderColors();

  function renderFields() {
    const host = $('#embed-fields');
    host.replaceChildren(...r.fields.map((field, index) => {
      const row = node('div', 'embed-field');
      const name = Object.assign(node('input'), {maxLength: 256, placeholder: 'Nom du champ', value: field.name});
      const value = Object.assign(node('textarea'), {maxLength: 1024, rows: 2, placeholder: 'Valeur', value: field.value});
      const inline = Object.assign(node('input', 'switch'), {type: 'checkbox', checked: field.inline});
      const inlineLabel = node('label', 'switch-row');
      inlineLabel.append(node('span', '', 'Côte à côte'), inline);
      const remove = Object.assign(node('button', 'chip-remove', '×'), {type: 'button'});
      remove.setAttribute('aria-label', 'Retirer le champ');
      name.oninput = () => { field.name = name.value; preview(); };
      value.oninput = () => { field.value = value.value; preview(); };
      inline.onchange = () => { field.inline = inline.checked; preview(); };
      remove.onclick = () => { r.fields.splice(index, 1); renderFields(); preview(); };
      const top = node('div', 'embed-field-top');
      top.append(name, remove);
      row.append(top, value, inlineLabel);
      return row;
    }));
    $('#embed-add-field').classList.toggle('hidden', r.fields.length >= 10);
  }
  $('#embed-add-field').onclick = () => { r.fields.push({name: '', value: '', inline: false}); renderFields(); $('#embed-fields input:last-of-type')?.focus(); };

  function embedValue() {
    const val = id => $(id).value.trim();
    return {author: val('#embed-author'), title: val('#embed-title'), description: val('#embed-description'),
            color: r.color, image: val('#embed-image'), thumbnail: val('#embed-thumbnail'), footer: val('#embed-footer'),
            timestamp: $('#embed-timestamp').checked,
            fields: r.fields.filter(f => f.name.trim() && f.value.trim())};
  }

  function preview() {
    const embed = embedValue();
    if (r.file && $('#room-in-embed').checked) embed.image = r.file.dataUrl;
    const shown = {...embed};
    if (embed.timestamp) shown.footer = [embed.footer, new Date().toLocaleString('fr-FR', {dateStyle: 'short', timeStyle: 'short'})].filter(Boolean).join(' • ');
    const host = $('#embed-preview');
    const empty = !embed.title && !embed.description && !embed.fields.length;
    host.replaceChildren(empty ? node('p', 'footnote', 'Ajoute un titre, une description ou un champ.') : renderEmbed(shown));
  }
  for (const id of ['#embed-author', '#embed-title', '#embed-description', '#embed-image', '#embed-thumbnail', '#embed-footer']) $(id).addEventListener('input', preview);
  $('#embed-timestamp').addEventListener('change', preview);

  function toggleEmbed(open = !r.embedOpen) {
    r.embedOpen = open;
    $('#embed-builder').classList.toggle('hidden', !open);
    $('#room-embed-toggle').classList.toggle('active', open);
    $('#room-in-embed-row').classList.toggle('hidden', !(open && r.file));
    if (open) { preview(); $('#embed-title').focus(); }
  }
  $('#room-embed-toggle').onclick = () => toggleEmbed();

  /* ---------- Image jointe ---------- */

  $('#room-file').onchange = event => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    if (!['image/png', 'image/jpeg', 'image/gif', 'image/webp'].includes(file.type)) { notice('Choisis une image PNG, JPG, GIF ou WebP.', true); return; }
    if (file.size > 8 * 1024 * 1024) { notice('L’image doit faire moins de 8 Mo.', true); return; }
    const reader = new FileReader();
    reader.onload = () => {
      const dataUrl = String(reader.result);
      r.file = {name: file.name, type: file.type, size: file.size, dataUrl, data: dataUrl.split(',')[1]};
      $('#room-attachment-img').src = dataUrl;
      $('#room-attachment-name').textContent = file.name;
      $('#room-attachment-size').textContent = `${(file.size / 1024 / 1024).toFixed(1).replace('.', ',')} Mo`;
      $('#room-attachment').classList.remove('hidden');
      $('#room-in-embed-row').classList.toggle('hidden', !r.embedOpen);
      buzz('select');
      preview();
    };
    reader.readAsDataURL(file);
  };
  function clearFile() {
    r.file = null;
    $('#room-attachment').classList.add('hidden');
    $('#room-in-embed').checked = false;
    preview();
  }
  $('#room-attachment-remove').onclick = clearFile;
  $('#room-in-embed').onchange = preview;

  /* ---------- Envoi ---------- */

  const textArea = $('#room-text');
  textArea.addEventListener('input', () => {
    textArea.style.height = 'auto';
    textArea.style.height = `${Math.min(textArea.scrollHeight, 180)}px`;
  });
  textArea.addEventListener('keydown', event => {
    if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) { event.preventDefault(); $('#room-composer').requestSubmit(); }
  });

  $('#room-composer').onsubmit = async event => {
    event.preventDefault();
    if (!r.current || r.sending) return;
    const content = textArea.value.trim();
    const embed = r.embedOpen ? embedValue() : null;
    const embedEmpty = embed && !embed.title && !embed.description && !embed.fields.length;
    if (embedEmpty && !(r.file && $('#room-in-embed').checked)) { notice('L’embed est vide : ajoute un titre ou une description.', true); return; }
    if (!content && !embed && !r.file) { notice('Écris un message, crée un embed ou joins une image.', true); return; }
    r.sending = true;
    const button = $('#room-send');
    button.disabled = true;
    try {
      const result = await api(`/api/guild/${state.guild}/ticket-rooms/${r.current}/messages`, {method: 'POST', body: JSON.stringify({
        content, embed,
        file: r.file ? {name: r.file.name, type: r.file.type, data: r.file.data} : null,
        image_in_embed: !!(r.file && embed && $('#room-in-embed').checked),
        mention_owner: $('#room-mention').checked,
      })});
      $('#room-messages .empty')?.remove();
      appendMessages([result.item], true);
      markSeen(r.current, r.lastId);
      textArea.value = '';
      textArea.style.height = '';
      clearFile();
      if (embed) {
        for (const id of ['#embed-author', '#embed-title', '#embed-description', '#embed-image', '#embed-thumbnail', '#embed-footer']) $(id).value = '';
        r.fields = [];
        renderFields();
        toggleEmbed(false);
      }
      notice(result.message);
    } catch (error) { notice(error.message, true); }
    finally { r.sending = false; button.disabled = false; }
  };

  /* ---------- Réglage de la catégorie ---------- */

  async function loadTicketSettings() {
    const data = await api(`/api/guild/${state.guild}/ticket-settings`);
    $('#ticket-category').value = data.category_id;
    $('#ticket-category-name').textContent = data.found ? `Catégorie trouvée : ${data.name}` : 'René ne trouve pas cette catégorie sur ce serveur.';
  }
  const loadSettingsBeforeTickets = loadSettings;
  loadSettings = async () => { await Promise.all([loadSettingsBeforeTickets(), loadTicketSettings().catch(() => {})]); };
  $('#ticket-settings-form').onsubmit = async event => {
    event.preventDefault();
    const result = await withButton(event.target.querySelector('button'), () => post(`/api/guild/${state.guild}/ticket-settings`, {category_id: $('#ticket-category').value}));
    if (result) { $('#ticket-category-name').textContent = `Catégorie trouvée : ${result.name}`; r.rooms = []; }
  };

  // Changer de serveur ou quitter la page arrête la lecture en direct.
  $('#guild-select').addEventListener('change', () => { if (r.current) closeRoom(); });
  setInterval(() => { if (state.view !== 'tickets') stopPolling(); else if (r.current && !r.timer && r.mode === 'rooms') startPolling(); }, 3000);
  renderFields();
})();
