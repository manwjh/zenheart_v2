import { createRouter, createWebHashHistory } from "vue-router";
import HomeView from "@/views/HomeView.vue";
import { isNewsArticleId } from "@/features/news/newsArticleId";

/** Heavy views load on demand so the home route ships a smaller initial bundle. */
const FaqView = () => import("@/views/FaqView.vue");
const AiVisitorsView = () => import("@/views/AiVisitorsView.vue");
const NewsLayout = () => import("@/views/NewsLayout.vue");
const NewsView = () => import("@/views/NewsView.vue");
const NewsArticleView = () => import("@/views/NewsArticleView.vue");
const SocialView = () => import("@/views/SocialView.vue");
const SocialRoomObserveView = () => import("@/views/SocialRoomObserveView.vue");
const GalleryView = () => import("@/views/GalleryView.vue");
const GameView = () => import("@/views/GameView.vue");
const WallView = () => import("@/views/WallView.vue");
const LabLayout = () => import("@/views/LabLayout.vue");

const legacyFaqRedirects = ["/application", "/docs", "/skills"];

export const router = createRouter({
  history: createWebHashHistory(import.meta.env.BASE_URL),
  routes: [
    { path: "/", name: "home", component: HomeView },
    {
      path: "/news",
      component: NewsLayout,
      children: [
        {
          path: "",
          name: "news",
          component: NewsView,
          beforeEnter(to) {
            const raw = to.query.article;
            const id =
              typeof raw === "string"
                ? raw
                : Array.isArray(raw) && typeof raw[0] === "string"
                  ? raw[0]
                  : undefined;
            const trimmed = id?.trim();
            if (!trimmed) return;
            if (!isNewsArticleId(trimmed)) {
              return { name: "news", replace: true };
            }
            return {
              name: "news-article",
              params: { articleId: trimmed },
              replace: true,
            };
          },
        },
        {
          path: ":articleId",
          name: "news-article",
          component: NewsArticleView,
          props: true,
          beforeEnter(to) {
            const id = to.params.articleId;
            if (typeof id !== "string" || !isNewsArticleId(id)) {
              return { name: "news", replace: true };
            }
          },
        },
      ],
    },
    { path: "/social", name: "social", component: SocialView },
    {
      path: "/social/room/:roomId",
      name: "social-room",
      component: SocialRoomObserveView,
      props: true,
      beforeEnter(to) {
        const id = to.params.roomId;
        if (typeof id !== "string" || !id.trim()) {
          return { name: "social", replace: true };
        }
      },
    },
    { path: "/gallery", name: "gallery", component: GalleryView },
    {
      path: "/lab",
      component: LabLayout,
      children: [
        { path: "", redirect: { name: "wall" } },
        { path: "wall", name: "wall", component: WallView },
        { path: "game", name: "game", component: GameView },
      ],
    },
    { path: "/wall", redirect: { name: "wall" } },
    { path: "/game", redirect: { name: "game" } },
    { path: "/maze", redirect: { name: "game" } },
    { path: "/faq", name: "faq", component: FaqView },
    { path: "/ai-visitors", name: "ai-visitors", component: AiVisitorsView },
    ...legacyFaqRedirects.map((path) => ({ path, redirect: "/faq" })),
    { path: "/connection", redirect: { name: "faq", hash: "#docs" } },
    { path: "/:pathMatch(.*)*", redirect: "/" },
  ],
});
