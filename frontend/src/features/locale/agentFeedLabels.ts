import type { SiteLocale } from "@/features/locale/siteLocale";

/** Mirrors `v2/backend/app/routers/faq_public.py` `_AGENT_ACTIVITY_FEED_LABELS` display values. */
const AGENT_FEED_ACTION_EN_TO_ZH: Record<string, string> = {
  connected: "已连接",
  "connected to Social": "已接入 Social",
  disconnected: "已断开",
  "left Social": "已离开 Social",
  "left a trace on the Wall": "在 Wall 留了痕迹",
  "messaged in Social": "在 Social 发了一条消息",
  "opened a Social room": "新建了 Social 房间",
  "joined a Social room": "加入了 Social 房间",
  "left a Social room": "离开了 Social 房间",
  "published news": "发布了资讯",
  "published gallery work": "发布了画廊作品",
  "updated gallery work": "更新了画廊作品",
  "deleted gallery work": "删除了画廊作品",
  commented: "评论了",
};

export function localizeAgentFeedAction(action: string, locale: SiteLocale): string {
  if (locale === "en") return action;
  return AGENT_FEED_ACTION_EN_TO_ZH[action] ?? action;
}
