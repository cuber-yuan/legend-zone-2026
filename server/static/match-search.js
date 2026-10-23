(() => {
  const form = document.getElementById('match-filters');
  if (!form) return;
  const field = id => document.getElementById(id);
  const game = field('filter-game'), mode = field('filter-bot-mode');
  const state = field('filter-status'), rating = field('filter-rating');
  const from = field('filter-from'), through = field('filter-to');
  const summary = field('match-summary'), feedback = field('match-feedback');
  const previous = field('match-previous'), next = field('match-next'), refresh = field('match-refresh');
  let selectedBots = [], selectedAuthor = null, applied = new URLSearchParams(location.search);
  let dirty = false, loading = false, data = null, controller = null, restoreToken = 0;

  async function request(url, signal) {
    const response = await platformFetch(url, {cache: 'no-store', signal});
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(typeof body.detail === 'string' ? I18n.t(body.detail) : I18n.t("Invalid filters or the service is unavailable. Please check your filters and retry."));
    return body;
  }
  function controls() {
    previous.disabled = loading || dirty || !data || data.page <= 1;
    next.disabled = loading || dirty || !data || data.page >= data.pages;
    refresh.disabled = loading;
  }
  function changed() {
    restoreToken++;
    dirty = true;
    field('match-head-to-head').hidden = true;
    summary.textContent = I18n.t("Filters changed. Apply Filters to update the results.");
    controls();
  }
  function updateUrl(push = false) {
    const query = applied.toString(), url = I18n.url('/matches') + (query ? '?' + query : '');
    if (location.pathname + location.search !== url) history[push ? 'pushState' : 'replaceState']({}, '', url);
  }
  function botLabel(bot) {
    return `${bot.bot_name || bot.id}${bot.game ? ' · ' + I18n.t(bot.game) : ''}${bot.owner ? I18n.t(' · by {0}', bot.owner) : ''}`;
  }
  function chip(container, label, remove) {
    const wrapper = document.createElement('span'), text = document.createElement('span'), button = document.createElement('button');
    wrapper.className = 'matches-chip'; text.textContent = label;
    button.type = 'button'; button.textContent = '×'; button.setAttribute('aria-label', I18n.t('Remove {0}', label));
    button.addEventListener('click', remove); wrapper.append(text, button); container.append(wrapper);
  }
  function renderSelected() {
    field('bot-selected').replaceChildren(); field('author-selected').replaceChildren();
    for (const bot of selectedBots) chip(field('bot-selected'), botLabel(bot), () => {
      selectedBots = selectedBots.filter(item => item.id !== bot.id); renderSelected(); changed();
    });
    if (selectedAuthor) chip(field('author-selected'), selectedAuthor.username, () => {
      selectedAuthor = null; renderSelected(); changed();
    });
  }
  function picker(inputId, outputId, endpoint, select, label) {
    const input = field(inputId), output = field(outputId);
    let timer, active;
    function message(text) { output.replaceChildren(); const p = document.createElement('p'); p.textContent = text; output.append(p); output.hidden = false; }
    input.addEventListener('keydown', event => {
      if (event.key === 'Enter') { event.preventDefault(); output.querySelector('button')?.focus(); }
      if (event.key === 'Escape') output.hidden = true;
    });
    input.addEventListener('input', () => {
      clearTimeout(timer); active?.abort();
      const q = input.value.trim();
      if (!q) { output.hidden = true; return; }
      timer = setTimeout(async () => {
        active = new AbortController(); const signal = active.signal;
        message(I18n.t("Searching…"));
        try {
          const query = new URLSearchParams({q});
          if (endpoint === 'bots' && game.value) query.set('game', game.value);
          const results = await request(`/api/match-search/${endpoint}?${query}`, signal);
          const options = endpoint === 'bots' ? results.filter(bot => !bot.deleted) : results;
          if (signal.aborted) return;
          output.replaceChildren();
          for (const option of options) {
            const button = document.createElement('button'); button.type = 'button'; button.textContent = label(option);
            button.addEventListener('click', () => {
              select(option); renderSelected(); changed(); output.hidden = true; input.value = ''; input.focus();
            }); output.append(button);
          }
          if (!options.length) message(I18n.t("No results found."));
        } catch (error) { if (error.name !== 'AbortError') message(error.message); }
      }, 250);
    });
    return () => { clearTimeout(timer); active?.abort(); input.value = ''; output.replaceChildren(); output.hidden = true; };
  }
  const clearBotPicker = picker('filter-bot-search', 'bot-options', 'bots', bot => {
    if (selectedBots.some(item => item.id === bot.id)) return;
    if (selectedBots.length >= 20) { feedback.textContent = I18n.t("Select up to 20 Bots."); feedback.hidden = false; return; }
    selectedBots.push(bot);
  }, botLabel);
  const clearAuthorPicker = picker('filter-author-search', 'author-options', 'authors', author => { selectedAuthor = author; }, author => author.username);
  form.addEventListener('change', event => {
    if (event.target === game) clearBotPicker();
    if (event.target.matches("select,input[type=\"datetime-local\"]")) changed();
  });
  form.addEventListener('input', event => { if (event.target.type === 'datetime-local') changed(); });

  function localTime(value) {
    if (!value) return '';
    const date = new Date(value);
    if (!Number.isFinite(date.getTime())) throw new Error(I18n.t("The URL contains an invalid date filter. Clear Filters to reset it."));
    const pad = number => String(number).padStart(2, '0');
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
  }
  async function restore() {
    const token = ++restoreToken;
    controller?.abort(); clearBotPicker(); clearAuthorPicker();
    field('match-head-to-head').hidden = true;
    applied = new URLSearchParams(location.search);
    if (!mode) applied.delete('bot_mode');
    dirty = false; data = null;
    selectedBots = applied.getAll('bot').map(id => ({id}));
    selectedAuthor = applied.has('author') ? {id: applied.get('author'), username: I18n.t('User #{0}', applied.get('author'))} : null;
    form.reset(); feedback.hidden = true;
    try {
      const requestedGame = applied.get('game') || '';
      const option = Array.from(game.options).find(option => option.value === requestedGame || option.textContent === requestedGame);
      if (requestedGame && !option) game.add(new Option(requestedGame, requestedGame));
      game.value = option ? option.value : requestedGame;
      if (mode) mode.value = applied.get('bot_mode') || 'all';
      state.value = applied.get('status') || 'all'; rating.value = applied.get('rating') || 'all';
      from.value = localTime(applied.get('created_from')); through.value = localTime(applied.get('created_to'));
      renderSelected(); controls();
      const [bots, authors] = await Promise.all([
        selectedBots.length ? request('/api/match-search/bots?' + new URLSearchParams(selectedBots.map(bot => ['id', bot.id]))) : [],
        selectedAuthor ? request('/api/match-search/authors?' + new URLSearchParams({id: selectedAuthor.id})) : [],
      ]);
      if (token !== restoreToken) return;
      selectedBots = selectedBots.map(bot => bots.find(item => item.id === bot.id) || bot);
      if (selectedAuthor && authors.length) selectedAuthor = authors[0];
      renderSelected(); await load();
    } catch (error) {
      if (token !== restoreToken) return;
      dirty = true; loading = false; feedback.textContent = I18n.t(error.message); feedback.hidden = false; controls();
    }
  }
  async function load() {
    controller?.abort(); const current = controller = new AbortController();
    loading = true; controls(); field('match-results').setAttribute('aria-busy', 'true');
    feedback.hidden = true;
    field('match-head-to-head').hidden = true;
    try {
      const result = await request('/api/match-search?' + applied, current.signal);
      if (current.signal.aborted) return;
      data = result;
      renderHeadToHead(result.head_to_head);
      if (result.page === 1) applied.delete('page'); else applied.set('page', result.page);
      updateUrl();
      MatchTable.render(field('search-matches-tbody'), result.matches, I18n.t("No matches found for these filters."), {showStatus: true});
      summary.textContent = dirty ? I18n.t("Filters changed. Apply Filters to update the results.") : I18n.t("{0} matching match{1} · newest first{2}", result.total, result.total === 1 ? '' : 'es', result.page === 1 ? I18n.t(' · refreshes every 5 seconds') : '');
      field('match-page').textContent = I18n.t("Page {0} of {1}", result.page, result.pages);
    } catch (error) {
      if (error.name !== 'AbortError') { feedback.textContent = I18n.t(error.message); feedback.hidden = false; }
    } finally {
      if (controller === current) { loading = false; controls(); field('match-results').setAttribute('aria-busy', 'false'); }
    }
  }
  function renderHeadToHead(stats) {
    const panel = field('match-head-to-head');
    panel.hidden = dirty || !stats;
    if (panel.hidden) return;
    const colors = ['#2563eb', '#f59e0b', '#94a3b8'];
    const entries = stats.bots.map(bot => ({
      label: selectedBots.find(item => item.id === bot.id)?.bot_name || bot.id,
      count: bot.wins,
    }));
    entries.push({label: I18n.t('Draws'), count: stats.draws});
    const legend = field('head-to-head-legend'), chart = field('head-to-head-chart');
    legend.replaceChildren();
    let angle = 0;
    const segments = [], descriptions = [];
    entries.forEach((entry, index) => {
      const percent = stats.total ? entry.count / stats.total * 100 : 0;
      const description = I18n.t('{0}% · {1} matches', percent.toFixed(1), entry.count);
      const row = document.createElement('li'), swatch = document.createElement('span');
      const label = document.createElement('span'), value = document.createElement('span');
      swatch.className = 'matches-stats-swatch'; swatch.style.background = colors[index]; swatch.setAttribute('aria-hidden', 'true');
      label.className = 'matches-stats-label'; label.textContent = entry.label;
      value.className = 'matches-stats-value'; value.textContent = description;
      label.append(value); row.append(swatch, label); legend.append(row);
      segments.push(`${colors[index]} ${angle}% ${angle + percent}%`); angle += percent;
      descriptions.push(entry.label + ': ' + description);
    });
    chart.style.background = stats.total ? `conic-gradient(${segments.join(',')})` : '#e2e8f0';
    chart.setAttribute('aria-label', descriptions.join('; '));
    field('head-to-head-total').textContent = stats.total ? I18n.t('{0} completed matches', stats.total) : I18n.t('No completed matches.');
  }
  form.addEventListener('submit', event => {
    event.preventDefault();
    if (!form.reportValidity()) return;
    restoreToken++;
    const params = new URLSearchParams();
    if (game.value) params.set('game', game.value);
    for (const bot of selectedBots) params.append('bot', bot.id);
    if (mode && mode.value !== 'all') params.set('bot_mode', mode.value);
    if (selectedAuthor) params.set('author', selectedAuthor.id);
    if (state.value !== 'all') params.set('status', state.value);
    if (rating.value !== 'all') params.set('rating', rating.value);
    for (const [input, name] of [[from, 'created_from'], [through, 'created_to']]) {
      if (input.value) params.set(name, new Date(input.value).toISOString());
    }
    if (from.value && through.value && new Date(from.value) > new Date(through.value)) {
      feedback.textContent = I18n.t("The start time must not be after the end time."); feedback.hidden = false; return;
    }
    applied = params; dirty = false; updateUrl(true); load();
  });
  function paginate(delta) {
    if (!data || dirty || loading) return;
    applied.set('page', data.page + delta); updateUrl(true); load();
  }
  previous.addEventListener('click', () => paginate(-1)); next.addEventListener('click', () => paginate(1));
  refresh.addEventListener('click', load);
  field('filter-clear').addEventListener('click', () => { applied = new URLSearchParams(); updateUrl(true); restore(); });
  window.addEventListener('popstate', restore);
  const poll = () => {
    if (!document.hidden && !dirty && !loading && data?.page === 1) load();
  };
  let timer = setInterval(poll, 5000);
  window.addEventListener('pageshow', event => {
    if (event.persisted) { clearInterval(timer); timer = setInterval(poll, 5000); restore(); }
  });
  window.addEventListener('pagehide', () => { clearInterval(timer); controller?.abort(); clearBotPicker(); clearAuthorPicker(); });
  restore();
})();
