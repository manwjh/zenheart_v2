/**
 * Odd-sized grid: 1 = wall, 0 = passage. Carved with recursive backtracker.
 * Start (1,1), goal (w-2, h-2). Single fixed grid size (debug / v1 product).
 */

const MAZE_WIDTH = 21;
const MAZE_HEIGHT = 21;

const DIRS: ReadonlyArray<readonly [number, number]> = [
  [0, -2],
  [0, 2],
  [-2, 0],
  [2, 0],
];

export type MazeGrid = {
  cells: Uint8Array;
  width: number;
  height: number;
  start: { x: number; y: number };
  goal: { x: number; y: number };
};

function shuffleInPlace(rng: () => number, order: number[]): void {
  for (let i = order.length - 1; i > 0; i--) {
    const j = Math.floor(rng() * (i + 1));
    const t = order[i]!;
    order[i] = order[j]!;
    order[j] = t;
  }
}

function idx(w: number, x: number, y: number): number {
  return y * w + x;
}

function carve(
  w: number,
  h: number,
  cells: Uint8Array,
  x: number,
  y: number,
  rng: () => number
): void {
  cells[idx(w, x, y)] = 0;
  const order = [0, 1, 2, 3];
  shuffleInPlace(rng, order);
  for (const d of order) {
    const [dx, dy] = DIRS[d]!;
    const nx = x + dx;
    const ny = y + dy;
    if (nx < 0 || ny < 0 || nx >= w || ny >= h) {
      continue;
    }
    if (cells[idx(w, nx, ny)] !== 1) {
      continue;
    }
    const mx = x + dx / 2;
    const my = y + dy / 2;
    cells[idx(w, mx, my)] = 0;
    carve(w, h, cells, nx, ny, rng);
  }
}

export function generateMaze(rng: () => number = Math.random): MazeGrid {
  const w = MAZE_WIDTH;
  const h = MAZE_HEIGHT;
  const cells = new Uint8Array(w * h);
  cells.fill(1);
  carve(w, h, cells, 1, 1, rng);
  const start = { x: 1, y: 1 };
  const goal = { x: w - 2, y: h - 2 };
  cells[idx(w, goal.x, goal.y)] = 0;
  return { cells, width: w, height: h, start, goal };
}

export type ShortestPathResult = {
  length: number;
  path: ReadonlyArray<readonly [number, number]>;
  reachable: boolean;
};

const STEP_DIRS: ReadonlyArray<readonly [number, number]> = [
  [0, -1],
  [0, 1],
  [-1, 0],
  [1, 0],
];

/**
 * 4-neighbor BFS on passage cells; returns one shortest path (including start and goal).
 */
export function shortestPath(maze: MazeGrid): ShortestPathResult {
  const { cells, width: w, height: h, start, goal } = maze;
  const sKey = idx(w, start.x, start.y);
  const gKey = idx(w, goal.x, goal.y);
  const dist = new Int32Array(w * h);
  dist.fill(-1);
  const prev = new Int32Array(w * h);
  prev.fill(-1);
  const q: number[] = [sKey];
  dist[sKey] = 0;

  let qi = 0;
  while (qi < q.length) {
    const cur = q[qi]!;
    qi++;
    if (cur === gKey) {
      break;
    }
    const cx = cur % w;
    const cy = (cur / w) | 0;
    for (const [dx, dy] of STEP_DIRS) {
      const nx = cx + dx;
      const ny = cy + dy;
      if (nx < 0 || ny < 0 || nx >= w || ny >= h) {
        continue;
      }
      const n = idx(w, nx, ny);
      if (cells[n] !== 0) {
        continue;
      }
      if (dist[n] !== -1) {
        continue;
      }
      dist[n] = dist[cur]! + 1;
      prev[n] = cur;
      q.push(n);
    }
  }

  if (dist[gKey] === -1) {
    return { length: 0, path: [], reachable: false };
  }

  const out: [number, number][] = [];
  let p = gKey;
  for (;;) {
    const x = p % w;
    const y = (p / w) | 0;
    out.push([x, y]);
    if (p === sKey) {
      break;
    }
    p = prev[p]!;
  }
  out.reverse();
  return { length: out.length, path: out, reachable: true };
}

export const MAZE_GRID_SIZE = { w: MAZE_WIDTH, h: MAZE_HEIGHT } as const;

/** Wire value for unrevealed cells in fog mode (game_state only). */
export const CELL_UNKNOWN = 2;

/** True when the spectator page may draw a shortest-path hint (full map known). */
export function mazeStateAllowsPathHint(s: {
  visibility?: string;
  goal: { x: number; y: number } | null;
}): boolean {
  if (s.visibility === "fog" || s.visibility === "local_3x3") {
    return false;
  }
  return s.goal != null;
}

/** Map server /v2/games/active maze state to a local grid (spectator / mirror). */
export function mazeGridFromServerState(s: {
  width: number;
  height: number;
  cells: number[];
  start: { x: number; y: number };
  goal: { x: number; y: number };
}): MazeGrid {
  return {
    width: s.width,
    height: s.height,
    cells: new Uint8Array(s.cells),
    start: s.start,
    goal: s.goal,
  };
}
