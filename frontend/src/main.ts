import { createApp } from "vue";
import App from "./App.vue";
import { router } from "./router";
import { initSiteLocale } from "@/features/locale/siteLocale";
import "./styles/tokens-layout.css";
import "./styles/tokens-typography.css";
import "./styles/reduced-motion-global.css";
import "./styles/primitives.css";

initSiteLocale();

const app = createApp(App);
app.use(router);
app.mount("#app");
