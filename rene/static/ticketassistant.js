/* Réglages : accueil automatique des tickets et connexion à NathGPT. */
const tka = {options: {roles: [], members: []}, targets: []};

function tkaTargetRow(target = {kind: 'role', id: '', label: '', description: ''}) {
  const row = el('div', 'tka-row');
  const select = el('select');
  select.setAttribute('aria-label', 'Personne ou rôle');
  const groups = [['Rôles', 'role', tka.options.roles], ['Staff', 'user', tka.options.members]];
  for (const [label, kind, items] of groups) {
    const group = document.createElement('optgroup');
    group.label = label;
    for (const item of items) {
      const option = el('option', '', kind === 'role' ? `@${item.name}` : item.name);
      option.value = `${kind}:${item.id}`;
      group.append(option);
    }
    select.append(group);
  }
  if (target.id) {
    const value = `${target.kind}:${target.id}`;
    if (![...select.options].some(o => o.value === value)) {
      const option = el('option', '', target.label || target.id);
      option.value = value;
      select.prepend(option);
    }
    select.value = value;
  }
  const label = Object.assign(el('input'), {value: target.label || '', maxLength: 80, placeholder: 'Nom du bouton'});
  label.setAttribute('aria-label', 'Nom du bouton');
  const description = Object.assign(el('input'), {value: target.description || '', maxLength: 100, placeholder: 'Pour quoi ? (facultatif)'});
  description.setAttribute('aria-label', 'Description');
  const remove = Object.assign(el('button', 'mini danger-text', 'Retirer'), {type: 'button'});
  remove.onclick = () => { row.remove(); haptic?.(15); };
  select.onchange = () => {
    if (!label.value) label.value = select.selectedOptions[0]?.textContent.replace(/^@/, '') || '';
  };
  row.append(select, label, description, remove);
  return row;
}

async function loadTicketAssistant() {
  const data = await api(`/api/guild/${state.guild}/ticket-assistant`);
  tka.options = data.options;
  $('#tka-enabled').checked = data.enabled;
  $('#tka-ai').checked = data.ai;
  $('#tka-question').value = data.question;
  $('#tka-targets').replaceChildren(...data.targets.map(tkaTargetRow));
  $('#tka-note').textContent = data.custom ? '' : 'Choix par défaut : le rôle modérateur (ou le fondateur). Modifie-les puis enregistre.';
  $('#tka-ai-note').textContent = data.ai_ready ? '' : 'NathGPT n’est pas configuré : René enverra un message d’accueil simple.';
}

$('#tka-add').onclick = () => {
  if ($('#tka-targets').children.length >= 10) return notice('10 choix maximum.', true);
  $('#tka-targets').append(tkaTargetRow());
};

$('#tka-form').onsubmit = async event => {
  event.preventDefault();
  const targets = [...$('#tka-targets').querySelectorAll('.tka-row')].map(row => {
    const [kind, id] = row.querySelector('select').value.split(':');
    const [label, description] = row.querySelectorAll('input');
    return {kind, id, label: label.value.trim(), description: description.value.trim()};
  }).filter(t => t.id);
  const result = await withButton(event.submitter || $('#tka-form button[type=submit]'), () =>
    post(`/api/guild/${state.guild}/ticket-assistant`, {enabled: $('#tka-enabled').checked, ai: $('#tka-ai').checked,
      question: $('#tka-question').value.trim(), targets}));
  if (result) loadTicketAssistant().catch(() => {});
};

/* ---------- NathGPT ---------- */

async function loadNathGPT() {
  const data = await api('/api/system/nathgpt');
  $('#nathgpt-url').value = data.url_from_panel ? data.url : '';
  $('#nathgpt-url').placeholder = data.env_url || 'https://xxxx.trycloudflare.com';
  $('#nathgpt-state').textContent = !data.token ? 'Token absent : ajoute NATHGPT_API_TOKEN dans Render.'
    : !data.url ? 'Adresse absente : colle l’adresse de ton serveur NathGPT.'
    : `Utilise ${data.url}${data.url_from_panel ? ' (panel)' : ' (Render)'}`;
}

$('#nathgpt-form').onsubmit = async event => {
  event.preventDefault();
  const result = await withButton(event.submitter || $('#nathgpt-form button[type=submit]'),
    () => post('/api/system/nathgpt', {url: $('#nathgpt-url').value.trim()}));
  if (result) loadNathGPT().catch(() => {});
};

$('#nathgpt-test').onclick = async () => {
  $('#nathgpt-state').textContent = 'Test en cours… (jusqu’à quelques minutes)';
  const result = await withButton($('#nathgpt-test'), () => post('/api/system/nathgpt/test'));
  $('#nathgpt-state').textContent = result ? `✓ ${result.message}` : 'Échec du test : regarde le message affiché.';
};

const loadSettingsWithoutTickets = loadSettings;
loadSettings = async () => {
  await Promise.all([loadSettingsWithoutTickets(), loadTicketAssistant().catch(error => notice(error.message, true)),
    loadNathGPT().catch(error => notice(error.message, true))]);
};
