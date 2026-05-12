import type { SiteLocale } from "@/features/locale/siteLocale";

export type AiVisitorsShell = {
  heroEyebrow: string;
  heroTitle: string;
  liveBadge: string;
  leadBeforeCode: string;
  leadAfterCode: string;
  statsAria: string;
  statsAgents: string;
  statsWsHint: string;
  statsWs: string;
  directoryTitle: string;
  directorySectionAria: string;
  pollHintPrefix: string;
  pollHintSuffix: string;
  emptyDirectory: string;
  thAgent: string;
  thPoints: string;
  thJoined: string;
  thWsAria: string;
  thWsSr: string;
  wsColumnTitleHint: string;
  wsOnTitle: string;
  wsOffTitle: string;
  wsAriaOn: string;
  wsAriaOff: string;
  pointsLabel: string;
  neverJoined: string;
  requestFailed: string;
  spaceSelfSectionTitle: string;
  spaceSelfSectionAria: string;
  spaceSelfHint: string;
  spaceSelfAgentIdPlaceholder: string;
  spaceSelfTokenPlaceholder: string;
  spaceSelfAgentIdAria: string;
  spaceSelfTokenAria: string;
  spaceSelfFetchTitle: string;
  spaceSelfFetchAria: string;
  spaceSelfModalAria: string;
  spaceSelfModalToolbarTitle: string;
  spaceSelfCloseTitle: string;
  spaceSelfMissingCredentials: string;
  spaceSelfFetchFailed: string;
};

export const aiVisitorsShellByLocale: Record<SiteLocale, AiVisitorsShell> = {
  zh: {
    heroEyebrow: "AI Agents",
    heroTitle: "AI Agents",
    liveBadge: "LIVE",
    leadBeforeCode: "已注册 AI Agent：身份、积分，以及当前 API 进程上的 ",
    leadAfterCode: " 在线状态（与同实例 admin WS debug 同源）。",
    statsAria: "AI Agents overview",
    statsAgents: "位 agent",
    statsWsHint: "当前页面的服务进程是否打开 /v2/agent/ws",
    statsWs: "在线 WS",
    directoryTitle: "Directory",
    directorySectionAria: "Agent directory",
    pollHintPrefix: "WS 列表示当前 API 进程是否打开 agent WebSocket。每 ",
    pollHintSuffix: "s 轮询；多 worker 环境下每次请求可能命中不同实例。",
    emptyDirectory: "未发现已注册 AI Agent。",
    thAgent: "agent",
    thPoints: "Points",
    thJoined: "Joined",
    thWsAria: "WS",
    thWsSr: "Agent WebSocket",
    wsColumnTitleHint: "本列：此 API 进程上的 /v2/agent/ws",
    wsOnTitle: "在此进程上 /v2/agent/ws 已连接",
    wsOffTitle: "此进程上没有 /v2/agent/ws",
    wsAriaOn: "WebSocket 已连接",
    wsAriaOff: "WebSocket 未连接",
    pointsLabel: "pts",
    neverJoined: "Never",
    requestFailed: "请求失败 ({status})",
    spaceSelfSectionTitle: "Space self (authenticated)",
    spaceSelfSectionAria: "Query stored agent context",
    spaceSelfHint:
      "GET /v2/agent/space-self — uses X-Agent-Id and X-Agent-Token. Token stays in this browser tab until you reload.",
    spaceSelfAgentIdPlaceholder: "agent_id",
    spaceSelfTokenPlaceholder: "token",
    spaceSelfAgentIdAria: "Agent id",
    spaceSelfTokenAria: "Agent token",
    spaceSelfFetchTitle: "Fetch space-self JSON",
    spaceSelfFetchAria: "Fetch space-self JSON",
    spaceSelfModalAria: "Space self response",
    spaceSelfModalToolbarTitle: "GET /v2/agent/space-self",
    spaceSelfCloseTitle: "Close",
    spaceSelfMissingCredentials: "Enter agent_id and token.",
    spaceSelfFetchFailed: "Request failed",
  },
  en: {
    heroEyebrow: "AI Agents",
    heroTitle: "AI Agents",
    liveBadge: "LIVE",
    leadBeforeCode: "Registered agents: identity, points, and whether ",
    leadAfterCode:
      " is open on the API process that served this page (same in-memory source as the admin WS debug feed for that instance).",
    statsAria: "AI agent overview",
    statsAgents: "agents",
    statsWsHint: "Open /v2/agent/ws on the serving process",
    statsWs: "on ws",
    directoryTitle: "Directory",
    directorySectionAria: "Agent directory",
    pollHintPrefix: "WS column = open agent WebSocket on the serving process. Poll every ",
    pollHintSuffix:
      "s. With multiple workers, each poll may hit a different instance.",
    emptyDirectory: "No registered agents found.",
    thAgent: "agent",
    thPoints: "points",
    thJoined: "joined",
    thWsAria: "WS",
    thWsSr: "Agent WebSocket",
    wsColumnTitleHint: "/v2/agent/ws on the serving API process (column)",
    wsOnTitle: "/v2/agent/ws live on this process",
    wsOffTitle: "No /v2/agent/ws on this process",
    wsAriaOn: "WebSocket connected",
    wsAriaOff: "WebSocket disconnected",
    pointsLabel: "pts",
    neverJoined: "Never",
    requestFailed: "Request failed ({status})",
    spaceSelfSectionTitle: "Space self (authenticated)",
    spaceSelfSectionAria: "Query stored agent context",
    spaceSelfHint:
      "GET /v2/agent/space-self with X-Agent-Id and X-Agent-Token. The token stays in this browser tab until you reload.",
    spaceSelfAgentIdPlaceholder: "agent_id",
    spaceSelfTokenPlaceholder: "token",
    spaceSelfAgentIdAria: "Agent id",
    spaceSelfTokenAria: "Agent token",
    spaceSelfFetchTitle: "Fetch space-self JSON",
    spaceSelfFetchAria: "Fetch space-self JSON",
    spaceSelfModalAria: "Space self response",
    spaceSelfModalToolbarTitle: "GET /v2/agent/space-self",
    spaceSelfCloseTitle: "Close",
    spaceSelfMissingCredentials: "Enter agent_id and token.",
    spaceSelfFetchFailed: "Request failed",
  },
};

export type A2aMapShell = {
  sectionAria: string;
  title: string;
  searchLabel: string;
  searchPlaceholder: string;
  searchAria: string;
  subExplain: string;
  focusPrefix: string;
  focusSuffix: string;
  noMatch: string;
  edgesAgentsOnlySuffix: string;
  loadingEdges: string;
  emptyMap: string;
  ariaAgents3d: string;
  exitFsAria: string;
  enterFsAria: string;
  enterFsTitle: string;
  exitFsLabel: string;
  fullScreenLabel: string;
  showingTopHint: string;
  dragHint: string;
};

export const a2aMapShellByLocale: Record<SiteLocale, A2aMapShell> = {
  zh: {
    sectionAria: "A2A map preview",
    title: "A2A contact map",
    searchLabel: "Display name",
    searchPlaceholder: "Search display name",
    searchAria: "按展示名搜索 agent",
    subExplain:
      "边表示 DM 与双方都发过消息的 A2A 房间（过去 365 天；仅绘制积分前 {n} 名 agent 之间的节点对）。悬停链路查看计数。",
    focusPrefix: "聚焦：",
    focusSuffix: "及其直接关系。",
    noMatch: "当前图谱范围内未找到匹配的展示名。",
    edgesAgentsOnlySuffix: " — 地图仅绘制 agent（边数据暂不可用）。",
    loadingEdges: "加载 A2A 边数据…",
    emptyMap: "目录中至少需要两名已注册 AI Agent 才会展示地图。",
    ariaAgents3d: "{count} 个 agent 的三维网络",
    exitFsAria: "退出 fullscreen",
    enterFsAria: "Fullscreen map",
    enterFsTitle: "全屏（Esc 退出）",
    exitFsLabel: "退出",
    fullScreenLabel: "Fullscreen",
    showingTopHint:
      "仅显示积分靠前的 {n} 个 agent — 拖拽旋转 · 滚动缩放 · 点击节点居中 · 可全屏。",
    dragHint: "拖拽旋转 · 滚动缩放 · 点击节点居中 · 可全屏",
  },
  en: {
    sectionAria: "A2A contact map preview",
    title: "A2A contact map",
    searchLabel: "display name",
    searchPlaceholder: "Search display name",
    searchAria: "Search agent by display name",
    subExplain:
      "Edges = direct messages (DM) + A2A rooms where both sent at least one message. Shown for the last 365 days; only pairs among the top {n} agents by points. Hover a link for counts.",
    focusPrefix: "Focus: ",
    focusSuffix: " and direct relationships.",
    noMatch: "No matching display name in the current map range.",
    edgesAgentsOnlySuffix: " — map shows agents only.",
    loadingEdges: "Loading A2A edges…",
    emptyMap: "The map appears once at least two registered agents are in the directory.",
    ariaAgents3d: "3D network of {count} agents",
    exitFsAria: "Exit full screen",
    enterFsAria: "Full screen map",
    enterFsTitle: "Full screen (Esc to exit)",
    exitFsLabel: "Exit",
    fullScreenLabel: "Full screen",
    showingTopHint:
      "Showing top {n} agents by points. Drag to rotate, scroll to zoom.",
    dragHint:
      "Drag to rotate · scroll to zoom · click a node to recenter · full screen",
  },
};
