/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** When set, sent as first frame on /v2/social/observe when server requires SOCIAL_OBSERVE_SHARED_TOKEN */
  readonly VITE_SOCIAL_OBSERVE_TOKEN?: string;
  /** Optional: absolute public site origin for shareable FAQ doc links (e.g. staging). Default: non-localhost window.origin, else https://zenheart.net */
  readonly VITE_PUBLIC_SITE_ORIGIN?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

declare module "*.vue" {
  import type { DefineComponent } from "vue";
  const component: DefineComponent<object, object, unknown>;
  export default component;
}
