import type { Schemas } from './useApi'

export type EnvironmentSummary = Schemas['EnvironmentSummary']
export type InterfaceManifest = Schemas['InterfaceManifest']

/**
 * The environments documents run in, and their interface manifests (`pbg-interfaces/1`: every step and process class
 * an environment provides, read inside its image; docs/plan-authoring.md). The checker resolves a composite's
 * addresses against the manifest of the environment it runs in. Both are fetched once per page load: they change only
 * with a release.
 */
let environments: Promise<EnvironmentSummary[]> | null = null
const manifests = new Map<string, Promise<InterfaceManifest | null>>()

export function listEnvironments(): Promise<EnvironmentSummary[]> {
  environments ??= useApi()
    .GET('/registry/environments')
    .then(({ data, error }) => {
      if (error || !data) throw new Error(errorMessage(error, 'Could not list the environments'))
      return data
    })
    .catch((e) => {
      environments = null // retry on the next call
      throw e
    })
  return environments
}

/** An image reference without its digest or tag: `ghcr.io/org/name@sha256:…` and `ghcr.io/org/name:1.0` → `ghcr.io/org/name`. */
export function imageRepository(ref: string): string {
  const at = ref.indexOf('@')
  const bare = at < 0 ? ref : ref.slice(0, at)
  const colon = bare.lastIndexOf(':')
  return colon > bare.lastIndexOf('/') ? bare.slice(0, colon) : bare
}

/**
 * The environment a run used. A run's `simulator` is null for the shared image; for a prebuilt one it is the image it
 * ran in (an earlier digest of it, too, once the pin moves), so it is matched by repository; a bare name also matches.
 */
export async function environmentFor(simulator: string | null | undefined): Promise<EnvironmentSummary | null> {
  return matchEnvironment(await listEnvironments(), simulator)
}

export function matchEnvironment<E extends Pick<EnvironmentSummary, 'simulator' | 'image'>>(
  all: E[],
  simulator: string | null | undefined
): E | null {
  if (!simulator) return all.find(e => !e.simulator) ?? null
  const repository = imageRepository(simulator)
  return all.find(e => e.simulator && (e.simulator === simulator || (e.image != null && imageRepository(e.image) === repository))) ?? null
}

/** An environment's manifest, or null when none has been generated for it. */
export function fetchManifest(name: string): Promise<InterfaceManifest | null> {
  let pending = manifests.get(name)
  if (!pending) {
    pending = useApi()
      .GET('/registry/environments/{name}/manifest', { params: { path: { name } } })
      .then(({ data, response }) => {
        if (data) return data
        if (response.status === 404) return null
        throw new Error(`Could not fetch the ${name} manifest (HTTP ${response.status})`)
      })
      .catch((e) => {
        manifests.delete(name)
        throw e
      })
    manifests.set(name, pending)
  }
  return pending
}
