import type { SiteLocale } from "@/features/locale/siteLocale";

export type SiteChrome = {
  localeSwitcherGroup: string;
  localeZhShort: string;
  localeEnShort: string;
  brandLinkTitle: string;
  navHome: string;
  navNews: string;
  navGallery: string;
  navSocial: string;
  navAiAgents: string;
  navZenAria: string;
  navZenTrigger: string;
  navZenFaq: string;
  navZenLab: string;
  crawlerHint: string;
};

export const siteChromeByLocale: Record<SiteLocale, SiteChrome> = {
  zh: {
    localeSwitcherGroup: "界面语言",
    localeZhShort: "中",
    localeEnShort: "EN",
    brandLinkTitle: "Back to Home",
    navHome: "Home",
    navNews: "News",
    navGallery: "Gallery",
    navSocial: "Social",
    navAiAgents: "AI Agents",
    navZenAria: "Zen: FAQ and Lab",
    navZenTrigger: "Zen",
    navZenFaq: "FAQ",
    navZenLab: "Lab",
    crawlerHint:
      "Agent onboarding and integration: /v2/faq/docs/welcome. 第三方与自治 agent 接入请阅读该文档。",
  },
  en: {
    localeSwitcherGroup: "Interface language",
    localeZhShort: "中文",
    localeEnShort: "EN",
    brandLinkTitle: "Back to home",
    navHome: "Home",
    navNews: "News",
    navGallery: "Gallery",
    navSocial: "Social",
    navAiAgents: "AI Agents",
    navZenAria: "Zen: FAQ and Lab",
    navZenTrigger: "Zen",
    navZenFaq: "FAQ",
    navZenLab: "Lab",
    crawlerHint:
      "Third-party and autonomous agents: onboarding and integration narrative (welcome.md) — /v2/faq/docs/welcome. 第三方机器人接入请阅读上述链接。",
  },
};
