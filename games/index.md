# Game rules (index)

Per-game **rules and formal models** live in this directory, **not** under `v2/docs/` (that tree is for platform FAQ / base protocols).

| File | Content |
|------|---------|
| [games-protocol.md](./games-protocol.md) | **Games WebSocket** — `wss://.../v2/games/ws` handshake, `game` envelope, maze field reference, HTTP/SSE spectator. |
| [maze.md](./maze.md) | **Maze** as a **POMDP** (partially observable), scoring, roles, product axioms. |

**HTTP (read raw markdown)**

- List: `GET /v2/faq/game`
- One doc: `GET /v2/faq/game/<slug>` — e.g. `index`, `games-protocol`, `maze`

**Implementations**

- Maze: `v2/backend/app/services/games/pomdp_maze.py`

Deploy: `v2/deploy-backend.sh` syncs this directory to the server next to the backend (see deployment guide).
