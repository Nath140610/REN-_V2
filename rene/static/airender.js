/* René IA : les réponses de NathGPT arrivent en blocs (titre, encarts, chiffres, listes) et sont mises en page. */
function aiBlocks(blocks) {
  const box = el('div', 'ai-rich');
  let stats = null;
  for (const block of blocks) {
    if (block.type !== 'stat') stats = null;
    if (block.type === 'title') box.append(el('h4', 'ai-title', block.text));
    else if (block.type === 'text') box.append(el('p', 'ai-text', block.text));
    else if (block.type === 'box') {
      const card = el('div', 'ai-box');
      if (block.label) card.append(el('small', '', block.label));
      card.append(el('strong', '', block.text));
      box.append(card);
    } else if (block.type === 'stat') {
      if (!stats) { stats = el('div', 'ai-stats'); box.append(stats); }
      const tile = el('div', 'ai-stat');
      tile.append(el('strong', '', block.text), el('small', '', block.label || ''));
      stats.append(tile);
    } else if (block.type === 'list' || block.type === 'steps') {
      const list = el(block.type === 'steps' ? 'ol' : 'ul', 'ai-list');
      for (const item of block.items) list.append(el('li', '', item));
      box.append(list);
    } else if (block.type === 'tip') box.append(el('p', 'ai-callout tip', block.text));
    else if (block.type === 'warning') box.append(el('p', 'ai-callout warning', block.text));
    else if (block.type === 'question') box.append(el('p', 'ai-question', block.text));
  }
  return box;
}

$('#ai-form').onsubmit = async event => {
  event.preventDefault();
  const question = $('#ai-question').value.trim();
  if (!question) return;
  $('#ai-send').disabled = true;
  bubble(question, 'user');
  $('#ai-question').value = '';
  const pending = bubble('René réfléchit à partir des statistiques…', 'rene thinking');
  try {
    const started = await api(`/api/guild/${state.guild}/ai`, {method: 'POST', body: JSON.stringify({question})});
    let result;
    for (let i = 0; i < 125; i++) {
      await new Promise(resolve => setTimeout(resolve, 5000));
      result = await api(`/api/ai/${started.job_id}`);
      if (result.status !== 'thinking') break;
    }
    pending.classList.remove('thinking');
    if (result?.status === 'done' && result.blocks?.length) {
      pending.classList.add('rich');
      pending.replaceChildren(aiBlocks(result.blocks));
    } else {
      pending.textContent = result?.status === 'done' ? result.answer : result?.error || 'La réponse prend trop de temps. Réessaie.';
    }
    $('#ai-chat').scrollTop = $('#ai-chat').scrollHeight;
  } catch (error) {
    pending.classList.remove('thinking');
    pending.textContent = error.message;
  } finally {
    $('#ai-send').disabled = false;
  }
};
