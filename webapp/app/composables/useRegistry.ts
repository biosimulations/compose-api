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

/** The environment a run used: the prebuilt simulator it named, else the shared one (`simulator` is null there). */
export async function environmentFor(simulator: string | null | undefined): Promise<EnvironmentSummary | null> {
  const all = await listEnvironments()
  return all.find(e => (e.simulator ?? null) === (simulator ?? null)) ?? null
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
