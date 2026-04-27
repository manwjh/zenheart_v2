/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** When set, sent as first frame on /v2/social/observe when server requires SOCIAL_OBSERVE_SHARED_TOKEN */
  readonly VITE_SOCIAL_OBSERVE_TOKEN?: string;
  /** Optional: HTTPS origin for Zenlink FAQ URLs (e.g. staging). Default: window.location.origin, else https://zenheart.net */
  readonly VITE_ZENLINK_SOURCE_ORIGIN?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

declare module "*.vue" {
  import type { DefineComponent } from "vue";
  const component: DefineComponent<object, object, unknown>;
  export default component;
}
