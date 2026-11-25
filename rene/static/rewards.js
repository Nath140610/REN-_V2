/* Sélecteur de gain partagé : jeu → gain → quantités. Utilisé par le panel et l'assistance. */
(function (root) {
  'use strict';
  const NAMES = {glings: 'Glings', gifts: 'Cadeaux'};
  const node = (tag, className = '', text = '') => {
    const element = document.createElement(tag);
    element.className = className;
    element.textContent = text;
    return element;
  };
  const format = n => new Intl.NumberFormat('fr-FR').format(n);

  function mount(host, games, onChange = () => {}) {
    const state = {game: null, type: null, amounts: {}};
    host.replaceChildren();
    host.classList.add('reward-picker');

    const gameRow = node('div', 'segmented reward-games');
    const options = node('div', 'group reward-options hidden');
    const amounts = node('div', 'reward-amounts hidden');
    const summary = node('p', 'reward-summary');
    host.append(node('span', 'reward-step', 'Jeu'), gameRow, options, amounts, summary);

    const gameButtons = games.map(game => {
      const button = Object.assign(node('button', '', game.name), {type: 'button'});
      button.onclick = () => { selectGame(game.id); };
      gameRow.append(button);
      return [game.id, button];
    });

    function current() {
      return games.find(game => game.id === state.game);
    }

    function definition() {
      return current()?.rewards.find(reward => reward.id === state.type);
    }

    function selectGame(id, keepType = false) {
      state.game = id;
      if (!keepType) state.type = null;
      for (const [gameId, button] of gameButtons) button.classList.toggle('active', gameId === id);
      options.replaceChildren(...current().rewards.map(reward => {
        const row = Object.assign(node('button', 'group-row reward-option'), {type: 'button'});
        row.append(node('span', 'reward-label', reward.gamepass ? `${reward.label} · gamepass` : reward.label), node('i', 'reward-check', '✓'));
        row.onclick = () => selectType(reward.id);
        row.dataset.reward = reward.id;
        return row;
      }));
      options.classList.remove('hidden');
      renderAmounts();
      update();
    }

    function selectType(id) {
      state.type = id;
      for (const row of options.children) row.classList.toggle('active', row.dataset.reward === id);
      renderAmounts();
      update();
    }

    function renderAmounts() {
      const fields = definition()?.amounts || [];
      amounts.replaceChildren(...fields.map(key => {
        const label = node('label', 'reward-amount');
        const input = Object.assign(node('input'), {type: 'number', min: 1, max: 1000000, step: 1, inputMode: 'numeric',
                                                     placeholder: 'Quantité', value: state.amounts[key] || ''});
        input.oninput = () => { state.amounts[key] = input.value; update(); };
        label.append(node('span', '', NAMES[key] || key), input);
        return label;
      }));
      amounts.classList.toggle('hidden', !fields.length);
    }

    function value() {
      const reward = definition();
      if (!state.game || !reward) return null;
      const result = {game: state.game, type: state.type};
      for (const key of reward.amounts) {
        const amount = Number(state.amounts[key]);
        if (!Number.isInteger(amount) || amount < 1 || amount > 1000000) return null;
        result[key] = amount;
      }
      return result;
    }

    function label() {
      const game = current(), reward = definition();
      if (!game) return '';
      if (!reward) return `${game.name} · choisis le gain`;
      if (!reward.amounts.length) return `${game.name} · ${reward.label}`;
      const parts = reward.amounts.map(key => {
        const amount = Number(state.amounts[key]);
        return amount > 0 ? `${format(amount)} ${NAMES[key].toLowerCase()}` : `? ${NAMES[key].toLowerCase()}`;
      });
      return `${game.name} · ${parts.join(' et ')}`;
    }

    function update() {
      summary.textContent = label();
      summary.classList.toggle('ready', !!value());
      onChange(value());
    }

    function error() {
      if (!state.game) return 'Choisis le jeu du cadeau.';
      const reward = definition();
      if (!reward) return `Choisis le gain dans ${current().name}.`;
      for (const key of reward.amounts) {
        const amount = Number(state.amounts[key]);
        if (!Number.isInteger(amount) || amount < 1 || amount > 1000000) return `Indique le nombre de ${NAMES[key].toLowerCase()} (1 à 1 000 000).`;
      }
      return '';
    }

    function reset() {
      state.game = null; state.type = null; state.amounts = {};
      for (const [, button] of gameButtons) button.classList.remove('active');
      options.classList.add('hidden');
      amounts.classList.add('hidden');
      summary.textContent = '';
      onChange(null);
    }

    function set(reward) {
      reset();
      if (!reward || !games.some(game => game.id === reward.game)) return;
      state.amounts = {glings: reward.glings || '', gifts: reward.gifts || ''};
      selectGame(reward.game);
      if (current().rewards.some(item => item.id === reward.type)) selectType(reward.type);
    }

    return {value, error, reset, set};
  }

  root.ReneRewards = {mount};
})(window);
