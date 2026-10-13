import { createAuth0 } from '@auth0/auth0-vue'
import type { WebappConfig } from '~/composables/useAuth'

// Loads GET /webapp/config, then the optional Auth0 login (after ../platform/frontend/app/plugins/auth0.client.ts).
// The API accepts anonymous requests, so the app works without login; a deployment turns it on by setting
// AUTH0_DOMAIN, AUTH0_AUDIENCE and AUTH0_SPA_CLIENT_ID on the API, which serves them here, since a static SPA has
// no server of its own to read the environment. The build-time runtimeConfig values are only a fallback.
export default defineNuxtPlugin(async (nuxtApp) => {
  const config = useRuntimeConfig()
  let settings: WebappConfig = {
    auth0_domain: config.public.auth0Domain,
    auth0_audience: config.public.auth0Audience,
    auth0_client_id: config.public.auth0ClientId,
    prebuilt_simulators: []
  }
  try {
    const response = await fetch(`${config.public.apiBase}/webapp/config`)
    if (response.ok) settings = await response.json() as WebappConfig
  } catch {
    // An API without the endpoint: keep the build-time values.
  }
  useWebappConfig().value = settings
  if (!settings.auth0_domain || !settings.auth0_audience || !settings.auth0_client_id) return

  const auth0 = createAuth0({
    domain: settings.auth0_domain,
    clientId: settings.auth0_client_id,
    useRefreshTokens: true,
    cacheLocation: 'localstorage',
    authorizationParams: {
      redirect_uri: `${window.location.origin}${config.app.baseURL}`,
      audience: settings.auth0_audience
    }
  })
  nuxtApp.vueApp.use(auth0)
  setAuthClient(auth0, settings.auth0_audience)
})
