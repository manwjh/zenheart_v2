import { createRouter, createWebHashHistory } from "vue-router";
import HomeView from "@/views/HomeView.vue";
import AboutView from "@/views/AboutView.vue";
import FaqView from "@/views/FaqView.vue";
import AiVisitorsView from "@/views/AiVisitorsView.vue";
import NewsView from "@/views/NewsView.vue";
import SocialView from "@/views/SocialView.vue";

export const router = createRouter({
  history: createWebHashHistory(import.meta.env.BASE_URL),
  routes: [
    { path: "/", name: "home", component: HomeView },
    { path: "/about", name: "about", component: AboutView },
    { path: "/news", name: "news", component: NewsView },
    { path: "/social", name: "social", component: SocialView },
    { path: "/faq", name: "faq", component: FaqView },
    { path: "/ai-visitors", name: "ai-visitors", component: AiVisitorsView },
    { path: "/application", redirect: "/faq" },
    { path: "/connection", redirect: "/faq" },
    { path: "/docs", redirect: "/faq" },
    { path: "/skills", redirect: "/faq" },
    { path: "/:pathMatch(.*)*", redirect: "/" },
  ],
});
