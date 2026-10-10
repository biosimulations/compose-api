import type { Auth0VueClient } from '@auth0/auth0-vue'

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
}

const state = reactive<AuthState>({ enabled: false, audience: '', rejected: null })
// Outside `state`: reactive() would unwrap the client's own refs.
const auth0 = shallowRef<Auth0VueClient | null>(null)

export function authState(): AuthState {
  return state
}

export function setAuthClient(client: Auth0VueClient, audience: string) {
  auth0.value = client
  state.audience = audience
  state.enabled = true
}

/** The access token to send to the API, or null to call anonymously. */
export async function accessToken(): Promise<string | null> {
  const client = auth0.value
  if (!client || state.rejected || !client.isAuthenticated.value) return null
  try {
    return (await client.getAccessTokenSilently({ authorizationParams: { audience: state.audience } })) ?? null
  } catch {
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

  return {
    enabled: computed(() => state.enabled),
    rejected: computed(() => state.rejected),
    isAuthenticated,
    isLoading,
    user,
    error: computed(() => client.value?.error.value),
    login: () => client.value?.loginWithRedirect({ appState: { target: route.fullPath } }),
    logout: () => client.value?.logout({ logoutParams: { returnTo: redirectUri() } }),
    clearRejected: () => {
      state.rejected = null
    }
  }
}
