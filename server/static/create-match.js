window.initMatchSetup = function (options) {
    const socket = options.socket || new PlatformClient('/tables');
    const escapeHtml = text => { const div = document.createElement('div'); div.textContent = text; return div.innerHTML; };
    // Dialog logic: step 1 picks the game, step 2 fills the two seats.
    const modal = document.getElementById('modal-create-table');
    const playerModal = document.getElementById('modal-player-setup');
    const btnCreate = document.getElementById('btn-create-table');
    const btnModalCreate = document.getElementById('btn-modal-create');
    const gameGrid = document.getElementById('game-grid');
    const playerSlots = document.getElementById('player-slots');
    const playerGameName = document.getElementById('player-modal-game-name');
    const lineupNote = document.getElementById('lineup-note');
    const btnStartGame = document.getElementById('btn-start-game');

    let selectedGame = null, setupRequest = 0;
    const isAuthenticated = options.isAuthenticated;
    const CURRENT_USERNAME = options.username;
    const HUMAN_LABEL = CURRENT_USERNAME || 'Player';

    // openGameTable() runs before the seats are (re)rendered, so the lineup rides
    // along with table_open instead of a fresh table briefly showing two empty seats.
    function openGameTable() {
        if (!selectedGame) return;
        socket.emit('table_open', { game: selectedGame.name, seats: currentLineup() });
    }

    function syncGameTable() {
        if (!selectedGame) return;
        socket.emit('table_update', { game:selectedGame.name, seats: currentLineup() });
    }

    function closeGameTable() {
        setupRequest++;
        selectedGame = null;
        socket.emit('table_close');
    }

    function openDialog(el) { el.classList.remove('hidden'); }
    function closeDialog(el) { el.classList.add('hidden'); }
    function isDialogOpen(el) { return el && !el.classList.contains('hidden'); }

    function renderGameCards(games, emptyText) {
        gameGrid.innerHTML = '';
        btnModalCreate.disabled = true;
        if (!games.length) {
            const p = document.createElement('p');
            p.className = 'game-empty';
            p.textContent = emptyText || 'No games available.';
            gameGrid.appendChild(p);
            return;
        }
        games.forEach((g, idx) => {
            const card = document.createElement('button');
            card.type = 'button';
            card.className = 'game-card';
            card.dataset.id = g.slug;
            card.dataset.name = g.name;
            card.style.setProperty('--i', String(idx));
            card.setAttribute('aria-pressed', 'false');
            const name = document.createElement('span');
            name.className = 'game-name';
            name.textContent = g.name;
            const ord = document.createElement('span');
            ord.className = 'game-idx';
            ord.textContent = String(idx + 1).padStart(2, '0');
            card.appendChild(name);
            card.appendChild(ord);
            card.addEventListener('click', () => pickGame(card));
            gameGrid.appendChild(card);
        });
    }

    function pickGame(card) {
        gameGrid.querySelectorAll('.game-card').forEach((c) => c.setAttribute('aria-pressed', String(c === card)));
        selectedGame = { slug: card.dataset.id, name: card.dataset.name };
        btnModalCreate.disabled = false;
    }

    btnCreate.addEventListener('click', async () => {
        btnCreate.classList.add('no-shine');
        if (!isAuthenticated) {
            alert('Please log in to create a match.');
            socket.disconnect();
            window.location.href = '/login';
            return;
        }
        closeGameTable();
        if (options.game) { selectedGame = options.game; showPlayerSetup(); return; }
        gameGrid.innerHTML = '';
        openDialog(modal);
        try {
            const resp = await platformFetch('/api/games');
            renderGameCards(await resp.json());
        } catch (e) {
            renderGameCards([], 'Could not load the game list.');
        }
    });

    modal?.addEventListener('click', (e) => {
        if (e.target === modal) closeDialog(modal);
    });

    btnModalCreate?.addEventListener('click', () => {
        if (!selectedGame) return;
        closeDialog(modal);
        showPlayerSetup();
    });

    const slotType = (slot) => slot.dataset.type || 'bot';

    function playerSlotHtml(i, botOptions) {
        return `
            <div class="seat-card" data-type="bot" style="--i:${i - 1}">
                <div class="seat-head">
                    <span class="seat-label">Seat ${i}</span>
                    <span class="seg" role="radiogroup" aria-label="Seat ${i} type">
                        <button type="button" class="seg-btn seg-bot" role="radio" aria-checked="true">Bot</button>
                        <button type="button" class="seg-btn seg-human" role="radio" aria-checked="false">Human</button>
                    </span>
                </div>
                <div class="seat-bot-row">
                    <select class="seat-select player-bot" aria-label="Bot for seat ${i}">${botOptions}</select>
                    <details class="seat-version">
                        <summary aria-label="Change bot version for seat ${i}"><span data-version-label>Latest</span></summary>
                        <div class="version-options" role="group" aria-label="Bot version for seat ${i}"></div>
                    </details>
                    <input type="hidden" class="player-version">
                </div>
                <input type="text" readonly tabindex="-1" aria-disabled="true" class="seat-name player-name seat-hidden" placeholder="Player ${i}">
            </div>
        `;
    }

    // A human seat is always the signed-in player, so the dropdown gives way to a
    // read-only field naming who plays, and the card takes the player's hue.
    function syncPlayerSlot(slot) {
        const isBot = slotType(slot) === 'bot';
        const bot = slot.querySelector('.player-bot');
        const name = slot.querySelector('.player-name');
        const version = slot.querySelector('.player-version');
        slot.querySelector('.seat-bot-row').classList.toggle('seat-hidden', !isBot);
        if (!isBot) slot.querySelector('.seat-version').open = false;
        slot.dataset.type = isBot ? 'bot' : 'human';
        if (bot) { bot.classList.toggle('seat-hidden', !isBot); bot.disabled = !isBot; }
        if (version) { version.classList.toggle('seat-hidden', !isBot); version.disabled = !isBot || !version.value; }
        if (name) {
            name.classList.toggle('seat-hidden', isBot);
            if (!isBot && !name.value) name.value = HUMAN_LABEL;
        }
        slot.querySelectorAll('.seg-btn').forEach((b) => {
            const humanSeat = b.classList.contains('seg-human');
            b.setAttribute('aria-checked', String(humanSeat !== isBot));
        });
        updateLineupNote();
    }

    function currentLineup() {
        const seats = [];
        playerSlots.querySelectorAll('.seat-card').forEach((slot, idx) => {
            if (slotType(slot) === 'bot') {
                const sel = slot.querySelector('.player-bot');
                const botId = sel ? sel.value : '';
                const label = sel && sel.selectedIndex >= 0 ? sel.options[sel.selectedIndex].text : `Bot ${idx + 1}`;
                const versionSelect = slot.querySelector('.player-version');
                const version = Number(versionSelect.value) || null;
                seats.push({ type: 'bot', botId, name: botId ? label : '', version,
                    oldVersion: versionSelect.value !== versionSelect.dataset.latest });
            } else {
                const input = slot.querySelector('.player-name');
                seats.push({ type: 'human', botId: null, name: (input && input.value) || HUMAN_LABEL });
            }
        });
        return seats;
    }

    function updateLineupNote() {
        // Explain blocked seats and the rating rule only when relevant.
        const lineup = currentLineup();
        const stuck = lineup.some((s) => s.type === 'bot' && (!s.botId || !s.version));
        btnStartGame.disabled = stuck;
        lineupNote.textContent = stuck ? 'A bot seat still has no bot to pick.' :
            lineup.some(s => s.type === 'bot' && s.oldVersion) ? 'Older bot versions do not affect ratings for either player.' : '';
        syncGameTable();
    }

    function renderPlayerSlots(botOptions, gameId) {
        playerSlots.innerHTML = '';
        playerSlots.dataset.forGame = String(gameId);
        for (let i = 1; i <= 2; i++) {
            playerSlots.innerHTML += playerSlotHtml(i, botOptions);
        }
        playerSlots.querySelectorAll('.seat-card').forEach((slot) => {
            slot.querySelectorAll('.seg-btn').forEach((btn) => {
                btn.addEventListener('click', () => {
                    slot.dataset.type = btn.classList.contains('seg-human') ? 'human' : 'bot';
                    syncPlayerSlot(slot);
                });
            });
            const syncVersions = () => {
                const bot = slot.querySelector('.player-bot');
                const select = slot.querySelector('.player-version');
                const versions = (bot.selectedOptions[0]?.dataset.versions || '').split(',').filter(Boolean);
                select.value = versions[0] || '';
                select.dataset.latest = select.value;
                slot.querySelector('.version-options').replaceChildren(...versions.map((v, index) => {
                    const option = document.createElement('button');
                    option.type = 'button';
                    option.className = 'version-option';
                    option.dataset.version = v;
                    option.textContent = `v${v}${index === 0 ? ' (latest)' : ''}`;
                    option.setAttribute('aria-pressed', String(index === 0));
                    option.addEventListener('click', () => {
                        select.value = v;
                        slot.querySelector('[data-version-label]').textContent = index === 0 ? 'Latest' : `v${v}`;
                        slot.querySelectorAll('.version-option').forEach(button => button.setAttribute('aria-pressed', String(button === option)));
                        slot.querySelector('.seat-version').open = false;
                        slot.querySelector('.seat-version summary').focus();
                        updateLineupNote();
                    });
                    return option;
                }));
                slot.querySelector('[data-version-label]').textContent = 'Latest';
                slot.querySelector('.seat-version').open = false;
                syncPlayerSlot(slot);
            };
            slot.querySelector('.player-bot').addEventListener('change', syncVersions);
            syncVersions();
        });
        openDialog(playerModal);
    }

    function showPlayerSetup() {
        const request = ++setupRequest, game = selectedGame;
        playerGameName.textContent = selectedGame.name;
        openGameTable();

        // Re-opening the same game after abandoning a table reuses its lineup.
        if (playerSlots.dataset.forGame === String(selectedGame.slug) && playerSlots.children.length === 2) {
            updateLineupNote();
            openDialog(playerModal);
            return;
        }

        playerSlots.innerHTML = '';
        lineupNote.textContent = '';
        btnStartGame.disabled = true;
        openDialog(playerModal);

        // Fetch bot list for the selected game
        platformFetch(`/api/bots?game=${encodeURIComponent(selectedGame.slug)}`)
            .then(resp => resp.json())
            .then(bots => {
                if (request !== setupRequest) return;
                const botOptions = bots.length
                    ? bots.map(b => `<option value="${escapeHtml(String(b.id))}" data-versions="${(b.versions || []).filter(Number.isInteger).join(',')}">${escapeHtml(b.bot_name)}</option>`).join('')
                    : '<option value="">No bots available</option>';
                renderPlayerSlots(botOptions, game.slug);
            })
            .catch(err => {
                if (request !== setupRequest) return;
                console.error('Failed to load bots:', err);
                renderPlayerSlots('<option value="">No bots available</option>', game.slug);
            });
    }

    // Every way out of step 2 abandons the table; only "Start game" keeps it,
    // and that path clears it server-side once the match row exists.
    playerModal.addEventListener('click', (e) => {
        if (e.target === playerModal) {
            closeDialog(playerModal);
            closeGameTable();
        }
    });

    document.addEventListener('click', (e) => {
        playerSlots.querySelectorAll('.seat-version[open]').forEach(picker => {
            if (!picker.contains(e.target)) picker.open = false;
        });
    });

    document.addEventListener('keydown', (e) => {
        if (e.key !== 'Escape') return;
        const versionPicker = playerSlots.querySelector('.seat-version[open]');
        if (versionPicker) {
            versionPicker.open = false;
            versionPicker.querySelector('summary').focus();
            return;
        }
        if (isDialogOpen(playerModal)) {
            closeDialog(playerModal);
            closeGameTable();
        } else if (isDialogOpen(modal)) {
            closeDialog(modal);
        }
    });

    btnStartGame.addEventListener('click', async () => {
        const players = currentLineup().map((s) => ({ type: s.type, name: s.name, botId: s.botId,
            version: s.oldVersion ? s.version : null }));
        const missing = players.some((p) => !p.name);
        if (missing) {
            alert('Fill both seats before starting.');
            return;
        }
        
        try {
            const resp = await platformFetch('/api/matches', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ game: selectedGame.slug, players: players.map(p => ({type:p.type,bot_id:p.botId,version:p.version})) })
            });
            const data = await resp.json();
            if (data.id) {
                window.location.href = `/match/${data.id}`;
            } else {
                alert('Failed to create match: ' + (data.error || data.detail || 'Unknown error'));
            }
        } catch (e) {
            alert('Failed to create match: ' + e.message);
        }
    });
};
