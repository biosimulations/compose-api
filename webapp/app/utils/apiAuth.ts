/**
 * Whether a request goes to this app's API, so it may carry the caller's access token
 * (after ../platform/frontend/app/utils/api-auth.ts).
 *
 * `apiBase` is the API's base URL: empty in a deployment, where the API serves the UI from its own origin, and an
 * absolute URL in development. The destination must be http(s), on the API's origin, under the API's path, and carry
 * no user info. Anything unparseable is refused, so a token never reaches another host, not even one that looks alike.
 */
export function isApiRequest(request: string | URL | Request, apiBase: string, pageOrigin: string): boolean {
  try {
    const api = new URL(apiBase || '/', pageOrigin)
    const target = request instanceof Request ? request.url : request
    const destination = new URL(target, pageOrigin)
    const path = api.pathname.replace(/\/$/, '')
    return ['http:', 'https:'].includes(api.protocol)
      && !destination.username && !destination.password
      && destination.origin === api.origin
      && (path === '' || destination.pathname === path || destination.pathname.startsWith(`${path}/`))
  } catch {
    return false
  }
}
