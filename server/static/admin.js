(() => {
  const form = document.getElementById('bot-queue-form');
  if (!form) return;
  const botId = document.getElementById('queue-bot-id');
  const opponentId = document.getElementById('queue-opponent-id');
  const count = document.getElementById('queue-match-count');
  const check = document.getElementById('queue-check-bot');
  const submit = document.getElementById('queue-submit');
  const refresh = document.getElementById('queue-refresh');
  const info = document.getElementById('queue-bot-info');
  const status = document.getElementById('queue-status');
  const rows = document.getElementById('queue-batches');
  let checked = null, busy = false, loading = false, requestId = null, generation = 0;

  async function request(url, options) {
    const response = await platformFetch(url, options);
    if (response.redirected) throw new Error(I18n.t("Your session has expired. Please sign in again."));
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? I18n.t(data.detail) : I18n.t("Unable to load the Bot match queue. Please try again."));
    return data;
  }
  function controls() {
    check.disabled = busy || !botId.value.trim();
    submit.disabled = busy || !checked || checked.id !== botId.value.trim()
      || (checked.opponent?.id || '') !== opponentId.value.trim() || (!checked.opponent && !checked.opponents);
    botId.disabled = opponentId.disabled = count.disabled = busy;
  }
  function invalidate() {
    checked = null; requestId = null; generation++;
    info.textContent = I18n.t("Check this Bot ID before queueing matches.");
    controls();
  }
  botId.addEventListener('input', invalidate);
  opponentId.addEventListener('input', invalidate);
  count.addEventListener('input', () => { requestId = null; });
  check.addEventListener('click', async () => {
    const token = ++generation, value = botId.value.trim(), opponent = opponentId.value.trim();
    checked = null; busy = true; controls();
    info.textContent = I18n.t("Checking Bot…");
    try {
      const [bot, other] = await Promise.all([
        request(`/api/admin/bot-queue/bot?bot_id=${encodeURIComponent(value)}`, {cache: 'no-store'}),
        opponent ? request(`/api/admin/bot-queue/bot?bot_id=${encodeURIComponent(opponent)}`, {cache: 'no-store'}) : null,
      ]);
      if (token !== generation) return;
      if (other && bot.game !== other.game) throw new Error(I18n.t('Both Bots must belong to the same game.'));
      checked = {...bot, opponent: other};
      info.textContent = other
        ? I18n.t('{0} — {1} · latest v{2}.', bot.name, I18n.t(bot.game), bot.version)
        : I18n.t("{0} — {1} · latest v{2} · {3} available opponent(s).", bot.name, I18n.t(bot.game), bot.version, bot.opponents);
      if (other) info.textContent += ' ' + I18n.t('Against {0} · latest v{1}.', other.name, other.version);
      else if (!bot.opponents) info.textContent += I18n.t(" Add another Bot in this game before queueing matches.");
    } catch (error) { info.textContent = I18n.t(error.message); }
    finally { busy = false; controls(); }
  });
  function detail(cell, text) {
    const span = document.createElement('span'); span.className = 'queue-detail'; span.textContent = text; cell.append(span);
  }
  async function load() {
    if (loading) return;
    loading = true; refresh.disabled = true;
    try {
      const batches = await request('/api/admin/bot-queue', {cache: 'no-store'});
      rows.replaceChildren();
      if (!batches.length) {
        const row = rows.insertRow(), cell = row.insertCell(); cell.colSpan = 5; cell.textContent = I18n.t("No batches in this server session.");
      }
      for (const batch of batches) {
        const row = rows.insertRow(), bot = row.insertCell(), progress = row.insertCell(), results = row.insertCell(), state = row.insertCell(), match = row.insertCell();
        bot.textContent = batch.bot_name; detail(bot, batch.bot_id);
        if (batch.opponent_id) {
          detail(bot, batch.opponent_name); detail(bot, batch.opponent_id);
        }
        detail(bot, I18n.t(batch.game));
        progress.textContent = `${batch.completed} / ${batch.total}`;
        detail(progress, I18n.t("{0} rated · {1} skipped", batch.rated, batch.skipped));
        results.textContent = I18n.t('{0} W · {1} L · {2} D', batch.wins, batch.losses, batch.draws);
        results.title = I18n.t('Results from {0}’s perspective.', batch.bot_name);
        if (batch.excluded) detail(results, I18n.t('{0} not counted', batch.excluded));
        state.textContent = I18n.t(batch.status); if (batch.error) detail(state, batch.error);
        const id = batch.current_match || batch.last_match;
        if (id) { const link = document.createElement('a'); link.href = I18n.url(`/match/${encodeURIComponent(id)}`); link.textContent = batch.current_match ? I18n.t("Current match") : I18n.t("Last match"); match.append(link); }
        else match.textContent = '—';
      }
    } catch (error) { status.textContent = I18n.t(error.message); status.dataset.error = 'true'; }
    finally { loading = false; refresh.disabled = false; }
  }
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (busy || submit.disabled || !form.reportValidity()) return;
    // Reuse the ID after a lost response so retrying cannot enqueue 100 matches twice.
    requestId ||= (globalThis.crypto?.randomUUID?.() || `batch-${Date.now()}-${Math.random().toString(36).slice(2)}`);
    const body = {bot_id: checked.id, opponent_id: checked.opponent?.id || null, count: Number(count.value), request_id: requestId};
    busy = true; controls(); status.textContent = I18n.t("Queueing matches…"); status.dataset.error = 'false';
    try {
      const batch = await request('/api/admin/bot-queue', {method: 'POST', headers: {'Content-Type': "application/json"}, body: JSON.stringify(body)});
      status.textContent = batch.opponent_id
        ? I18n.t('Queued {0} matches: {1} vs {2} ({3}).', batch.total, batch.bot_name, batch.opponent_name, I18n.t(batch.game))
        : I18n.t("Queued {0} matches for {1} ({2}).", batch.total, batch.bot_name, I18n.t(batch.game));
      requestId = null;
      await load();
    } catch (error) { status.textContent = I18n.t(error.message); status.dataset.error = 'true'; }
    finally { busy = false; controls(); }
  });
  refresh.addEventListener('click', load);
  document.getElementById('bot-queue-tab').addEventListener('admin-tab-selected', load);
  const timer = setInterval(() => {
    if (!document.hidden && !document.getElementById('bot-queue-panel').hidden) load();
  }, 2000);
  window.addEventListener('pagehide', () => clearInterval(timer));
  controls();
})();

(() => {
  const forms = Array.from(document.querySelectorAll('.danger-form'));
  let busy = false;
  function synchronize(form) {
    const game = form.elements.game.value;
    const expected = game ? `${form.dataset.phrase} ${game}` : '';
    form.querySelector('.danger-hint').textContent = game
      ? I18n.t("Type exactly: {0}", expected) : I18n.t("Select a game to see the required confirmation text.");
    form.querySelector('button').disabled = busy || !game || form.elements.confirmation.value !== expected;
  }
  forms.forEach(form => {
    const status = form.querySelector("[role=\"status\"]");
    form.elements.game.addEventListener('change', () => {
      form.elements.confirmation.value = '';
      status.textContent = '';
      synchronize(form);
    });
    form.elements.confirmation.addEventListener('input', () => synchronize(form));
    form.addEventListener('submit', async event => {
      event.preventDefault();
      if (busy || !form.reportValidity() || form.querySelector('button').disabled) return;
      const body = {game: form.elements.game.value, confirmation: form.elements.confirmation.value};
      busy = true;
      forms.forEach(item => {
        item.elements.game.disabled = item.elements.confirmation.disabled = true;
        item.setAttribute('aria-busy', 'true');
        synchronize(item);
      });
      status.textContent = I18n.t("Processing…");
      status.dataset.error = 'false';
      try {
        const response = await platformFetch(`/api/admin/operations/${form.dataset.action}`, {
          method: 'POST', headers: {'Content-Type': "application/json"}, body: JSON.stringify(body),
        });
        if (response.redirected) throw new Error(I18n.t("Your session has expired. Please sign in again."));
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(typeof data.detail === 'string' ? I18n.t(data.detail) : I18n.t("Operation failed. Please check the result before retrying."));
        status.textContent = form.dataset.action === 'clear-matches'
          ? I18n.t("Deleted {0} match records for {1}.", data.deleted_matches, body.game)
          : I18n.t("Reset {0} Bot versions to 1500 for {1}.", data.reset_versions, body.game);
      } catch (error) {
        status.textContent = I18n.t(error.message);
        status.dataset.error = 'true';
      } finally {
        // Require a fresh typed confirmation for every attempt, including retries.
        form.elements.confirmation.value = '';
        busy = false;
        forms.forEach(item => {
          item.elements.game.disabled = item.elements.confirmation.disabled = false;
          item.removeAttribute('aria-busy');
          synchronize(item);
        });
      }
    });
    synchronize(form);
  });
})();

(() => {
  const panel = document.getElementById('database-panel');
  if (!panel) return;
  const table = document.getElementById('db-table');
  const size = document.getElementById('db-page-size');
  const refresh = document.getElementById('db-refresh');
  const previous = document.getElementById('db-previous');
  const next = document.getElementById('db-next');
  const status = document.getElementById('db-status');
  const grid = document.getElementById('db-grid');
  const summary = document.getElementById('db-summary');
  const pageLabel = document.getElementById('db-page');
  let page = 1, pages = 1, controller;

  async function request(url, signal) {
    const response = await platformFetch(url, {signal, cache: 'no-store'});
    if (response.redirected) throw new Error(I18n.t("Your session has expired. Please sign in again."));
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || I18n.t("Unable to load database. Please check your access and try again."));
    return data;
  }
  function setStatus(message, error = false) {
    status.textContent = message;
    status.dataset.error = String(error);
    status.hidden = !message;
  }
  function cell(tag, text, className) {
    const element = document.createElement(tag);
    element.textContent = text;
    if (className) element.className = className;
    return element;
  }
  async function load(target = 1) {
    if (!table.value) return;
    controller?.abort();
    controller = new AbortController();
    const signal = controller.signal;
    previous.disabled = next.disabled = refresh.disabled = true;
    grid.setAttribute('aria-busy', 'true');
    grid.hidden = true;
    summary.textContent = pageLabel.textContent = '';
    setStatus(I18n.t("Loading records…"));
    const url = new URL(panel.dataset.tableUrl, location.origin);
    url.search = new URLSearchParams({name: table.value, page: target, page_size: size.value});
    try {
      const data = await request(url, signal);
      if (signal.aborted) return;
      const head = document.createElement('tr');
      for (const column of data.columns) {
        const th = cell('th', column.name);
        th.scope = 'col';
        th.append(cell('span', [column.type || 'ANY', column.primary_key ? 'PK' : ''].filter(Boolean).join(' · '), 'db-column-type'));
        head.append(th);
      }
      document.getElementById('db-head').replaceChildren(head);
      const body = document.createDocumentFragment();
      for (const row of data.rows) {
        const tr = document.createElement('tr');
        row.forEach((value, index) => {
          const td = document.createElement('td');
          const hidden = data.columns[index].hidden;
          let text = hidden ? 'Hidden' : value === null ? 'NULL' : String(value);
          if (typeof value === 'string' && text.length > data.cell_limit) text = text.slice(0, data.cell_limit) + '…';
          td.append(cell('span', text, 'db-value' + (hidden || value === null ? ' db-muted' : '')));
          tr.append(td);
        });
        body.append(tr);
      }
      document.getElementById('db-body').replaceChildren(body);
      page = data.page;
      pages = data.pages;
      grid.hidden = false;
      grid.scrollTop = grid.scrollLeft = 0;
      summary.textContent = data.total ? I18n.t("{0}–{1} of {2} rows", (page - 1) * data.page_size + 1, Math.min(page * data.page_size, data.total), data.total) : I18n.t("0 rows");
      pageLabel.textContent = `${page} / ${pages}`;
      previous.disabled = page <= 1;
      next.disabled = page >= pages;
      setStatus(data.rows.length ? '' : I18n.t("This table is empty."));
    } catch (error) {
      if (!signal.aborted) setStatus(error.message, true);
    } finally {
      if (!signal.aborted) {
        refresh.disabled = false;
        grid.setAttribute('aria-busy', 'false');
      }
    }
  }
  table.addEventListener('change', () => load());
  size.addEventListener('change', () => load());
  previous.addEventListener('click', () => load(page - 1));
  next.addEventListener('click', () => load(page + 1));
  refresh.addEventListener('click', async () => {
    if (table.options.length) return load(page);
    await initialize();
  });
  async function initialize() {
    try {
      refresh.disabled = true;
      setStatus(I18n.t("Loading tables…"));
      const data = await request(panel.dataset.tablesUrl);
      table.replaceChildren(...data.tables.map(name => new Option(name, name)));
      table.disabled = !data.tables.length;
      if (data.tables.length) await load();
      else setStatus(I18n.t("No tables found."));
    } catch (error) {
      table.replaceChildren();
      setStatus(error.message, true);
    } finally {
      refresh.disabled = false;
    }
  }
  initialize();
})();

(() => {
  const tabs = Array.from(document.querySelectorAll('.admin-tab'));
  if (!tabs.length) return;
  const storageKey = 'legend-admin-tab';
  function select(tab, scroll = true) {
    tabs.forEach(item => {
      const selected = item === tab;
      item.setAttribute('aria-selected', String(selected));
      item.tabIndex = selected ? 0 : -1;
      document.getElementById(item.getAttribute('aria-controls')).hidden = !selected;
    });
    try { sessionStorage.setItem(storageKey, tab.id); } catch {}
    if (scroll) tab.scrollIntoView({block: 'nearest', inline: 'nearest'});
    tab.dispatchEvent(new Event('admin-tab-selected'));
  }
  tabs.forEach((tab, index) => {
    tab.addEventListener('click', () => select(tab));
    tab.addEventListener('keydown', event => {
      let next;
      if (event.key === 'ArrowRight') next = tabs[(index + 1) % tabs.length];
      if (event.key === 'ArrowLeft') next = tabs[(index + tabs.length - 1) % tabs.length];
      if (event.key === 'Home') next = tabs[0];
      if (event.key === 'End') next = tabs.at(-1);
      if (!next) return;
      event.preventDefault();
      select(next);
      next.focus();
    });
  });
  let saved;
  try { saved = sessionStorage.getItem(storageKey); } catch {}
  select(tabs.find(tab => tab.id === saved) || tabs[0], false);
})();

(() => {
  const form = document.getElementById('site-settings-form');
  if (!form) return;
  const hours = document.getElementById('chat-history-hours');
  const ladder = document.getElementById('ladder-interval-minutes');
  const limits = Array.from(form.querySelectorAll('[data-game-time-limit]'));
  const save = document.getElementById('site-settings-save');
  const refresh = document.getElementById('site-settings-refresh');
  const status = document.getElementById('site-settings-status');
  const endpoint = '/api/admin/settings';
  let loaded = false;
  let busy = false;

  async function update(saving = false) {
    if (busy) return;
    busy = true;
    const value = Number(hours.value);
    const seconds = Number(ladder.value) * 60;
    const timeLimits = Object.fromEntries(limits.map(input => [input.dataset.gameTimeLimit, Math.round(Number(input.value) * 1000)]));
    hours.disabled = ladder.disabled = save.disabled = refresh.disabled = true;
    limits.forEach(input => { input.disabled = true; });
    form.setAttribute('aria-busy', 'true');
    status.textContent = saving ? I18n.t("Saving site settings…") : I18n.t("Loading site settings…");
    status.dataset.error = 'false';
    try {
      const response = await platformFetch(endpoint, saving ? {
        method: 'POST',
        headers: {'Content-Type': "application/json"},
        body: JSON.stringify({chat_history_hours: value, ladder_interval_seconds: seconds, bot_time_limits_ms: timeLimits}),
      } : {cache: 'no-store'});
      if (response.redirected) throw new Error(I18n.t("Your session has expired. Please sign in again."));
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(typeof data.detail === 'string' ? I18n.t(data.detail) : I18n.t("Unable to update site settings. Please try again."));
      hours.value = data.chat_history_hours;
      ladder.value = data.ladder_interval_seconds / 60;
      limits.forEach(input => { input.value = data.bot_time_limits_ms[input.dataset.gameTimeLimit] / 1000; });
      loaded = true;
      status.textContent = saving ? I18n.t("Saved. Chat and ladder settings apply within 30 seconds; Bot time limits apply to newly started matches.") : '';
    } catch (error) {
      status.textContent = I18n.t(error.message);
      status.dataset.error = 'true';
    } finally {
      hours.disabled = ladder.disabled = save.disabled = !loaded;
      limits.forEach(input => { input.disabled = !loaded; });
      refresh.disabled = false;
      busy = false;
      form.removeAttribute('aria-busy');
    }
  }
  form.addEventListener('submit', event => {
    event.preventDefault();
    if (form.reportValidity()) update(true);
  });
  refresh.addEventListener('click', () => update());
  update();
})();
