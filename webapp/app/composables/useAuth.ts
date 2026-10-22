import type { Auth0VueClient } from '@auth0/auth0-vue'
import type { components } from '~/api/schema'

/**
 * What the API publishes for this app at GET /webapp/config: its Auth0 settings (login is offered only when all
 * three are set) and the prebuilt simulator names a submission may ask for.
 */
export interface WebappConfig {
  auth0_domain: string
  auth0_audience: string
  auth0_client_id: string
  prebuilt_simulators: string[]
  dataset_kinds?: string[]
}

const webappConfig = ref<WebappConfig | null>(null)

export function useWebappConfig() {
  return webappConfig
}

interface AuthState {
  enabled: boolean
  audience: string
  // Set when the API answered 401 to a request that carried our token: the token was not accepted
  // (wrong audience, expired, tenant mismatch). The API never falls back to anonymous for a bad token.
  rejected: string | null
  // Set when the session could not be renewed (the refresh token expired or was revoked): the local session is
  // cleared, so the person is signed out and told why, instead of carrying on anonymously without knowing.
  expired: string | null
  // Who the API says the caller is (GET /auth/me), fetched once after sign-in; null until then.
  principal: Principal | null
}

export type Principal = components['schemas']['CurrentPrincipalResponse']

const state = reactive<AuthState>({ enabled: false, audience: '', rejected: null, expired: null, principal: null })
// Outside `state`: reactive() would unwrap the client's own refs.
const auth0 = shallowRef<Auth0VueClient | null>(null)

// The errors a silent renewal ends with when only a new sign-in can help (auth0-spa-js and the token endpoint).
const SESSION_ENDED = new Set(['login_required', 'invalid_grant', 'missing_refresh_token', 'consent_required'])
const EXPIRED = 'Your session has ended, so you are signed out. Sign in again to continue.'

export function authState(): AuthState {
  return state
}

export function setAuthClient(client: Auth0VueClient, audience: string) {
  auth0.value = client
  state.audience = audience
  state.enabled = true
  // Ask the API who this is once per sign-in: a token the API rejects (a wrong audience, say) shows up now, not
  // at the first request that happens to need it.
  watch(() => client.isAuthenticated.value, async (signedIn) => {
    if (!signedIn) {
      state.principal = null
      return
    }
    state.expired = null
    const { data } = await useApi().GET('/auth/me')
    state.principal = data ?? null
  }, { immediate: true })
}

let ending: Promise<void> | null = null

/** Clear the local session without leaving the page; Auth0's own session is left alone. */
function endSession(): Promise<void> {
  ending ??= (async () => {
    state.expired = EXPIRED
    try {
      await auth0.value?.logout({ openUrl: false })
    } finally {
      ending = null
    }
  })()
  return ending
}

/**
 * The access token for a request to `target`, or null to send it anonymously. Only requests to this app's API get
 * one (`isApiRequest`), so a token never travels to another host.
 */
export async function accessToken(target: string | URL | Request): Promise<string | null> {
  const client = auth0.value
  if (!client || state.rejected || !client.isAuthenticated.value) return null
  if (!isApiRequest(target, useRuntimeConfig().public.apiBase, window.location.origin)) return null
  try {
    return (await client.getAccessTokenSilently({ authorizationParams: { audience: state.audience } })) ?? null
  } catch (e) {
    if (SESSION_ENDED.has((e as { error?: string }).error ?? '')) await endSession()
    return null
  }
}

export function useAuth() {
  const client = auth0
  const isAuthenticated = computed(() => !!client.value?.isAuthenticated.value)
  const isLoading = computed(() => !!client.value?.isLoading.value)
  const user = computed(() => client.value?.user.value)
  const route = useRoute()
  const redirectUri = () => `${window.location.origin}${useRuntimeConfig().app.baseURL}`
  // auth0-vue returns to `appState.target` through the app's router after the callback.
  const signIn = (signup: boolean) => client.value?.loginWithRedirect({
    appState: { target: route.fullPath },
    authorizationParams: signup ? { screen_hint: 'signup' } : undefined
  })

  return {
    enabled: computed(() => state.enabled),
    rejected: computed(() => state.rejected),
    expired: computed(() => state.expired),
    principal: computed(() => state.principal),
    isAuthenticated,
    isLoading,
    user,
    error: computed(() => client.value?.error.value),
    login: () => signIn(false),
    signup: () => signIn(true),
    logout: () => client.value?.logout({ logoutParams: { returnTo: redirectUri() } }),
    clearRejected: () => {
      state.rejected = null
    },
    clearExpired: () => {
      state.expired = null
    }
  }
}
