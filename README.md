# Legend Zone

Legend Zone is a bot battle platform. Upload a Python or C++ program to compete against other bots and earn Elo ratings, play against bots yourself, or watch match replays.

The interface and this README are in English. Other development and maintenance documentation is in Simplified Chinese.

## Features

- Six competitive games: Gomoku, Tic Tac Toe, Connect Four, Snake, Mini Snake, and Tank Battle. All game judges are implemented in Python.
- Single-file and ZIP bot uploads, immutable versions, private source code, and authorized downloads. Upload requests are limited to 16 MiB.
- Bot battles, human vs. bot matches, two-player matches on the same device, and automatic ladder matches. Selecting an older bot version disables rating changes for both players.
- Live spectating, shared replay controls, and a public Debug panel showing bot input, output, and stderr for each turn.
- Bot labels colored continuously by the latest version's rating, leaderboards, rating history, user profiles, and recent matches for each bot.

## Technology and Deployment

FastAPI and SQLite provide the API and match services. Jinja2, Tailwind CSS, and Phaser provide the pages and game canvases. In production, a single Python process serves the API, pages, and static assets. Node.js is used only for builds. Redis, message queues, and a separate frontend server are not required.

Requirements: Python 3.11+, Node.js 24+, and npm. Running C++ bots also requires g++ with C++17 support on PATH. Game judges do not require a compiler.

## Running Locally

Run these commands from the project root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.lock
cd web
npm ci
npm run build
cd ..
python -m server.cli init --admin admin
python -m server.cli serve
```

Open <http://127.0.0.1:8000>. Initialization prompts you to set the administrator password; there is no default password. The initialization command refuses to overwrite an existing database. Normal startup only validates the schema and does not run migrations.

Initialization creates the database and a persistent session signing key in `data/`. Do not delete these runtime files or commit them to Git.

## Common Commands

```powershell
# Make an existing user an administrator; takes effect on the next request.
python -m server.cli access username --role admin

# Set VIP membership separately; membership and administrator roles are independent.
python -m server.cli access username --membership vip

# Use a separate data directory.
python -m server.cli serve --data C:/legend-data --port 8000
```

Page templates are in `server/templates/`; game canvases and interactions are in `server/static/`. After changing Tailwind utility classes, run `npm run build` in `web/`. Regular template and JavaScript changes are served directly by the Python service.

## Directory Structure

```text
judges/           Pure Python game rules
server/           API, file storage, bot execution, and shared match lifecycle
server/templates/ Pages and shared template components
server/static/    Styles, Phaser canvases, and page interactions
web/              Styles and local frontend dependency builds
schema.sql        Current SQLite schema
requirements.lock Pinned production Python dependencies
```

This project is designed for a single machine and a single process. Bots run under the same operating system account as the server, and the executor is not a security sandbox. Read the security boundaries before deploying.
