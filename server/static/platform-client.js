/* Shared transport for existing page controllers. UI and game renderers stay unchanged. */
window.platformFetch = function (input, options = {}) {
  const headers = new Headers(options.headers);
  const method = (options.method || "GET").toUpperCase();
  if (!["GET", "HEAD", "OPTIONS"].includes(method))
    headers.set("X-Legend-Request", "1");
  return fetch(input, { ...options, headers, credentials: "same-origin" });
};

window.PlatformClient = class PlatformClient {
  constructor(namespace = "/") {
    this.namespace = namespace;
    this.listeners = new Map();
    this.connected = false;
    this.closed = false;
    this.moves = [];
    this.applied = -1;
    this.started = false;
    this.snapshot = null;
    this.tableSocket = null;
    this.latestDraft = null;
    this.timer = null;
    setTimeout(() => {
      this.connected = true;
      this.dispatch("connect", {});
      this.dispatch("init", {
        user_id: window.PlatformUser?.id || "spectator",
      });
      if (namespace === "/") this.home();
    }, 0);
    window.addEventListener("pagehide", () => this.disconnect(), {
      once: true,
    });
  }
  on(name, handler) {
    if (!this.listeners.has(name)) this.listeners.set(name, []);
    this.listeners.get(name).push(handler);
    return this;
  }
  dispatch(name, value) {
    for (const handler of this.listeners.get(name) || []) handler(value);
  }
  emit(name, value = {}) {
    if (name === "join_match") {
      this.id = value.match_id;
      if (!this.polling) {
        this.polling = true;
        this.poll();
      }
    } else if (name === "player_move") {
      if (!this.snapshot) return;
      const match = this.snapshot;
      const seat = Number(
        value.seat ||
          (match.slug === "gomoku" ||
          match.slug === "tictactoe" ||
          match.slug === "connect4"
            ? match.state?.side
            : match.players.findIndex(
                (player) =>
                  player.type === "human" &&
                  player.user_id === window.PlatformUser?.id,
              ) + 1),
      );
      let action;
      try {
        action = value.move
          ? JSON.parse(value.move)
          : { x: value.x, y: value.y };
      } catch {
        return;
      }
      const turn = Math.max(
        match.turn || 1,
        (match.move_history?.length || 0) + 1,
        match.displays?.length || 0,
      );
      if (!this.moves.some((move) => move.seat === seat && move.turn === turn))
        this.moves.push({ seat, turn, action });
      this.submit();
    } else if (name === "table_open" || name === "table_update") {
      this.draftGame = value.game || this.draftGame;
      const seats = value.seats || [];
      this.latestDraft = {
        game: this.draftGame,
        players: seats.map((seat) =>
          seat.type === "human"
            ? { type: "human" }
            : {
                type: "bot",
                bot_id: seat.botId || seat.bot_id,
                version: seat.version || null,
              },
        ),
      };
      // Display-only partial seats are handled by the shared table endpoint.
      this.openDraft();
    } else if (name === "table_close") {
      this.latestDraft = null;
      this.tableSocket?.close();
      this.tableSocket = null;
    }
    return this;
  }
  async submit() {
    if (this.submitting || !this.snapshot) return;
    const current = this.snapshot;
    this.moves = this.moves.filter((move) => move.turn >= (current.turn || 1));
    const index = this.moves.findIndex(
      (move) =>
        move.turn === current.turn &&
        (current.waiting || []).includes(move.seat),
    );
    if (index < 0) return;
    this.submitting = true;
    const [move] = this.moves.splice(index, 1);
    try {
      const response = await platformFetch(
        `/api/matches/${encodeURIComponent(this.id)}/moves`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(move),
        },
      );
      if (!response.ok) {
        const data = await response.json();
        if (response.status !== 400)
          alert(data.detail || "Unable to submit the move.");
      }
    } catch (error) {
      console.warn("Move submission failed", error);
    } finally {
      this.submitting = false;
    }
  }
  async ready() {
    for (let i = 0; i < 300 && !this.closed; i++) {
      if (
        typeof phaserGame !== "undefined" &&
        phaserGame.scene.scenes.some((scene) => scene.sys.isActive())
      )
        return true;
      await new Promise((resolve) => setTimeout(resolve, 50));
    }
    return false;
  }
  async poll() {
    if (this.closed) return;
    try {
      const response = await platformFetch(
        `/api/matches/${encodeURIComponent(this.id)}`,
        { cache: "no-store" },
      );
      if (!response.ok) throw new Error("Unable to load match.");
      const match = await response.json();
      this.snapshot = match;
      const board = ["gomoku", "tictactoe", "connect4"].includes(match.slug);
      const players = {
        player_1: match.players[0],
        player_2: match.players[1],
      };
      const base = {
        match_id: match.id,
        game_id: match.id,
        players,
        player_types: Object.fromEntries(
          match.players.map((player, index) => [
            String(index + 1),
            player.type,
          ]),
        ),
        winner: board
          ? match.winner === 0 || match.winner === 1
            ? match.winner + 1
            : 0
          : match.winner,
        move_history: match.move_history || [],
        displays: match.displays || [],
      };
      if (match.status === "finished") {
        if (!(await this.ready())) return;
        this.dispatch(this.started ? "match_finished" : "match_status", {
          ...base,
          status: "finished",
        });
        this.closed = true;
        return;
      }
      if (match.status === "interrupted") {
        this.dispatch("finish", {
          ...base,
          winner: board ? 0 : -1,
          error_msg: "Match interrupted.",
        });
        this.closed = true;
        return;
      }
      if (
        !this.started &&
        (board ? match.state?.board : match.displays?.length)
      ) {
        if (!(await this.ready())) return;
        this.started = true;
        this.dispatch("game_started", {
          ...base,
          board: match.state?.board,
          current_player: match.state?.side,
          state: match.displays?.[0],
        });
        this.applied = board ? match.move_history.length : 0;
        if (!board) {
          for (let i = 1; i < match.displays.length; i++)
            this.dispatch("update", { ...base, state: match.displays[i] });
          this.applied = match.displays.length - 1;
        }
        const owner = match.players.some(
          (player) =>
            player.type === "human" &&
            player.user_id === window.PlatformUser?.id,
        );
        if (!owner)
          this.dispatch("match_status", {
            ...base,
            status: "playing",
            board: match.state?.board,
            current_player: match.state?.side,
          });
      } else if (this.started) {
        if (board && match.move_history.length > this.applied) {
          this.dispatch("update", {
            ...base,
            board: match.state.board,
            current_player: match.state.side,
            ai_move: match.move_history.at(-1),
            winner: 0,
          });
          this.applied = match.move_history.length;
        } else if (!board) {
          for (let i = this.applied + 1; i < match.displays.length; i++)
            this.dispatch("update", { ...base, state: match.displays[i] });
          this.applied = match.displays.length - 1;
        }
      }
      await this.submit();
    } catch (error) {
      console.warn("Match refresh failed", error);
    }
    if (!this.closed) this.timer = setTimeout(() => this.poll(), 500);
  }
  async home() {
    if (this.closed) return;
    try {
      const [matches, tables] = await Promise.all([
        platformFetch("/api/matches?limit=50").then((r) => r.json()),
        platformFetch("/api/tables").then((r) => r.json()),
      ]);
      this.dispatch("latest_matches", {
        matches: matches
          .filter((match) => match.status === "finished")
          .slice(0, 20)
          .map((match) => {
            const value = { ...match };
            match.players.forEach((player, index) => {
              const key = `player_${index + 1}`;
              value[key] = player.name;
              value[key + "_id"] = player.bot_id;
              value[key + "_version"] = player.version;
              value[key + "_is_human"] = player.type === "human";
              value[key + "_rating"] = player.rating;
            });
            return value;
          }),
      });
      this.dispatch("tables_update", {
        tables: tables.map((table) => ({
          ...table,
          host: table.owner,
          seats: table.players,
        })),
      });
    } catch (error) {
      console.warn("Homepage refresh failed", error);
    }
    if (!this.closed) this.timer = setTimeout(() => this.home(), 3000);
  }
  openDraft() {
    if (!window.PlatformUser || !this.latestDraft) return;
    if (!this.tableSocket || this.tableSocket.readyState > 1) {
      const socket = (this.tableSocket = new WebSocket(
        `${location.protocol === "https:" ? "wss:" : "ws:"}//${location.host}/api/tables/ws`,
      ));
      socket.addEventListener("open", () => {
        if (this.latestDraft) socket.send(JSON.stringify(this.latestDraft));
      });
    } else if (this.tableSocket.readyState === WebSocket.OPEN)
      this.tableSocket.send(JSON.stringify(this.latestDraft));
  }
  disconnect() {
    this.closed = true;
    this.connected = false;
    clearTimeout(this.timer);
    this.tableSocket?.close();
  }
};

document.addEventListener("DOMContentLoaded", () => {
  document
    .querySelector('a[href="#logout"]')
    ?.addEventListener("click", async (event) => {
      event.preventDefault();
      await platformFetch("/api/logout", { method: "POST" });
      location.href = "/";
    });
});
