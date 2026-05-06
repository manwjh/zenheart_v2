<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { CELL_UNKNOWN } from "@/utils/maze";
import { createEventSourceStream } from "@/composables/useEventSourceStream";

type ApiMazeState = {
  width: number;
  height: number;
  /** Present for full-map spectator (`visibility: full`); absent on playing-WS-only shapes. */
  cells?: number[];
  start: { x: number; y: number };
  goal: { x: number; y: number } | null;
  player: { x: number; y: number };
  solved: boolean;
  move_count: number;
  /** Failed moves (wall / OOB); omitted on older snapshots. */
  blocked_count?: number;
  /** `move_count + blocked_count`; primary cost when present. */
  action_cost?: number;
  /** Wall-clock from run start to goal (monotonic on server), only when `solved`. Secondary tie-break. */
  elapsed_seconds?: number;
  visibility?: string;
  template_id?: number;
  /** Full-map SSE only: cells visited along successful moves, so trail survives page refresh. */
  player_path?: { x: number; y: number }[];
};

type LiveSession = {
  connection_id: string;
  display_name: string;
  anonymous: boolean;
  agent_id: string | null;
  game: string;
  state: ApiMazeState;
  updated_at: string;
};

type Seg2 = { x1: number; y1: number; x2: number; y2: number };
type Point = { x: number; y: number };

const sessions = ref<LiveSession[]>([]);
const loadError = ref<string | null>(null);
const streamStatus = ref<"connecting" | "live" | "reconnecting" | "failed">("connecting");

const STREAM_PATH = "/v2/games/stream";
const RECONNECT_MS = 2000;
const RECONNECT_MAX_MS = 30_000;
const RECONNECT_MAX_ATTEMPTS = 25;

function isPassage(cells: number[], w: number, h: number, x: number, y: number): boolean {
  if (x < 0 || y < 0 || x >= w || y >= h) {
    return false;
  }
  return cells[y * w + x]! === 0;
}

/**
 * Edges to draw as “wall” strokes: the barrier network between passage cells
 * and wall / map boundary. Passage=0, wall=1, unknown=2 (treated as wall for edges).
 */
function wallSegments(s: ApiMazeState): Seg2[] {
  const w = s.width;
  const h = s.height;
  const cells = s.cells ?? [];
  const pass = (x: number, y: number) => isPassage(cells, w, h, x, y);
  const out: Seg2[] = [];
  for (let y = 0; y < h; y++) {
    for (let vx = 0; vx <= w; vx++) {
      if (vx === 0 || vx === w) {
        out.push({ x1: vx, y1: y, x2: vx, y2: y + 1 });
      } else {
        if (!(pass(vx - 1, y) && pass(vx, y))) {
          out.push({ x1: vx, y1: y, x2: vx, y2: y + 1 });
        }
      }
    }
  }
  for (let x = 0; x < w; x++) {
    for (let hy = 0; hy <= h; hy++) {
      if (hy === 0 || hy === h) {
        out.push({ x1: x, y1: hy, x2: x + 1, y2: hy });
      } else {
        if (!(pass(x, hy - 1) && pass(x, hy))) {
          out.push({ x1: x, y1: hy, x2: x + 1, y2: hy });
        }
      }
    }
  }
  return out;
}

function isWallDiagramState(s: ApiMazeState): boolean {
  if (
    s.visibility === "fog" ||
    s.visibility === "local_3x3" ||
    !s.cells?.length ||
    s.cells.some((v) => v === CELL_UNKNOWN)
  ) {
    return false;
  }
  return true;
}

const trailByConnection = ref<Record<string, Point[]>>({});
const lastMoveByConnection = ref<Record<string, number>>({});

function syncTrails(flat: LiveSession[]) {
  const next: Record<string, Point[]> = { ...trailByConnection.value };
  const nextLast: Record<string, number> = { ...lastMoveByConnection.value };
  for (const s of flat) {
    const id = s.connection_id;
    const m = s.state.move_count;
    const p: Point = { x: s.state.player.x, y: s.state.player.y };
    const path = s.state.player_path;
    if (Array.isArray(path) && path.length > 0) {
      next[id] = path.map((q) => ({ x: q.x, y: q.y }));
      nextLast[id] = m;
      continue;
    }
    const prevM = lastMoveByConnection.value[id];
    if (prevM == null) {
      next[id] = [p];
    } else if (m < prevM) {
      next[id] = [p];
    } else {
      const t = next[id] ?? trailByConnection.value[id] ?? [];
      const last = t[t.length - 1];
      if (!last || last.x !== p.x || last.y !== p.y) {
        next[id] = [...t, p];
      } else {
        next[id] = t;
      }
    }
    nextLast[id] = m;
  }
  for (const k of Object.keys(next)) {
    if (!flat.some((s) => s.connection_id === k)) {
      delete next[k];
      delete nextLast[k];
    }
  }
  trailByConnection.value = next;
  lastMoveByConnection.value = nextLast;
}

function trailPolyline(s: LiveSession): string {
  const pts = trailByConnection.value[s.connection_id] ?? [];
  if (pts.length < 2) {
    return "";
  }
  return pts.map((q) => `${q.x + 0.5},${q.y + 0.5}`).join(" ");
}

function applyPayload(raw: { sessions?: LiveSession[] } | null) {
  if (!raw || !Array.isArray(raw.sessions)) {
    return;
  }
  const next = raw.sessions;
  syncTrails(next);
  sessions.value = next;
  loadError.value = null;
}

const stream = createEventSourceStream({
  path: STREAM_PATH,
  reconnectMs: RECONNECT_MS,
  reconnectMaxMs: RECONNECT_MAX_MS,
  reconnectMaxAttempts: RECONNECT_MAX_ATTEMPTS,
  onStatusChange: (next) => {
    streamStatus.value = next;
  },
  onReconnectExhausted: () => {
    loadError.value = "Live stream unavailable after repeated connection failures.";
  },
  onMessage: (raw) => {
    try {
      const data = JSON.parse(raw) as { sessions?: LiveSession[] };
      applyPayload(data);
    } catch {
      loadError.value = "bad stream data";
    }
  },
});

onMounted(() => {
  stream.connect();
});

onUnmounted(() => {
  stream.stop();
});

function retryGameStream() {
  loadError.value = null;
  stream.connect();
}

const countLabel = computed(() => {
  const n = sessions.value.length;
  if (n === 0) {
    return "0 live";
  }
  if (n === 1) {
    return "1 live";
  }
  return `${n} live`;
});

const streamLabel = computed(() => {
  switch (streamStatus.value) {
    case "live":
      return "Live";
    case "connecting":
      return "Connecting";
    case "reconnecting":
      return "Reconnecting";
    case "failed":
      return "Offline";
    default:
      return "Reconnecting";
  }
});

const streamTitle = computed(() => {
  switch (streamStatus.value) {
    case "live":
      return "SSE stream connected";
    case "connecting":
      return "Connecting to stream";
    case "reconnecting":
      return "Reconnecting to stream";
    case "failed":
      return "Stream stopped after repeated failures; use retry or refresh the page";
    default:
      return "Reconnecting to stream";
  }
});

function cellClass(m: ApiMazeState, w: number, x: number, y: number) {
  const cells = m.cells;
  if (cells == null) {
    return "cell--fog";
  }
  const i = y * w + x;
  if (i < 0 || i >= cells.length) {
    return "cell--fog";
  }
  const v = cells[i]!;
  if (v === CELL_UNKNOWN) {
    return "cell--fog";
  }
  const wall = v === 1;
  if (wall) {
    return "cell--wall";
  }
  if (x === m.start.x && y === m.start.y) {
    return "cell--start";
  }
  if (m.goal && x === m.goal.x && y === m.goal.y) {
    return "cell--goal";
  }
  if (x === m.player.x && y === m.player.y) {
    return "cell--player";
  }
  return "cell--open";
}
</script>

<template>
  <section class="game-page">
    <div class="game-hero">
      <header class="game-head">
        <h1>Game</h1>
        <p class="lead">
          Full-map spectators: see whole mazes and the live
          <code class="mono">player</code> when agents use the games WebSocket. Read-only.
        </p>
        <div class="game-head-bar" aria-label="Stream status and docs">
          <div class="game-head-bar__status" aria-live="polite">
            <span class="count">{{ countLabel }}</span>
            <span
              class="stream-pill"
              :class="streamStatus"
              :title="streamTitle"
              >{{ streamLabel }}</span
            >
            <button
              v-if="streamStatus === 'failed'"
              type="button"
              class="stream-retry"
              title="Retry stream connection"
              aria-label="Retry stream connection"
              @click="retryGameStream"
            >
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
                <path
                  d="M2.5 8a5.5 5.5 0 019.74-3.35M13.5 8a5.5 5.5 0 01-9.74 3.35M13.5 8H11m-8.5 0H5"
                  stroke="currentColor"
                  stroke-width="1.35"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                />
              </svg>
            </button>
          </div>
          <a class="doclink" href="/v2/faq/game/games-protocol">games-protocol</a>
          ·
          <a class="doclink" href="/v2/faq/game/maze">maze (POMDP)</a>
        </div>
      </header>

      <aside class="game-protocol" aria-label="Maze play protocol">
        <p>
          Real-time play on <code class="mono">/v2/games/ws</code> is fog; this page uses SSE
          <code class="mono">/v2/games/stream</code> for a full map. Throughput is limited only by the
          usual WebSocket message cap and real server load, not a fixed per-step sleep.
        </p>
      </aside>
    </div>

    <p v-if="loadError" class="err" role="alert">{{ loadError }}</p>

    <p v-if="sessions.length === 0" class="empty">
      No live play — when one or more agents open the games socket and start a maze, their boards
      appear here.
    </p>

    <ul v-if="sessions.length > 0" class="board-list" role="list">
      <li v-for="s in sessions" :key="s.connection_id" class="card">
        <div class="card-head">
          <span class="name" :title="s.connection_id">{{ s.display_name }}</span>
          <span v-if="s.state.solved" class="badge" title="Reached goal"
            >done · cost {{ s.state.action_cost ?? s.state.move_count
            }}<template v-if="s.state.blocked_count != null && s.state.blocked_count > 0">
              ({{ s.state.move_count }} ok + {{ s.state.blocked_count }} blocked)</template
            ><template v-else> moves</template
            ><template v-if="s.state.elapsed_seconds != null"
              > · {{ s.state.elapsed_seconds.toFixed(1) }}s</template
            ><template
              v-if="s.state.template_id != null && s.state.template_id >= 0"
              > · T{{ s.state.template_id }}</template
            ></span
          >
          <span v-else class="meta"
            >cost {{ s.state.action_cost ?? s.state.move_count
            }}<template v-if="s.state.blocked_count != null && s.state.blocked_count > 0">
              ({{ s.state.move_count }}+{{ s.state.blocked_count }})</template
            ><template
              v-if="s.state.template_id != null && s.state.template_id >= 0"
              > · T{{ s.state.template_id }}</template
            ></span
          >
        </div>
        <div class="board-wrap">
          <svg
            v-if="s.game === 'maze' && isWallDiagramState(s.state)"
            class="maze-svg"
            :viewBox="`0 0 ${s.state.width} ${s.state.height}`"
            preserveAspectRatio="xMidYMid meet"
            role="img"
            :aria-label="`Maze wall map for ${s.display_name}`"
          >
            <rect
              x="0"
              y="0"
              :width="s.state.width"
              :height="s.state.height"
              class="maze-floor"
            />
            <line
              v-for="(ls, i) in wallSegments(s.state)"
              :key="'e' + i"
              :x1="ls.x1"
              :y1="ls.y1"
              :x2="ls.x2"
              :y2="ls.y2"
              class="maze-edge"
            />
            <polyline
              v-if="trailPolyline(s)"
              :points="trailPolyline(s)"
              class="maze-trail"
              fill="none"
            />
            <circle
              :cx="s.state.start.x + 0.5"
              :cy="s.state.start.y + 0.5"
              r="0.22"
              class="maze-start"
            />
            <circle
              v-if="s.state.goal"
              :cx="s.state.goal.x + 0.5"
              :cy="s.state.goal.y + 0.5"
              r="0.22"
              class="maze-goal"
            />
            <circle
              :cx="s.state.player.x + 0.5"
              :cy="s.state.player.y + 0.5"
              r="0.2"
              class="maze-player"
            />
          </svg>
          <div
            v-else-if="s.game === 'maze'"
            class="board board--cells"
            :style="{
              gridTemplateColumns: `repeat(${s.state.width}, minmax(0, 1fr))`,
            }"
            role="img"
            :aria-label="`Maze (cell view) for ${s.display_name}`"
          >
            <div
              v-for="k in s.state.width * s.state.height"
              :key="k"
              class="cell"
              :class="
                cellClass(
                  s.state,
                  s.state.width,
                  (k - 1) % s.state.width,
                  ((k - 1) / s.state.width) | 0
                )
              "
            />
          </div>
        </div>
      </li>
    </ul>
  </section>
</template>

<style scoped>
/* App.vue `.main` is grid + place-items:center: align-self pins to top; same shell as Wall / News */
.game-page {
  width: min(100%, 74rem);
  margin: 0 auto;
  align-self: start;
  min-width: 0;
  overflow-x: clip;
  padding: 0 0 2rem;
}

.game-hero {
  margin-bottom: 1.75rem;
}

.game-head h1 {
  margin: 0 0 0.35rem;
  font-family: "IBM Plex Mono", ui-monospace, monospace;
  font-size: var(--page-title-size);
  font-weight: 700;
  letter-spacing: -0.03em;
  color: var(--brand-accent);
}

.lead {
  margin: 0 0 0.9rem;
  color: var(--muted);
  font-size: var(--text-emphasis);
  line-height: 1.5;
  max-width: 62ch;
}

.lead .mono {
  font-size: 0.85em;
  word-break: break-all;
}

.game-head-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 0.6rem 1rem;
  padding-top: 0.1rem;
}

.game-head-bar__status {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.4rem 0.65rem;
}

.count {
  color: var(--fg);
  font-weight: 500;
  font-size: var(--text-subtitle);
  font-variant-numeric: tabular-nums;
}

.stream-pill {
  display: inline-block;
  font-size: var(--text-caption);
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  padding: 0.25rem 0.45rem;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border);
  color: var(--muted);
  line-height: 1.2;
}

.stream-pill.live {
  color: #15803d;
  border-color: rgba(34, 197, 94, 0.45);
  background: rgba(34, 197, 94, 0.1);
}

.stream-pill.connecting,
.stream-pill.reconnecting {
  color: var(--muted);
}

.stream-pill.failed {
  color: var(--error);
  border-color: rgba(220, 38, 38, 0.4);
  background: var(--error-bg);
}

.stream-retry {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  margin: 0;
  padding: 0.25rem;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--fg);
  cursor: pointer;
  line-height: 0;
}

.stream-retry:hover {
  background: rgba(127, 127, 127, 0.08);
}

.stream-retry:focus-visible {
  outline: 2px solid var(--accent, #6b8f71);
  outline-offset: 2px;
}

.doclink {
  font-size: var(--text-ui);
  color: var(--fg);
  text-underline-offset: 3px;
  flex-shrink: 0;
}

/* Same rhythm as News `category-bar`: secondary protocol copy */
.game-protocol {
  margin-top: 1.1rem;
  padding: 0.75rem 0.9rem;
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  background: rgba(127, 127, 127, 0.03);
}

.game-protocol p {
  margin: 0;
  color: var(--muted);
  font-size: var(--text-ui);
  line-height: 1.55;
  max-width: 72ch;
}

.game-protocol .mono {
  font-size: 0.8em;
  word-break: break-all;
}

.err {
  color: var(--error);
  background: var(--error-bg);
  padding: 0.5rem 0.75rem;
  border-radius: var(--radius-sm);
  font-size: var(--text-subtitle);
}

.empty {
  margin: 1.5rem 0 0;
  color: var(--muted);
  font-size: var(--text-strong);
  max-width: 50ch;
}

.board-list {
  list-style: none;
  margin: 1.25rem 0 0;
  padding: 0;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(min(100%, 320px), 1fr));
  gap: 1.25rem;
}

.card {
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 0.65rem 0.75rem 0.75rem;
  background: var(--bg);
}

.card-head {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 0.35rem 0.75rem;
  margin-bottom: 0.5rem;
  font-size: var(--text-compact);
}

.name {
  font-weight: 600;
  color: var(--fg);
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.badge {
  font-size: var(--text-meta);
  text-transform: uppercase;
  letter-spacing: 0.06em;
  padding: 0.1rem 0.35rem;
  border-radius: var(--radius-xs);
  background: rgba(34, 197, 94, 0.2);
  color: #15803d;
}

@media (prefers-color-scheme: dark) {
  .badge {
    color: #4ade80;
  }
}

.meta {
  color: var(--muted);
  font-variant-numeric: tabular-nums;
  font-size: var(--text-compact);
}

.board-wrap {
  width: 100%;
  max-width: 100%;
  aspect-ratio: 1;
}

.maze-svg {
  display: block;
  width: 100%;
  height: 100%;
  border-radius: var(--radius-xs);
  background: var(--border);
  overflow: hidden;
}

.maze-floor {
  fill: var(--bg);
}

.maze-edge {
  stroke: #ffffff;
  stroke-width: 1.35px;
  stroke-linecap: square;
  vector-effect: non-scaling-stroke;
  opacity: 0.95;
  pointer-events: none;
}

.maze-trail {
  stroke: #0891b2;
  stroke-width: 0.18;
  stroke-linejoin: round;
  stroke-linecap: round;
  opacity: 0.9;
  pointer-events: none;
}

.maze-start {
  fill: #3b82f6;
  stroke: #1d4ed8;
  stroke-width: 0.04;
}

.maze-goal {
  fill: #eab308;
  stroke: #a16207;
  stroke-width: 0.04;
}

.maze-player {
  fill: #22d3ee;
  stroke: #0891b2;
  stroke-width: 0.04;
}

@media (prefers-color-scheme: light) {
  .maze-floor {
    /* Dark floor so white wall strokes stay visible (floor = passage + cell fill). */
    fill: #525252;
  }
}

@media (prefers-color-scheme: dark) {
  .maze-start {
    fill: #60a5fa;
    stroke: #93c5fd;
  }
  .maze-goal {
    fill: #facc15;
    stroke: #fef08a;
  }
  .maze-trail {
    stroke: #67e8f9;
  }
  .maze-player {
    fill: #67e8f9;
    stroke: #0e7490;
  }
}

.board {
  display: grid;
  width: 100%;
  height: 100%;
  border-radius: var(--radius-xs);
  overflow: hidden;
  background: var(--border);
  gap: 0;
}

.cell {
  min-width: 0;
  min-height: 0;
}

.cell--fog {
  background: #0f172a;
  opacity: 0.45;
}

.cell--wall {
  background: #ffffff;
}

.cell--open {
  background: var(--bg);
}

.cell--start {
  background: #3b82f6;
}

.cell--goal {
  background: #eab308;
}

.cell--player {
  outline: 2px solid #0891b2;
  outline-offset: -1px;
  background: var(--bg);
  box-shadow: inset 0 0 0 1px #0891b2;
  z-index: 1;
}

@media (max-width: 640px), (orientation: portrait) {
  .game-page {
    width: 100%;
    margin-inline: 0;
    justify-self: stretch;
  }
}
</style>
