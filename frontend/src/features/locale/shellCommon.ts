import type { SiteLocale } from "@/features/locale/siteLocale";

export type ShellCommon = {
  networkError: string;
  failedToLoadNewsList: string;
  failedToLoadRooms: string;
  failedToLoadHistory: string;
  failedToLoadGallery: string;
  failedToLoadArticle: string;
  articleNotFound: string;
  failedToLoadWall: string;
  couldNotPost: string;
  contentNotReady: string;
  unknownError: string;
  requestFailedStatus: string;
};

export const shellCommonByLocale: Record<SiteLocale, ShellCommon> = {
  zh: {
    networkError: "网络错误。",
    failedToLoadNewsList: "加载资讯列表失败。",
    failedToLoadRooms: "加载房间失败。",
    failedToLoadHistory: "加载历史失败。",
    failedToLoadGallery: "加载画廊失败。",
    failedToLoadArticle: "加载文章失败。",
    articleNotFound: "未找到文章。",
    failedToLoadWall: "加载失败。",
    couldNotPost: "发布失败。",
    contentNotReady: "内容尚未就绪。",
    unknownError: "未知错误。",
    requestFailedStatus: "请求失败 ({status})",
  },
  en: {
    networkError: "Network error.",
    failedToLoadNewsList: "Failed to load news list.",
    failedToLoadRooms: "Failed to load rooms.",
    failedToLoadHistory: "Failed to load history.",
    failedToLoadGallery: "Failed to load gallery.",
    failedToLoadArticle: "Failed to load article detail.",
    articleNotFound: "Article not found.",
    failedToLoadWall: "Failed to load.",
    couldNotPost: "Could not post.",
    contentNotReady: "Content not ready.",
    unknownError: "Unknown error.",
    requestFailedStatus: "Request failed ({status})",
  },
};
