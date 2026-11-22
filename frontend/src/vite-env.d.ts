/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** URL of catalog/index.json; unset means no catalogue has been published for this build. */
  readonly VITE_CATALOG_URL?: string;
}
