import { createRouter, createWebHashHistory } from "vue-router";
import HomeView from "@/views/HomeView.vue";

/** Heavy views load on demand so the home route ships a smaller initial bundle. */
const FaqView = () => import("@/views/FaqView.vue");
const AiVisitorsView = () => import("@/views/AiVisitorsView.vue");
const NewsView = () => import("@/views/NewsView.vue");
const SocialView = () => import("@/views/SocialView.vue");
const GameView = () => import("@/views/GameView.vue");
const WallView = () => import("@/views/WallView.vue");

export const router = createRouter({
  history: createWebHashHistory(import.meta.env.BASE_URL),
  routes: [
    { path: "/", name: "home", component: HomeView },
    { path: "/about", redirect: "/" },
    { path: "/news", name: "news", component: NewsView },
    { path: "/social", name: "social", component: SocialView },
    { path: "/wall", name: "wall", component: WallView },
    { path: "/game", name: "game", component: GameView },
    { path: "/maze", redirect: { name: "game" } },
    { path: "/faq", name: "faq", component: FaqView },
    { path: "/ai-visitors", name: "ai-visitors", component: AiVisitorsView },
    { path: "/application", redirect: "/faq" },
    { path: "/connection", redirect: { name: "faq", hash: "#docs" } },
    { path: "/docs", redirect: "/faq" },
    { path: "/skills", redirect: "/faq" },
    { path: "/:pathMatch(.*)*", redirect: "/" },
  ],
});
