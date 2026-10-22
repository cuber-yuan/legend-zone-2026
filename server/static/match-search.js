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
  field('filter-timezone').textContent = Intl.DateTimeFormat().resolvedOptions().timeZone;

  async function request(url, signal) {
    const response = await platformFetch(url, {cache: 'no-store', signal});
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : 'Invalid filters or the service is unavailable. Please check your filters and retry.');
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
    summary.textContent = 'Filters changed. Apply Filters to update the results.';
    controls();
  }
  function updateUrl(push = false) {
    const query = applied.toString(), url = '/matches' + (query ? '?' + query : '');
    if (location.pathname + location.search !== url) history[push ? 'pushState' : 'replaceState']({}, '', url);
  }
  function botLabel(bot) {
    return `${bot.bot_name || bot.id}${bot.game ? ' · ' + bot.game : ''}${bot.owner ? ' · by ' + bot.owner : bot.deleted ? ' · deleted' : ''}`;
  }
  function chip(container, label, remove) {
    const wrapper = document.createElement('span'), text = document.createElement('span'), button = document.createElement('button');
    wrapper.className = 'matches-chip'; text.textContent = label;
    button.type = 'button'; button.textContent = '×'; button.setAttribute('aria-label', `Remove ${label}`);
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
        message('Searching…');
        try {
          const query = new URLSearchParams({q});
          if (endpoint === 'bots' && game.value) query.set('game', game.value);
          const options = await request(`/api/match-search/${endpoint}?${query}`, signal);
          if (signal.aborted) return;
          output.replaceChildren();
          for (const option of options) {
            const button = document.createElement('button'); button.type = 'button'; button.textContent = label(option);
            button.addEventListener('click', () => {
              select(option); renderSelected(); changed(); output.hidden = true; input.value = ''; input.focus();
            }); output.append(button);
          }
          if (!options.length) message('No results found.');
        } catch (error) { if (error.name !== 'AbortError') message(error.message); }
      }, 250);
    });
    return () => { clearTimeout(timer); active?.abort(); input.value = ''; output.replaceChildren(); output.hidden = true; };
  }
  const clearBotPicker = picker('filter-bot-search', 'bot-options', 'bots', bot => {
    if (selectedBots.some(item => item.id === bot.id)) return;
    if (selectedBots.length >= 20) { feedback.textContent = 'Select up to 20 Bots.'; feedback.hidden = false; return; }
    selectedBots.push(bot);
  }, botLabel);
  const clearAuthorPicker = picker('filter-author-search', 'author-options', 'authors', author => { selectedAuthor = author; }, author => author.username);
  form.addEventListener('change', event => {
    if (event.target === game) clearBotPicker();
    if (event.target.matches('select,input[type="datetime-local"]')) changed();
  });
  form.addEventListener('input', event => { if (event.target.type === 'datetime-local') changed(); });

  function localTime(value) {
    if (!value) return '';
    const date = new Date(value);
    if (!Number.isFinite(date.getTime())) throw new Error('The URL contains an invalid date filter. Clear Filters to reset it.');
    const pad = number => String(number).padStart(2, '0');
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
  }
  async function restore() {
    const token = ++restoreToken;
    controller?.abort(); clearBotPicker(); clearAuthorPicker();
    applied = new URLSearchParams(location.search); dirty = false; data = null;
    selectedBots = applied.getAll('bot').map(id => ({id}));
    selectedAuthor = applied.has('author') ? {id: applied.get('author'), username: 'User #' + applied.get('author')} : null;
    form.reset(); feedback.hidden = true;
    try {
      const requestedGame = applied.get('game') || '';
      const option = Array.from(game.options).find(option => option.value === requestedGame || option.textContent === requestedGame);
      if (requestedGame && !option) game.add(new Option(requestedGame, requestedGame));
      game.value = option ? option.value : requestedGame;
      mode.value = applied.get('bot_mode') || 'all'; state.value = applied.get('status') || 'all'; rating.value = applied.get('rating') || 'all';
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
      dirty = true; loading = false; feedback.textContent = error.message; feedback.hidden = false; controls();
    }
  }
  async function load() {
    controller?.abort(); const current = controller = new AbortController();
    loading = true; controls(); field('match-results').setAttribute('aria-busy', 'true');
    feedback.hidden = true;
    try {
      const result = await request('/api/match-search?' + applied, current.signal);
      if (current.signal.aborted) return;
      data = result;
      if (result.page === 1) applied.delete('page'); else applied.set('page', result.page);
      updateUrl();
      MatchTable.render(field('search-matches-tbody'), result.matches, 'No matches found for these filters.', {showStatus: true});
      summary.textContent = dirty ? 'Filters changed. Apply Filters to update the results.' : `${result.total} matching match${result.total === 1 ? '' : 'es'} · newest first${result.page === 1 ? ' · refreshes every 5 seconds' : ''}`;
      field('match-page').textContent = `Page ${result.page} of ${result.pages}`;
    } catch (error) {
      if (error.name !== 'AbortError') { feedback.textContent = error.message; feedback.hidden = false; }
    } finally {
      if (controller === current) { loading = false; controls(); field('match-results').setAttribute('aria-busy', 'false'); }
    }
  }
  form.addEventListener('submit', event => {
    event.preventDefault();
    if (!form.reportValidity()) return;
    restoreToken++;
    const params = new URLSearchParams();
    if (game.value) params.set('game', game.value);
    for (const bot of selectedBots) params.append('bot', bot.id);
    if (mode.value !== 'all') params.set('bot_mode', mode.value);
    if (selectedAuthor) params.set('author', selectedAuthor.id);
    if (state.value !== 'all') params.set('status', state.value);
    if (rating.value !== 'all') params.set('rating', rating.value);
    for (const [input, name] of [[from, 'created_from'], [through, 'created_to']]) {
      if (input.value) params.set(name, new Date(input.value).toISOString());
    }
    if (from.value && through.value && new Date(from.value) > new Date(through.value)) {
      feedback.textContent = 'The start time must not be after the end time.'; feedback.hidden = false; return;
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
