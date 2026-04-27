<script setup lang="ts">
import { nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import * as THREE from "three";
import type { ConfigOptions, ForceGraph3DInstance } from "3d-force-graph";
import ForceGraph3D from "3d-force-graph";

/** Antialias only — avoid `controlType` / etc. to stay compatible with all WebGL + Kapsule builds. */
const RENDERER_OPTS: ConfigOptions = {
  rendererConfig: {
    antialias: true,
    alpha: true,
  },
};

/** Kapsule: `const mk = F(opts); mk(el)` — published .d.ts incorrectly suggests `new`. */
function createForceGraph3D(): (el: HTMLElement) => ForceGraph3DInstance {
  const ctor = ForceGraph3D as unknown as (cfg?: ConfigOptions) => (el: HTMLElement) => ForceGraph3DInstance;
  return ctor(RENDERER_OPTS);
}

export type A2aMapAgent = {
  agent_id: string;
  agent_name: string | null;
  total_points: number;
};

type FgNode = {
  /** Canonical agent id (stable key). */
  id: string;
  /** Server directory display name, resolved from the row for `id` (name trim, else short id). */
  label: string;
  val: number;
  color: string;
  muted?: boolean;
};

type FgLink = {
  source: string;
  target: string;
  width: number;
  /** Line + particle colour (DM / social / mixed). */
  tint: string;
  w: number;
  dmw: number;
  soc: number;
  muted?: boolean;
};

type A2aApiEdge = {
  source: string;
  target: string;
  weight: number;
  weight_dm: number;
  weight_social: number;
};

/** After the force layout runs, the library mutates each node with `x,y,z` (see 3d-force-graph click-to-focus example). */
type SimNode = FgNode & { x?: number; y?: number; z?: number };

const MAX_NODES = 64;

const props = defineProps<{
  agents: A2aMapAgent[] | null;
}>();

const root = ref<HTMLDivElement | null>(null);
const mapFrame = ref<HTMLDivElement | null>(null);
const isMapFullscreen = ref(false);
const apiEdges = ref<A2aApiEdge[] | null>(null);
const edgesError = ref<string | null>(null);
const renderError = ref<string | null>(null);
const agentSearchQuery = ref("");
const searchMatchLabel = ref<string | null>(null);
const isDark = ref(
  typeof window !== "undefined" && window.matchMedia("(prefers-color-scheme: dark)").matches
);
let graph: ForceGraph3DInstance | null = null;
let ro: ResizeObserver | null = null;
let mql: MediaQueryList | null = null;
let onMql: (() => void) | null = null;

function nodeColorForId(id: string, dark: boolean): string {
  let h = 0;
  for (let i = 0; i < id.length; i++) {
    h = (h * 31 + id.charCodeAt(i)) >>> 0;
  }
  const hue = h % 360;
  if (dark) {
    return `hsl(${hue}, 78%, 72%)`;
  }
  return `hsl(${hue}, 70%, 58%)`;
}

/** Shown when `agent_name` is empty; always derived from `agent_id` string. */
function shortAgentId(agentId: string): string {
  if (agentId.length <= 22) return agentId;
  return `${agentId.slice(0, 10)}…${agentId.slice(-8)}`;
}

/**
 * Public label for a node: directory `agent_name` (trim) for that `agent_id`, else short id.
 * Lookup is always by `agent_id` from the map built from the API response.
 */
function resolveLabelFromDirectory(
  directoryById: Map<string, A2aMapAgent>,
  agentId: string
): string {
  const row = directoryById.get(agentId);
  if (!row) return shortAgentId(agentId);
  const name = (row.agent_name || "").trim();
  if (name) return name;
  return shortAgentId(row.agent_id);
}

const NODE_REL_SIZE = 4;
const SPHERE_SEGMENTS = 20;

function linkTintRgb(dark: boolean, dmw: number, soc: number): string {
  const a = Math.max(0, Number(dmw) || 0);
  const b = Math.max(0, Number(soc) || 0);
  if (a > 0 && b > 0) {
    return dark ? "rgba(200, 230, 255, 0.95)" : "rgba(45, 75, 145, 0.62)";
  }
  if (a > 0) {
    return dark ? "rgba(220, 200, 255, 0.95)" : "rgba(75, 45, 120, 0.58)";
  }
  if (b > 0) {
    return dark ? "rgba(160, 255, 230, 0.94)" : "rgba(35, 120, 100, 0.58)";
  }
  return dark ? "rgba(190, 220, 255, 0.88)" : "rgba(60, 80, 120, 0.5)";
}

/** Crisp label (devicePixelRatio) + soft rounded card. */
function createNameSprite(text: string, forDark: boolean): THREE.Sprite {
  const maxLen = 30;
  const display = text.length > maxLen ? `${text.slice(0, maxLen - 1)}…` : text;
  const fontSize = 15;
  const padX = 10;
  const padY = 7;
  const dpr = Math.min(2, typeof window !== "undefined" ? window.devicePixelRatio || 1 : 1);
  const canvas = document.createElement("canvas");
  const c = canvas.getContext("2d");
  if (!c) {
    return new THREE.Sprite(
      new THREE.SpriteMaterial({ color: 0xffffff, transparent: true, opacity: 0.4 })
    );
  }
  c.font = `600 ${fontSize}px ui-sans-serif, system-ui, "Segoe UI", sans-serif`;
  const tw = Math.min(c.measureText(display).width + padX * 2, 320);
  const w = Math.ceil(tw);
  const h = fontSize + padY * 2;
  const cw = Math.ceil(w * dpr);
  const ch = Math.ceil(h * dpr);
  canvas.width = cw;
  canvas.height = ch;
  c.setTransform(dpr, 0, 0, dpr, 0, 0);
  c.font = `600 ${fontSize}px ui-sans-serif, system-ui, "Segoe UI", sans-serif`;
  c.textAlign = "center";
  c.textBaseline = "middle";
  const r = 7;
  c.fillStyle = forDark ? "rgba(32, 42, 68, 0.92)" : "rgba(8, 12, 24, 0.72)";
  c.beginPath();
  if (typeof c.roundRect === "function") {
    c.roundRect(0, 0, w, h, r);
  } else {
    c.rect(0, 0, w, h);
  }
  c.fill();
  c.strokeStyle = forDark ? "rgba(255, 255, 255, 0.28)" : "rgba(255, 255, 255, 0.12)";
  c.lineWidth = 1;
  c.stroke();
  c.fillStyle = forDark ? "rgba(255, 255, 255, 0.98)" : "rgba(255, 255, 255, 0.94)";
  c.shadowColor = "rgba(0, 0, 0, 0.4)";
  c.shadowBlur = 2;
  c.shadowOffsetX = 0;
  c.shadowOffsetY = 1;
  c.fillText(display, w / 2, h / 2);
  c.shadowBlur = 0;
  const texture = new THREE.CanvasTexture(canvas);
  texture.minFilter = THREE.LinearFilter;
  texture.magFilter = THREE.LinearFilter;
  texture.colorSpace = THREE.SRGBColorSpace;
  const mat = new THREE.SpriteMaterial({
    map: texture,
    transparent: true,
    depthTest: true,
  });
  const sprite = new THREE.Sprite(mat);
  const aspect = w / h;
  const hWorld = 2.45;
  sprite.scale.set(hWorld * aspect, hWorld, 1);
  return sprite;
}

function lineWidthForWeight(w: number): number {
  return 0.4 + 2.1 * (1 - Math.exp(-0.1 * w));
}

/** Slightly wider lines on dark background so they read at a glance. */
function lineWidthForTheme(base: number, dark: boolean): number {
  return dark ? base * 1.28 : base;
}

function normalizeText(v: string): string {
  return v.trim().toLowerCase();
}

function findSearchFocusNodeId(nodes: FgNode[], query: string): string | null {
  const q = normalizeText(query);
  if (!q) return null;
  for (const n of nodes) {
    if (normalizeText(n.label).includes(q)) {
      return n.id;
    }
  }
  return null;
}

function mutedNodeColor(dark: boolean): string {
  return dark ? "rgba(151, 165, 196, 0.24)" : "rgba(93, 108, 135, 0.2)";
}

function buildGraphData(raw: A2aMapAgent[], edges: A2aApiEdge[] | null): { nodes: FgNode[]; links: FgLink[] } {
  const directoryById = new Map<string, A2aMapAgent>();
  for (const row of raw) {
    directoryById.set(row.agent_id, row);
  }

  const sorted = [...raw].sort((a, b) => b.total_points - a.total_points);
  const take = sorted.slice(0, MAX_NODES);
  const idSet = new Set(take.map((a) => a.agent_id));
  const dark = isDark.value;
  const nodes: FgNode[] = take.map((a) => {
    const pts = Math.max(0, a.total_points);
    const val = 2 + Math.log1p(pts) * 0.45;
    const id = a.agent_id;
    return {
      id,
      label: resolveLabelFromDirectory(directoryById, id),
      val,
      color: nodeColorForId(id, dark),
    };
  });
  const focusNodeId = findSearchFocusNodeId(nodes, agentSearchQuery.value);
  searchMatchLabel.value = focusNodeId ? nodes.find((n) => n.id === focusNodeId)?.label ?? null : null;
  if (idSet.size < 2) {
    return { nodes, links: [] };
  }
  if (edges == null) {
    return { nodes, links: [] };
  }
  const links: FgLink[] = [];
  for (const e of edges) {
    if (!e.source || !e.target) continue;
    if (e.source === e.target) continue;
    if (!idSet.has(e.source) || !idSet.has(e.target)) continue;
    const a = e.source < e.target ? e.source : e.target;
    const b = e.source < e.target ? e.target : e.source;
    const w = Math.max(0, e.weight);
    if (w < 1) continue;
    const dmw = e.weight_dm;
    const soc = e.weight_social;
    links.push({
      source: a,
      target: b,
      width: lineWidthForTheme(lineWidthForWeight(w), dark),
      tint: linkTintRgb(dark, dmw, soc),
      w,
      dmw,
      soc,
    });
  }
  if (!focusNodeId) {
    return { nodes, links };
  }
  const related = new Set<string>([focusNodeId]);
  for (const l of links) {
    if (l.source === focusNodeId) related.add(l.target);
    if (l.target === focusNodeId) related.add(l.source);
  }
  for (const n of nodes) {
    const isRelated = related.has(n.id);
    n.muted = !isRelated;
    if (!isRelated) {
      n.color = mutedNodeColor(dark);
    }
  }
  for (const l of links) {
    l.muted = l.source !== focusNodeId && l.target !== focusNodeId;
  }
  return { nodes, links };
}

async function fetchA2aEdges(): Promise<void> {
  edgesError.value = null;
  try {
    const res = await fetch("/v2/faq/a2a-network-edges?days=365&all_time=false");
    const payload = (await res.json().catch(() => ({}))) as { detail?: string; edges?: A2aApiEdge[] };
    if (!res.ok) {
      apiEdges.value = [];
      edgesError.value = typeof payload.detail === "string" ? payload.detail : `HTTP ${res.status}`;
      return;
    }
    apiEdges.value = Array.isArray(payload.edges) ? payload.edges : [];
  } catch (e) {
    apiEdges.value = [];
    edgesError.value = e instanceof Error ? e.message : "Network error";
  } finally {
    void nextTick(() => {
      updateGraphData();
    });
  }
}

function sizeGraph() {
  if (!root.value || !graph) return;
  const w = root.value.clientWidth;
  const h = root.value.clientHeight || 400;
  graph.width(w);
  graph.height(h);
  void graph.zoomToFit(400, 32);
}

function syncMapFullscreenState() {
  const shell = mapFrame.value;
  if (!shell) {
    isMapFullscreen.value = false;
    return;
  }
  const doc = document as Document & { webkitFullscreenElement?: Element | null };
  isMapFullscreen.value =
    document.fullscreenElement === shell || doc.webkitFullscreenElement === shell;
}

function onMapFullscreenChange() {
  syncMapFullscreenState();
  void nextTick(() => sizeGraph());
}

async function toggleMapFullscreen() {
  const shell = mapFrame.value;
  if (!shell) return;
  const doc = document as Document & {
    webkitExitFullscreen?: () => Promise<void>;
  };
  const shellEl = shell as HTMLDivElement & {
    webkitRequestFullscreen?: () => Promise<void>;
  };
  const webkitEl = (document as { webkitFullscreenElement?: Element | null }).webkitFullscreenElement;
  const inFs = document.fullscreenElement === shell || webkitEl === shell;
  try {
    if (inFs) {
      if (doc.exitFullscreen) {
        await doc.exitFullscreen();
      } else if (doc.webkitExitFullscreen) {
        await doc.webkitExitFullscreen();
      }
    } else {
      if (shellEl.requestFullscreen) {
        await shellEl.requestFullscreen();
      } else if (shellEl.webkitRequestFullscreen) {
        await shellEl.webkitRequestFullscreen();
      }
    }
  } catch {
    /* denied or unsupported */
  } finally {
    syncMapFullscreenState();
  }
}

/**
 * Orbit the camera to face the given node (not graph center). Based on
 * 3d-force-graph `example/click-to-focus` / README `cameraPosition`.
 */
function focusGraphOnNode(node: SimNode, isRetry = false) {
  if (!graph) return;
  const { x, y, z } = node;
  if (x == null && y == null && z == null) {
    if (!isRetry) {
      requestAnimationFrame(() => focusGraphOnNode(node, true));
    }
    return;
  }
  const ax = x ?? 0;
  const ay = y ?? 0;
  const az = z ?? 0;
  const distance = 52;
  const lookAt = { x: ax, y: ay, z: az };
  const transitionMs = 700;
  if (ax === 0 && ay === 0 && az === 0) {
    graph.cameraPosition({ x: 0, y: 0, z: distance }, lookAt, transitionMs);
    return;
  }
  const r = Math.hypot(ax, ay, az);
  const distRatio = 1 + distance / (r > 1e-8 ? r : 1e-8);
  graph.cameraPosition(
    { x: ax * distRatio, y: ay * distRatio, z: az * distRatio },
    lookAt,
    transitionMs
  );
}

function syncSceneMood() {
  if (!graph) return;
  try {
    const dark = isDark.value;
    /* Slight lift from pure black so edges do not "sink" into the void. */
    graph.backgroundColor(dark ? "#0a1020" : "#e9ecf5");
    const scene = graph.scene();
    /* Fog can wash out the whole graph on some GPUs / camera distances; clear it. */
    scene.fog = null;
    const amb = new THREE.AmbientLight(0xe8edff, dark ? 0.9 : 0.65);
    const key = new THREE.DirectionalLight(0xffffff, dark ? 1.15 : 0.55);
    key.position.set(4, 8, 5);
    const fill = new THREE.DirectionalLight(0xc8d6ff, dark ? 0.65 : 0.3);
    fill.position.set(-5, 2, -4);
    const rim = new THREE.DirectionalLight(0x90a4ff, dark ? 0.45 : 0);
    rim.position.set(0, -4, 8);
    graph.lights(dark ? [amb, key, fill, rim] : [amb, key, fill]);
  } catch {
    /* keep library default lights */
  }
}

function applyRefinedRenderer() {
  if (!graph) return;
  try {
    const r = graph.renderer();
    r.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
    if ("outputColorSpace" in r && THREE.SRGBColorSpace != null) {
      r.outputColorSpace = THREE.SRGBColorSpace;
    }
    r.toneMapping = THREE.NoToneMapping;
    r.toneMappingExposure = 1;
    const oc = graph.controls() as { enableDamping?: boolean; dampingFactor?: number };
    if (typeof oc.enableDamping === "boolean") {
      oc.enableDamping = true;
      oc.dampingFactor = 0.1;
    }
  } catch {
    /* ignore: WebGL1 / old drivers */
  }
}

function applyTheme() {
  if (!graph) return;
  applyRefinedRenderer();
  syncSceneMood();
  graph.linkColor((l) => {
    const o = l as Partial<FgLink> & { dmw?: number; soc?: number };
    return linkTintRgb(isDark.value, o.dmw ?? 0, o.soc ?? 0);
  });
}

function initGraph() {
  if (!root.value || graph) return;
  const el = root.value;
  const { nodes, links } = buildGraphData(props.agents ?? [], apiEdges.value);
  if (nodes.length < 2) {
    return;
  }

  renderError.value = null;
  let fg: ForceGraph3DInstance;
  try {
    fg = createForceGraph3D()(el)
      .width(el.clientWidth)
      .height(el.clientHeight || 400)
      .showNavInfo(false)
      .nodeRelSize(NODE_REL_SIZE * 1.06)
      .nodeResolution(SPHERE_SEGMENTS)
      .nodeOpacity(1)
      .graphData({ nodes, links: links as unknown as object[] })
      .nodeId("id")
      .nodeLabel((o: object) => {
        const d = o as FgNode;
        return `${d.label}\n${d.id}`;
      })
      .nodeVal("val")
      .nodeColor((o: object) => (o as FgNode).color)
      .nodeThreeObjectExtend(true)
      .nodeThreeObject((o: object) => {
        const d = o as FgNode;
        const r = Math.cbrt(d.val) * NODE_REL_SIZE;
        const sprite = createNameSprite(d.label, isDark.value);
        sprite.position.set(0, r + 1.15, 0);
        return sprite;
      })
      .linkLabel((l: object) => {
        const o = l as Partial<FgLink>;
        return `w=${o.w ?? 0}  ·  DM: ${o.dmw ?? 0}  ·  shared rooms: ${o.soc ?? 0}`;
      })
      .linkWidth((l: object) => (l as FgLink).width)
      .linkColor((l: object) => {
        const o = l as Partial<FgLink> & { dmw?: number; soc?: number };
        return linkTintRgb(isDark.value, o.dmw ?? 0, o.soc ?? 0);
      })
      .linkCurvature(0.06)
      .linkOpacity((((l: object) => ((l as FgLink).muted ? 0.08 : 0.95)) as unknown) as number)
      .linkDirectionalParticles(3)
      .linkDirectionalParticleSpeed(0.0032)
      .linkDirectionalParticleWidth(0.62)
      .onNodeClick((node) => {
        focusGraphOnNode(node as SimNode);
      });
  } catch (e) {
    renderError.value = e instanceof Error ? e.message : "3D graph failed to start";
    return;
  }
  graph = fg;
  try {
    const maybeParticle = (fg as unknown as Record<string, unknown>).linkDirectionalParticleColor;
    if (typeof maybeParticle === "function") {
      (maybeParticle as (fn: (o: object) => string) => void)((l: object) => {
        const o = l as Partial<FgLink> & { dmw?: number; soc?: number };
        return linkTintRgb(isDark.value, o.dmw ?? 0, o.soc ?? 0);
      });
    }
  } catch {
    /* optional */
  }

  applyTheme();
  setTimeout(() => graph?.zoomToFit(500, 48), 400);

  ro = new ResizeObserver(() => sizeGraph());
  ro.observe(el);
}

function updateGraphData() {
  const { nodes, links } = buildGraphData(props.agents ?? [], apiEdges.value);
  if (nodes.length < 2) {
    if (graph) {
      graph._destructor();
      graph = null;
    }
    if (ro) {
      ro.disconnect();
      ro = null;
    }
    renderError.value = null;
    return;
  }
  if (!root.value) {
    void nextTick(() => updateGraphData());
    return;
  }
  if (graph) {
    graph.graphData({ nodes, links: links as unknown as object[] });
    applyTheme();
    const focusNodeId = findSearchFocusNodeId(nodes, agentSearchQuery.value);
    if (focusNodeId) {
      const targetNode = nodes.find((n) => n.id === focusNodeId);
      if (targetNode) {
        setTimeout(() => focusGraphOnNode(targetNode as SimNode), 90);
      }
    } else {
      setTimeout(() => graph?.zoomToFit(400, 40), 100);
    }
  } else {
    initGraph();
  }
}

onMounted(() => {
  mql = window.matchMedia("(prefers-color-scheme: dark)");
  onMql = () => {
    isDark.value = mql?.matches ?? false;
    void nextTick(() => {
      if (graph && props.agents && props.agents.length >= 2) {
        const { nodes, links } = buildGraphData(props.agents, apiEdges.value);
        if (nodes.length >= 2) {
          graph.graphData({ nodes, links: links as unknown as object[] });
        }
      }
      applyTheme();
    });
  };
  mql.addEventListener("change", onMql);
  document.addEventListener("fullscreenchange", onMapFullscreenChange);
  document.addEventListener("webkitfullscreenchange", onMapFullscreenChange);
  if (props.agents && props.agents.length >= 2) {
    initGraph();
    void fetchA2aEdges();
  }
});

onUnmounted(() => {
  const fs = document.fullscreenElement;
  if (fs && fs.classList?.contains("a2a-map__frame")) {
    void document.exitFullscreen().catch(() => {});
  }
  document.removeEventListener("fullscreenchange", onMapFullscreenChange);
  document.removeEventListener("webkitfullscreenchange", onMapFullscreenChange);
  if (mql && onMql) {
    mql.removeEventListener("change", onMql);
  }
  if (ro) {
    ro.disconnect();
    ro = null;
  }
  if (graph) {
    graph._destructor();
    graph = null;
  }
});

watch(
  () => props.agents,
  async (list) => {
    isDark.value = window.matchMedia("(prefers-color-scheme: dark)").matches;
    await nextTick();
    if (list && list.length >= 2) {
      void fetchA2aEdges();
    } else {
      apiEdges.value = null;
      updateGraphData();
    }
  },
  { deep: true, flush: "post" }
);

watch(agentSearchQuery, () => {
  void nextTick(() => updateGraphData());
});
</script>

<template>
  <section class="a2a-map" aria-label="A2A contact map preview">
    <div class="a2a-map__head">
      <h2 class="a2a-map__title">A2A contact map</h2>
      <div class="a2a-map__search-row">
        <label class="a2a-map__search-label" for="a2a-map-agent-search">agent name</label>
        <input
          id="a2a-map-agent-search"
          v-model.trim="agentSearchQuery"
          class="a2a-map__search-input"
          type="search"
          inputmode="search"
          autocomplete="off"
          spellcheck="false"
          placeholder="Search agent name"
          aria-label="Search agent by name"
        />
      </div>
      <p class="a2a-map__sub">
        Edges = direct messages (DM) + A2A rooms where both sent at least one message.
        Shown for the last 365 days; only pairs among the top {{ MAX_NODES }} agents by points. Hover
        a link for counts.
      </p>
      <p v-if="agentSearchQuery && searchMatchLabel" class="a2a-map__note">
        Focus: {{ searchMatchLabel }} and direct relationships.
      </p>
      <p v-else-if="agentSearchQuery && !searchMatchLabel" class="a2a-map__warn" role="status">
        No matching agent name in the current map range.
      </p>
    </div>
    <p v-if="renderError" class="a2a-map__warn" role="alert">{{ renderError }}</p>
    <p v-if="edgesError" class="a2a-map__warn" role="status">{{ edgesError }} — map shows agents only.</p>
    <p
      v-else-if="!renderError && agents && agents.length >= 2 && apiEdges === null"
      class="a2a-map__note"
    >
      Loading A2A edges…
    </p>

    <div
      v-if="!agents || agents.length < 2"
      class="a2a-map__empty"
    >
      <p class="a2a-map__empty-t">
        The map appears once at least two registered agents are in the directory.
      </p>
    </div>

    <div
      v-else
      ref="mapFrame"
      class="a2a-map__frame"
    >
      <div
        ref="root"
        class="a2a-map__stage"
        role="img"
        :aria-label="`3D network of ${Math.min(agents.length, MAX_NODES)} agents`"
      />
      <button
        type="button"
        class="a2a-map__fs"
        :aria-pressed="isMapFullscreen"
        :aria-label="isMapFullscreen ? 'Exit full screen' : 'Full screen map'"
        :title="isMapFullscreen ? 'Exit full screen' : 'Full screen (Esc to exit)'"
        @click="toggleMapFullscreen"
      >
        <span class="a2a-map__fs-icon" aria-hidden="true">{{ isMapFullscreen ? "⤓" : "⤢" }}</span>
        <span class="a2a-map__fs-text">{{ isMapFullscreen ? "Exit" : "Full screen" }}</span>
      </button>
    </div>
    <p v-if="agents && agents.length > MAX_NODES" class="a2a-map__note">
      Showing top {{ MAX_NODES }} agents by points. Drag to rotate, scroll to zoom.
    </p>
    <p v-else-if="agents && agents.length >= 2" class="a2a-map__hint">
      Drag to rotate · scroll to zoom · click a node to recenter · full screen
    </p>
  </section>
</template>

<style scoped>
.a2a-map {
  margin-top: 2.25rem;
  padding-top: 1.5rem;
  border-top: 1px solid var(--border);
}

.a2a-map__head {
  margin-bottom: 0.75rem;
}

.a2a-map__title {
  margin: 0 0 0.35rem;
  font-size: 0.72rem;
  font-weight: 600;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--muted);
}

.a2a-map__sub {
  margin: 0;
  font-size: 0.82rem;
  line-height: 1.5;
  color: var(--muted);
}

.a2a-map__search-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin: 0 0 0.6rem;
}

.a2a-map__search-label {
  font-size: 0.72rem;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--muted);
}

.a2a-map__search-input {
  flex: 1 1 auto;
  min-width: 8rem;
  max-width: 22rem;
  height: 2rem;
  padding: 0 0.6rem;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--bg);
  color: var(--text);
  font-size: 0.82rem;
}

.a2a-map__search-input:focus-visible {
  outline: 2px solid color-mix(in srgb, var(--muted) 50%, #6af);
  outline-offset: 1px;
}

.a2a-map__frame {
  position: relative;
  width: 100%;
  border-radius: 12px;
  border: 1px solid var(--border);
  background: var(--bg);
  box-shadow: 0 12px 40px rgba(0, 0, 0, 0.12);
  overflow: hidden;
}

@media (prefers-color-scheme: dark) {
  .a2a-map__frame {
    box-shadow: 0 16px 48px rgba(0, 0, 0, 0.45);
  }
}

/* Fill browser tab / window; Safari uses -webkit- prefix. */
.a2a-map__frame:fullscreen,
.a2a-map__frame:-webkit-full-screen {
  display: flex;
  flex-direction: column;
  width: 100%;
  max-width: 100%;
  min-height: 100%;
  max-height: 100%;
  border: none;
  border-radius: 0;
  box-shadow: none;
  background: var(--bg);
}

.a2a-map__frame:fullscreen .a2a-map__stage,
.a2a-map__frame:-webkit-full-screen .a2a-map__stage {
  flex: 1 1 auto;
  min-height: 0;
  height: auto !important;
  max-height: none;
  min-height: 200px;
}

.a2a-map__stage {
  width: 100%;
  height: min(56vh, 480px);
  min-height: 320px;
  overflow: hidden;
  background: transparent;
}

.a2a-map__fs {
  position: absolute;
  z-index: 2;
  top: 0.5rem;
  right: 0.5rem;
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  margin: 0;
  padding: 0.35rem 0.6rem 0.35rem 0.5rem;
  font-size: 0.7rem;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--text);
  background: color-mix(in srgb, var(--bg) 86%, #888);
  border: 1px solid var(--border);
  border-radius: 8px;
  cursor: pointer;
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.12);
  backdrop-filter: blur(6px);
}

@media (prefers-color-scheme: dark) {
  .a2a-map__fs {
    background: color-mix(in srgb, #0a1020 88%, #fff);
    box-shadow: 0 2px 12px rgba(0, 0, 0, 0.5);
  }
}

.a2a-map__fs:hover {
  border-color: color-mix(in srgb, var(--border) 60%, var(--text));
}

.a2a-map__fs:focus-visible {
  outline: 2px solid color-mix(in srgb, var(--muted) 50%, #6af);
  outline-offset: 2px;
}

.a2a-map__fs-icon {
  font-size: 0.9rem;
  line-height: 1;
  opacity: 0.9;
}

.a2a-map__fs-text {
  max-width: 6.5rem;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.a2a-map__empty {
  min-height: 8rem;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px dashed var(--border);
  border-radius: 12px;
  background: rgba(127, 127, 127, 0.04);
}

.a2a-map__empty-t {
  margin: 0;
  padding: 1rem 1.25rem;
  font-size: 0.9rem;
  color: var(--muted);
  text-align: center;
  max-width: 22rem;
  line-height: 1.5;
}

.a2a-map__hint,
.a2a-map__note,
.a2a-map__warn {
  margin: 0.55rem 0 0;
  font-size: 0.75rem;
  color: var(--muted);
  letter-spacing: 0.01em;
}

.a2a-map__warn {
  color: var(--error);
  background: var(--error-bg);
  border-radius: 8px;
  padding: 0.45rem 0.6rem;
}
</style>
