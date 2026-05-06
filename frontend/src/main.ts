import { createApp } from "vue";
import App from "./App.vue";
import { router } from "./router";
import "./styles/tokens-layout.css";
import "./styles/tokens-typography.css";
import "./styles/reduced-motion-global.css";
import "./styles/primitives.css";

const app = createApp(App);
app.use(router);
app.mount("#app");
