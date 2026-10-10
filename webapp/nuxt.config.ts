// Static SPA served by the compose-api FastAPI app at /ui (compose_api/api/webapp.py).
// Same origin in production, so the API base is ''. In development (`make webapp-dev`, :4200/ui/) the API base comes
// from NUXT_PUBLIC_API_BASE and the browser calls the API directly; localhost:4200 is in the API's CORS origins.

export default defineNuxtConfig({
  modules: ['@nuxt/eslint', '@nuxt/ui', '@vueuse/nuxt'],

  ssr: false,

  devtools: { enabled: true },

  app: {
    baseURL: '/ui/',
    head: {
      title: 'compose-api',
      htmlAttrs: { lang: 'en' },
      link: [{ rel: 'icon', type: 'image/svg+xml', href: '/ui/favicon.svg' }]
    }
  },

  css: ['~/assets/css/main.css'],

  colorMode: { preference: 'light' },

  // Build-time values only (this is a static SPA). The deployed app reads its Auth0 settings from the API at
  // GET /webapp/config; these are the fallback when that endpoint is absent.
  runtimeConfig: {
    public: {
      apiBase: '',
      auth0Domain: '',
      auth0ClientId: '',
      auth0Audience: ''
    }
  },

  // Icons are bundled from the installed @iconify-json sets (scanned from the source) instead of fetched from
  // api.iconify.design at runtime.
  icon: {
    provider: 'none',
    clientBundle: { scan: true }
  },

  // Nuxt UI's @nuxt/fonts fetches web fonts at build time; the on-premise build uses system fonts instead.
  ui: { fonts: false },

  compatibilityDate: '2025-01-15',

  vite: {
    // Pre-bundle Plotly's UMD build so the dev server exposes it as a module (served raw, it sets a global instead).
    optimizeDeps: { include: ['plotly.js-dist-min'] }
  }
})
