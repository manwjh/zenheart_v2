# Maze (`game` = `maze`) — POMDP rules

**Wire details** (WebSocket frames, field names, HTTP/SSE spectator): [games-protocol.md](./games-protocol.md) — `GET /v2/faq/game/games-protocol`.

**Code:** `v2/backend/app/services/games/pomdp_maze.py` — implementation is structured as a **POMDP**: hidden full state on the server, **partial global knowledge** to the runner (3×3 local walls per step; goal / distance / facing to goal only after the goal cell is revealed), discrete actions, deterministic transitions.

---

## 1. POMDP formulation

| Symbol | Meaning |
|--------|---------|
| **Hidden state** `s` | Full grid, goal, player pose, run metadata — held by the **Arena** (server). The runner does **not** receive `s` in one message. |
| **Observation** `o_t` | JSON in `game_state.state` for the **playing** WebSocket: **3×3** `grid_3x3`, `position` / `player`, `cardinal`, optional `goal` / `distance_to_goal` / `toward_goal` when the goal is revealed, `move_count`, `blocked_count`, `action_cost`, `solved`, etc. (See wire doc.) |
| **Action** `a` | `new` / `apply` (reset) or `move` with `dir ∈ {n,e,s,w}`. |
| **Transition** | Deterministic: legal move updates pose and revelation; illegal move (wall, OOB) may reveal walls without a successful step. |
| **Belief** (client-side) | A rational agent maintains a **belief** over `s` (e.g. map hypotheses + position). The protocol does not require a specific algorithm — only that decisions use **observed** `o_t` and not spectator-only truth. |
| **Objective** (product) | Reach the goal with **minimum `action_cost`** = `move_count` + `blocked_count` (see §2). Optional tie-break: `elapsed_seconds` at solve. |

This is a **POMDP** (partially observable MDP): the underlying MDP is fully defined by the server, but the **runner’s information process** is partial. Micromouse-style physical runs have the same shape: on-board sensors yield local observations, not a global map at t=0.

---

## 2. Scoring and ranking

- **`move_count`:** successful `move` steps into a passage (unchanged; **lower is better** in isolation).
- **`blocked_count`:** every failed `move` into a **wall** or **out of bounds** adds **one** (the runner gets a 3×3 true view, so these are treated as **wasteful** on purpose). **Lower is better.**
- **Primary score — `action_cost`:** `move_count + blocked_count`. **Lower is better** for ranking a run (single number that encodes “steps + blunders”). Same value appears in `state` and in the `solved` `game_event` as `action_cost`.
- **Tie-break (optional):** `elapsed_seconds` (server monotonic from run start to goal, when `solved`) — e.g. equal `action_cost`, or logging only.

### 2.1 Reveal vs penalty

- A blocked move may still **reveal** a wall (or leave position unchanged for OOB) and always updates **`blocked_count`**; after **wall** or **OOB** the server sends **`game_state`** so the next observation includes the new counts (see [games-protocol.md](./games-protocol.md)).
- **`move_count` alone** is not the headline ranker anymore; use **`action_cost`** (or the pair (`move_count`, `blocked_count`)) for comparisons.
- For **statistics**, use multiple `new` / `apply` runs and report mean / percentiles of `action_cost` (see `tests/maze_trial_games_ws.py`).

### 2.2 After the goal is revealed

When the goal cell is in the server’s revealed set, the runner may receive `goal`, `distance_to_goal`, and `toward_goal`. Difficulty often drops there relative to the **phase before the goal is revealed**. Cross-run comparisons should use **diverse seeds** and agreed maze size bands so numbers stay comparable.

---

## 3. Roles (who sees what)

- **Runner** — local 3×3 and scoring fields on `/v2/games/ws` (not the full map).
- **Observer** — full `cells` for humans (`/v2/games/active`, `/#/game`); **not** the runner’s input. Turning the UI off is a product switch; it does not change the formal runner problem.
- **Arena** — ground truth, adjudication, scoring.

---

## 4. Product axioms (short)

1. The server instantiates a **procedural** maze per `new`/`apply` (64-bit seed; not sent to the runner). There is no fixed template catalog in production. See `games-protocol.md` for spectator fields (anti-speculation).
2. **Discrete steps** — one accepted `move` advances the world by one cell at most; no “instant solve” over the wire.
3. **No natural-language hints** in core rules — only structured state and `game_event` outcomes.

---

## 5. Optional extension: two-phase (Micromouse)

The shipped mode is a **single** search run until the goal. A future **search + speed** phase would need a separate `phase` or second session and **separate** leaderboards — do not mix with single-run scores unless the rulebook says so.

---

## 6. Acceptance checks (product)

- [ ] Main ranking uses `action_cost` (or `move_count` + `blocked_count` jointly) with an explicit tie-break policy if needed.
- [ ] Pacing cannot reduce per-step penalties by protocol tricks; only the hidden map + policy determine outcome counts.
- [ ] Spectator full map is not required for a valid runner client.

## 7. Baselines and evaluation practice

- **Baselines (examples):** *random* — among directions not already known to be a wall, pick uniformly; *bfs_frontier* — maintain a merged map from the 3×3 stream, BFS to goal when known, else BFS to a passage cell adjacent to unknown (frontier exploration). The latter is a simple deterministic smoke test, not a Bayes-optimal POMDP policy.
- **Multi-run:** Procedural mazes differ each `apply`. Report **distributions** (e.g. mean, p50, p90) over several runs, not a single score.
- **Retrospective `evaluation.score` on `solved`:** Composite includes path efficiency **vs. optimal** using `action_cost` in `pomdp-v2` (see `maze_pomdp_evaluation`). Use as **secondary** fitness if the product defines it; **primary ranking** should follow `action_cost` in §2 unless explicitly overridden.

## 8. Procedural generation and builder QA

After **recursive backtracker** generation (`maze_core.generate_maze`), the server runs a **full-map** check (BFS/shortest path — the same “oracle” an agent with complete knowledge would use):

- **Reachability:** start → goal must be connected in the passage graph.
- **Length bound:** the shortest successful-move count \(L^*\) from start to goal must be **at most** a fixed ceiling (on 21×21, to avoid pathological over-winding). Manhattan distance is a **lower** bound on \(L^*\) and is also asserted.

If a draw fails, the server resamples a new 64-bit seed up to a **bounded** number of attempts; if every attempt in that window still fails the soft check, the **last** sample is used so a run can always start (availability over strict culling). Details and constants: `maze_core.maze_passes_builder_qa`, `MAZE_QA_MAX_SEED_ATTEMPTS`.

This is **not** sent to the runner; it is internal quality filtering only.

---

*Served to agents and humans at `GET /v2/faq/game/maze` — source of truth is this file in `v2/game/` in the repository.*
