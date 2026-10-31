/* Fonctions du panel ajoutées sans dépendance réseau côté navigateur. */
const pickerTimers = {};
let qrChallenge = null;
let qrStream = null;
let qrScanning = false;
let qrSubmitting = false;

function haptic(pattern = 12) {
  try {
    if (localStorage.getItem('rene_haptics') !== 'off') navigator.vibrate?.(pattern);
  } catch {}
}

function navigate(view) {
  state.view = view;
  for (const node of document.querySelectorAll('.view')) node.classList.toggle('hidden', node.id !== `view-${view}`);
  for (const node of document.querySelectorAll('.nav')) node.classList.toggle('active', node.dataset.view === view);
  const names = {overview:"Vue d'ensemble", members:'Membres', gifts:'Codes cadeau', presence:'Présence', appointments:'Rendez-vous', messages:'Messages privés', settings:'Réglages', ai:'René IA'};
  const subtitles = {overview:'Les chiffres du serveur, mis à jour par René.', members:'Retrouve les personnes du serveur et gère la modération.', gifts:'Envoie et retrouve les codes distribués.', presence:'Classement selon la dernière présence observée.', appointments:'Programme et suis les rendez-vous.', messages:'Envoie un courrier privé à un membre.', settings:'Contrôle le statut et le service de René.', ai:'Une analyse claire de tes statistiques Discord.'};
  $('#page-title').textContent = names[view] || view;
  $('#crumb').textContent = names[view] || view;
  $('#page-subtitle').textContent = subtitles[view] || '';
  $('.sidebar').classList.remove('open');
  haptic();
  refresh();
}

async function refresh() {
  if (!state.guild) return;
  try {
    if (state.view === 'overview') await loadOverview();
    if (state.view === 'members') await loadMembers();
    if (state.view === 'gifts') await loadGifts();
    if (state.view === 'presence') await loadPresence();
    if (state.view === 'appointments') await loadAppointments();
    if (state.view === 'settings') await loadSettings();
  } catch (error) { notice(error.message, true); haptic([35, 35, 35]); }
}

function selectPicker(kind, member) {
  const root = document.querySelector(`[data-picker="${kind}"]`);
  if (!root) return;
  root.querySelector('input[type=search]').value = member.name;
  root.querySelector('input[name=user_id]').value = member.id;
  root.querySelector('.picker-selected').textContent = `Sélection : ${member.name}`;
  root.querySelector('.picker-results').replaceChildren();
  haptic([12, 30, 12]);
}

function resetPicker(kind) {
  const root = document.querySelector(`[data-picker="${kind}"]`);
  root.querySelector('input[name=user_id]').value = '';
  root.querySelector('input[type=search]').value = '';
  root.querySelector('.picker-selected').textContent = '';
  root.querySelector('.picker-results').replaceChildren();
}

async function findPickerMembers(kind, query) {
  if (!state.guild) return;
  const root = document.querySelector(`[data-picker="${kind}"]`);
  const input = root.querySelector('input[type=search]');
  const data = await api(`/api/guild/${state.guild}/member-search?q=${encodeURIComponent(query)}`);
  if (input.value.trim() !== query) return;
  const results = root.querySelector('.picker-results');
  results.replaceChildren();
  for (const member of data.items) {
    const button = el('button', 'picker-option');
    button.type = 'button';
    const avatar = Object.assign(el('img'), {src: member.avatar, alt: ''});
    const label = el('span');
    label.append(el('strong', '', member.name), el('small', '', member.username));
    button.append(avatar, label);
    button.onclick = () => selectPicker(kind, member);
    results.append(button);
  }
  if (!data.items.length) results.append(el('div', 'empty', 'Aucun membre trouvé.'));
}

for (const root of document.querySelectorAll('[data-picker]')) {
  const kind = root.dataset.picker;
  const input = root.querySelector('input[type=search]');
  input.addEventListener('input', () => {
    root.querySelector('input[name=user_id]').value = '';
    root.querySelector('.picker-selected').textContent = '';
    clearTimeout(pickerTimers[kind]);
    pickerTimers[kind] = setTimeout(() => findPickerMembers(kind, input.value.trim()).catch(error => notice(error.message, true)), 220);
  });
  input.addEventListener('focus', () => findPickerMembers(kind, input.value.trim()).catch(error => notice(error.message, true)));
  input.addEventListener('keydown', event => {
    if (event.key === 'Escape') root.querySelector('.picker-results').replaceChildren();
  });
}

const originalGuildChange = $('#guild-select').onchange;
$('#guild-select').onchange = () => {
  for (const kind of ['gift', 'appointment', 'dm']) resetPicker(kind);
  originalGuildChange();
};

function stopQrCamera() {
  qrScanning = false;
  if (qrStream) for (const track of qrStream.getTracks()) track.stop();
  qrStream = null;
  $('#qr-video').srcObject = null;
}

function closeQr() {
  stopQrCamera();
  qrChallenge = null;
  qrSubmitting = false;
  $('#qr-image').value = '';
  $('#qr-dialog').classList.add('hidden');
}

function scanQrFrame() {
  if (!qrScanning || qrSubmitting) return;
  const video = $('#qr-video');
  if (video.readyState >= 2 && video.videoWidth > 0) {
    const canvas = $('#qr-canvas');
    const scale = Math.min(1, 800 / video.videoWidth);
    canvas.width = Math.round(video.videoWidth * scale);
    canvas.height = Math.round(video.videoHeight * scale);
    const context = canvas.getContext('2d', {willReadFrequently: true});
    context.drawImage(video, 0, 0, canvas.width, canvas.height);
    const pixels = context.getImageData(0, 0, canvas.width, canvas.height);
    const found = window.jsQR?.(pixels.data, pixels.width, pixels.height);
    if (found?.data) { confirmQr(found.data); return; }
  }
  setTimeout(scanQrFrame, 160);
}

async function startQrCamera() {
  if (!navigator.mediaDevices?.getUserMedia) {
    $('#qr-feedback').textContent = 'Caméra indisponible. Importe une image du QR ci-dessous.';
    return;
  }
  try {
    qrStream = await navigator.mediaDevices.getUserMedia({video: {facingMode: 'environment'}, audio: false});
    if (!qrChallenge) { stopQrCamera(); return; }
    const video = $('#qr-video');
    video.srcObject = qrStream;
    await video.play();
    qrScanning = true;
    $('#qr-feedback').textContent = 'Place le QR reçu sur Discord devant la caméra.';
    scanQrFrame();
  } catch {
    $('#qr-feedback').textContent = 'Accès caméra refusé. Importe une image du QR ci-dessous.';
  }
}

async function confirmQr(qrText) {
  if (!qrChallenge || qrSubmitting) return;
  qrSubmitting = true;
  stopQrCamera();
  $('#qr-feedback').textContent = 'Vérification et envoi du cadeau…';
  try {
    const result = await api(`/api/guild/${state.guild}/gift/confirm`, {method: 'POST', body: JSON.stringify({challenge_id: qrChallenge, qr_text: qrText})});
    closeQr();
    $('#gift-form').reset();
    resetPicker('gift');
    notice(`${result.message} ${result.code}`, !result.delivered);
    haptic(result.delivered ? [30, 40, 30] : [35, 35, 35]);
    await loadGifts();
  } catch (error) {
    $('#qr-feedback').textContent = error.message;
    qrSubmitting = false;
    haptic([35, 35, 35]);
    if (qrChallenge) startQrCamera();
  }
}

$('#gift-form').onsubmit = async event => {
  event.preventDefault();
  const form = event.target;
  const memberId = form.elements.namedItem('user_id').value;
  if (!memberId) { notice('Choisis un membre dans les résultats de recherche.', true); return; }
  const button = form.querySelector('button[type=submit]');
  button.disabled = true;
  try {
    const result = await api(`/api/guild/${state.guild}/gift/challenge`, {method: 'POST', body: JSON.stringify({user_id: memberId, reason: form.elements.namedItem('reason').value})});
    qrChallenge = result.challenge_id;
    $('#qr-dialog').classList.remove('hidden');
    $('#qr-feedback').textContent = 'Ouverture de la caméra…';
    haptic([20, 40, 20]);
    startQrCamera();
  } catch (error) { notice(error.message, true); haptic([35, 35, 35]); }
  finally { button.disabled = false; }
};

$('#qr-cancel').onclick = closeQr;
$('#qr-image').onchange = async event => {
  const file = event.target.files?.[0];
  if (!file) return;
  try {
    const image = await createImageBitmap(file);
    const canvas = $('#qr-canvas');
    const scale = Math.min(1, 1200 / image.width);
    canvas.width = Math.round(image.width * scale);
    canvas.height = Math.round(image.height * scale);
    const context = canvas.getContext('2d', {willReadFrequently: true});
    context.drawImage(image, 0, 0, canvas.width, canvas.height);
    image.close?.();
    const pixels = context.getImageData(0, 0, canvas.width, canvas.height);
    const found = window.jsQR?.(pixels.data, pixels.width, pixels.height);
    if (!found?.data) throw new Error('Aucun QR lisible dans cette image.');
    await confirmQr(found.data);
  } catch (error) { $('#qr-feedback').textContent = error.message; haptic([35, 35, 35]); }
};

async function loadPresence() {
  const data = await api(`/api/guild/${state.guild}/presence`);
  $('#presence-note').textContent = data.mode === 'presence'
    ? 'Classement de la dernière présence Discord observée depuis que le suivi est activé.'
    : 'Classement de la dernière activité (message ou vocal). Active Presence Intent dans le portail Discord pour suivre les connexions réelles.';
  const host = $('#presence-list');
  host.replaceChildren();
  data.members.forEach((member, index) => {
    const row = el('div', 'presence-row');
    row.append(el('span', 'rank', `${index + 1}.`), Object.assign(el('img', 'avatar'), {src: member.avatar, alt: ''}));
    const main = el('div', 'row-main');
    main.append(el('strong', '', member.name), el('small', '', member.last_seen_at ? new Date(member.last_seen_at).toLocaleString('fr-FR') : 'Aucune donnée observée'));
    const label = member.online_now ? 'En ligne maintenant' : member.days_ago === 0 ? "Aujourd'hui" : member.days_ago === 1 ? 'Hier' : member.days_ago == null ? 'Inconnu' : `Il y a ${member.days_ago} jours`;
    row.append(main, el('span', `presence-age ${member.days_ago > 1 ? 'old' : ''}`, label));
    host.append(row);
  });
  if (!data.members.length) empty(host, 'Aucun membre à classer.');
}

async function loadAppointments() {
  const data = await api(`/api/guild/${state.guild}/appointments`);
  const host = $('#appointment-list');
  host.replaceChildren();
  const labels = {pending:'En attente', accepted:'Accepté', declined:'Refusé', expired:'Expiré', dm_failed:'MP échoué'};
  for (const item of data.items) {
    const row = el('div', 'gift-row');
    const main = el('div', 'row-main');
    main.append(el('strong', '', item.target_name || `Membre ${item.target_id}`), el('small', '', new Date(item.scheduled_at).toLocaleString('fr-FR', {dateStyle:'full', timeStyle:'short'})));
    row.append(el('span', 'audit-icon', '▣'), main, el('span', `pill ${item.status === 'dm_failed' || item.status === 'declined' ? 'fail' : ''}`, labels[item.status] || item.status));
    host.append(row);
  }
  if (!data.items.length) empty(host, 'Aucun rendez-vous programmé.');
}

$('#appointment-form').onsubmit = async event => {
  event.preventDefault();
  const form = event.target;
  const memberId = form.elements.namedItem('user_id').value;
  if (!memberId) { notice('Choisis un membre dans les résultats de recherche.', true); return; }
  const when = new Date(form.elements.namedItem('scheduled_at').value);
  if (Number.isNaN(when.getTime())) { notice('Choisis une date et une heure valides.', true); return; }
  const button = form.querySelector('button[type=submit]');
  button.disabled = true;
  try {
    const result = await api(`/api/guild/${state.guild}/appointments`, {method:'POST', body:JSON.stringify({user_id:memberId, scheduled_at:when.toISOString()})});
    notice(result.message);
    haptic([20, 30, 20]);
    form.reset(); resetPicker('appointment'); await loadAppointments();
  } catch (error) { notice(error.message, true); haptic([35, 35, 35]); }
  finally { button.disabled = false; }
};

$('#dm-form').onsubmit = async event => {
  event.preventDefault();
  const form = event.target;
  const memberId = form.elements.namedItem('user_id').value;
  if (!memberId) { notice('Choisis un membre dans les résultats de recherche.', true); return; }
  if (!window.confirm('Envoyer ce message privé avec René ?')) return;
  const button = form.querySelector('button[type=submit]');
  button.disabled = true;
  try {
    const result = await api(`/api/guild/${state.guild}/dm`, {method:'POST', body:JSON.stringify({user_id:memberId, message:form.elements.namedItem('message').value})});
    notice(result.message);
    haptic([20, 30, 20]);
    form.reset(); resetPicker('dm');
  } catch (error) { notice(error.message, true); haptic([35, 35, 35]); }
  finally { button.disabled = false; }
};

async function loadSettings() {
  const data = await api('/api/system/presence');
  $('#bot-status').value = data.status || 'auto';
  $('#bot-activity').value = data.text || '';
}

$('#presence-form').onsubmit = async event => {
  event.preventDefault();
  const form = event.target;
  const button = form.querySelector('button[type=submit]');
  button.disabled = true;
  try {
    const result = await api('/api/system/presence', {method:'POST', body:JSON.stringify({status:form.elements.namedItem('status').value, text:form.elements.namedItem('text').value})});
    notice(result.message); haptic([20, 30, 20]);
  } catch (error) { notice(error.message, true); haptic([35, 35, 35]); }
  finally { button.disabled = false; }
};

$('#restart-bot').onclick = async () => {
  if (!window.confirm('Redémarrer le service Render maintenant ? René sera momentanément hors ligne.')) return;
  const button = $('#restart-bot');
  button.disabled = true;
  try {
    const result = await api('/api/system/restart', {method:'POST', body:'{}'});
    notice(result.message); haptic([30, 40, 30]);
  } catch (error) { notice(error.message, true); button.disabled = false; }
};

try { $('#haptic-toggle').checked = localStorage.getItem('rene_haptics') !== 'off'; } catch {}
$('#haptic-toggle').onchange = event => {
  try { localStorage.setItem('rene_haptics', event.target.checked ? 'on' : 'off'); } catch {}
  if (event.target.checked) haptic([15, 30, 15]);
};
document.addEventListener('click', event => {
  if (event.target.closest('button') && !event.target.closest('#haptic-toggle')) haptic(8);
});
