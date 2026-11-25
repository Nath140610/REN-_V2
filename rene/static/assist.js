/* Panel Assistance de René : vérifier ou activer un code cadeau. */
(() => {
  'use strict';
  const $ = selector => document.querySelector(selector);
  const s = {csrf: '', guild: '', history: [], reward: null};
  const el = (tag, className = '', text = '') => { const n = document.createElement(tag); n.className = className; n.textContent = text; return n; };

  async function api(path, options = {}) {
    const headers = {...(options.headers || {})};
    if (options.body) { headers['Content-Type'] = 'application/json'; headers['X-CSRF-Token'] = s.csrf; }
    const response = await fetch(path, {credentials: 'same-origin', ...options, headers});
    let data;
    try { data = await response.json(); } catch { data = {error: 'Réponse inattendue du serveur.'}; }
    if (!response.ok) { const error = new Error(data.error || 'Une erreur est survenue.'); error.status = response.status; throw error; }
    return data;
  }

  function show(id) {
    for (const name of ['assist-boot', 'assist-login', 'assist-app']) $(`#${name}`).classList.toggle('hidden', name !== id);
  }

  function notice(text, bad = false) {
    const box = $('#notice');
    box.textContent = text;
    box.classList.toggle('bad', bad);
    box.classList.remove('hidden');
    clearTimeout(notice.timer);
    notice.timer = setTimeout(() => box.classList.add('hidden'), 6000);
  }

  function localNow() {
    const now = new Date();
    now.setMinutes(now.getMinutes() - now.getTimezoneOffset());
    return now.toISOString().slice(0, 16);
  }

  /* ---------- Session ---------- */

  async function start() {
    try {
      const session = await api('/api/assist/session');
      if (!session.configured) {
        show('assist-login');
        $('#assist-login-text').textContent = 'L’assistance n’est pas encore ouverte. Demande le lien au staff.';
        $('#assist-login-form').classList.add('hidden');
        return;
      }
      if (!session.authenticated) { show('assist-login'); return; }
      s.csrf = session.csrf;
      await openApp();
    } catch (error) {
      $('#assist-boot-text').textContent = error.message;
      setTimeout(start, 5000);
    }
  }

  async function openApp() {
    show('assist-app');
    try {
      const guilds = await api('/api/assist/guilds');
      const select = $('#assist-guild');
      select.replaceChildren(...guilds.map(g => Object.assign(el('option', '', g.name), {value: g.id})));
      select.classList.toggle('hidden', guilds.length < 2);
      s.guild = guilds[0]?.id || '';
      if (!s.guild) notice('René ne voit aucun serveur pour le moment.', true);
    } catch (error) { notice(error.message, true); }
    try {
      const catalog = await api('/api/assist/rewards');
      s.reward = window.ReneRewards.mount($('#assist-reward'), catalog.games);
    } catch (error) { notice(error.message, true); }
    resetForm();
  }

  $('#assist-login-form').onsubmit = async event => {
    event.preventDefault();
    $('#assist-login-error').textContent = '';
    try {
      const result = await api('/api/assist/login', {method: 'POST', body: JSON.stringify({password: $('#assist-password').value})});
      s.csrf = result.csrf;
      $('#assist-password').value = '';
      await openApp();
    } catch (error) { $('#assist-login-error').textContent = error.message; }
  };

  $('#assist-logout').onclick = async () => {
    try { await api('/api/assist/logout', {method: 'POST', body: '{}'}); } catch {}
    s.csrf = '';
    show('assist-login');
  };

  $('#assist-guild').onchange = event => { s.guild = event.target.value; clearMember(); };

  /* ---------- Choix du membre ---------- */

  let searchTimer;
  function clearMember() {
    $('#assist-member-id').value = '';
    $('#assist-selected').textContent = '';
    $('#assist-results').replaceChildren();
  }

  function pick(member) {
    $('#assist-member').value = member.name;
    $('#assist-member-id').value = member.id;
    $('#assist-selected').textContent = `✓ ${member.name} · @${member.username}`;
    $('#assist-results').replaceChildren();
    $('#assist-code').focus();
  }

  async function searchMembers(query) {
    if (!query) { $('#assist-results').replaceChildren(); return; }
    const data = await api(`/api/assist/members?guild=${encodeURIComponent(s.guild)}&q=${encodeURIComponent(query)}`);
    if ($('#assist-member').value.trim() !== query) return;
    const host = $('#assist-results');
    host.replaceChildren(...data.items.map(member => {
      const button = Object.assign(el('button', 'picker-option'), {type: 'button'});
      const label = el('span');
      label.append(el('strong', '', member.name), el('small', '', `@${member.username}`));
      button.append(Object.assign(el('img'), {src: member.avatar, alt: ''}), label);
      button.onclick = () => pick(member);
      return button;
    }));
    if (!data.items.length) host.append(el('div', 'empty', 'Aucun membre trouvé.'));
  }

  $('#assist-member').addEventListener('input', event => {
    clearMember();
    clearTimeout(searchTimer);
    const query = event.target.value.trim();
    searchTimer = setTimeout(() => searchMembers(query).catch(error => notice(error.message, true)), 220);
  });
  $('#assist-member').addEventListener('keydown', event => { if (event.key === 'Escape') $('#assist-results').replaceChildren(); });

  /* ---------- Code ---------- */

  $('#assist-code').addEventListener('input', event => {
    const raw = event.target.value.toUpperCase().replace(/[^A-Z0-9]/g, '').slice(0, 16);
    event.target.value = raw.match(/.{1,4}/g)?.join('-') || '';
  });

  function resetForm() {
    $('#assist-form').reset();
    clearMember();
    s.reward?.reset();
    $('#assist-date').value = '';
    $('#assist-date').max = localNow();
    $('#assist-form').classList.remove('hidden');
    $('#assist-result').classList.add('hidden');
  }

  function showResult(ok, title, text) {
    const box = $('#assist-result');
    box.className = `card assist-result ${ok ? 'ok' : 'no'}`;
    $('#assist-result-icon').textContent = ok ? '✓' : '✕';
    $('#assist-result-title').textContent = title;
    $('#assist-result-text').textContent = text;
    $('#assist-form').classList.add('hidden');
    try { navigator.vibrate?.(ok ? [20, 40, 30] : [40, 40, 40]); } catch {}
  }

  function renderHistory() {
    const host = $('#assist-history');
    host.replaceChildren(...s.history.map(item => {
      const row = el('div', 'list-row');
      row.append(el('span', 'audit-icon', item.ok ? '✓' : '✕'));
      const main = el('div', 'row-main');
      main.append(el('strong', 'gift-code', item.code), el('small', '', `${item.member} · ${item.reward} · ${item.time}`));
      row.append(main, el('span', `pill ${item.ok ? '' : 'fail'}`, item.ok ? 'Activé 24 h' : 'Refusé'));
      return row;
    }));
    if (!s.history.length) host.append(el('div', 'empty', 'Aucune demande pour l’instant.'));
  }

  $('#assist-form').onsubmit = async event => {
    event.preventDefault();
    const memberId = $('#assist-member-id').value;
    const code = $('#assist-code').value.trim();
    const reason = $('#assist-reason').value.trim();
    const date = $('#assist-date').value;
    const signature = $('#assist-signature').value.trim();
    if (!memberId) { notice('Choisis la personne dans la liste des membres.', true); $('#assist-member').focus(); return; }
    if (!/^VOID-[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}$/.test(code)) { notice('Le code doit ressembler à VOID-XXXX-XXXX-XXXX.', true); $('#assist-code').focus(); return; }
    const rewardError = s.reward ? s.reward.error() : 'Le choix du gain n’a pas chargé. Recharge la page.';
    if (rewardError) { notice(rewardError, true); return; }
    const reward = s.reward.value();
    if (reason.length < 5) { notice('Explique le problème.', true); $('#assist-reason').focus(); return; }
    if (!date) { notice('Indique la date et l’heure du problème.', true); $('#assist-date').focus(); return; }
    if (signature.length < 2) { notice('Signe la demande avec ton nom.', true); $('#assist-signature').focus(); return; }
    const member = $('#assist-member').value;
    const rewardText = $('#assist-reward .reward-summary').textContent;
    if (!window.confirm(`Vérifier ${code} pour ${member} ?\nGain : ${rewardText}\nS’il n’existe pas, il sera activé pendant 24 h.`)) return;
    const button = $('#assist-submit');
    button.disabled = true;
    try {
      const result = await api('/api/assist/requests', {method: 'POST', body: JSON.stringify({
        guild_id: s.guild, user_id: memberId, code, reason, signature, reward,
        incident_at: new Date(date).toISOString(),
      })});
      if (result.ok) {
        const until = new Date(result.expires_at).toLocaleString('fr-FR', {dateStyle: 'medium', timeStyle: 'short'});
        showResult(true, 'Code activé', `${result.message} Il reste valable jusqu’au ${until}.`);
      } else {
        showResult(false, 'Ce n’est pas possible', result.message);
      }
      s.history.unshift({ok: !!result.ok, code, member, reward: rewardText,
                         time: new Date().toLocaleTimeString('fr-FR', {hour: '2-digit', minute: '2-digit'})});
      renderHistory();
    } catch (error) {
      if (error.status === 401) { show('assist-login'); return; }
      notice(error.message, true);
    } finally { button.disabled = false; }
  };

  $('#assist-again').onclick = resetForm;
  renderHistory();
  start();
})();
