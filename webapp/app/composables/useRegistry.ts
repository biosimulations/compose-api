import type { Schemas } from './useApi'

export type EnvironmentSummary = Schemas['EnvironmentSummary']
export type InterfaceManifest = Schemas['InterfaceManifest']
export type EnvironmentHeaders = Schemas['EnvironmentHeaders']

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

/**
 * An environment's interfaces as `.pblang` header files, one per module, and each class's declaration by address
 * (printed by process-bigraph-lang on the server); null when the deployment cannot print them.
 */
export async function fetchHeaders(name: string): Promise<EnvironmentHeaders | null> {
  const { data, response } = await useApi().GET('/registry/environments/{name}/headers', { params: { path: { name } } })
  if (data) return data
  if (response.status === 404 || response.status === 503) return null
  throw new Error(`Could not fetch the ${name} headers (HTTP ${response.status})`)
}

export type ImageStatus = Schemas['ImageStatus']

/** Whether an environment's current image is built (docs/plan-environment-builds.md, phase 4); never cached. */
export async function fetchImageStatus(name: string): Promise<ImageStatus> {
  const { data, error } = await useApi().GET('/registry/environments/{name}/images', { params: { path: { name } } })
  if (error || !data) throw new Error(errorMessage(error, `Could not read the image status of ${name}`))
  return data
}

/** Ask for the environment's image: answered at once when it is built, otherwise its pull or build starts. */
export async function requestBuild(name: string): Promise<ImageStatus> {
  const { data, error } = await useApi().POST('/registry/environments/{name}/build', { params: { path: { name } } })
  if (error || !data) throw new Error(errorMessage(error, `Could not start the build of ${name}`))
  return data
}

export type EnvironmentVersions = Schemas['EnvironmentVersions']
export type EnvironmentVersion = Schemas['EnvironmentVersion']
export type EnvironmentVersionDetail = Schemas['EnvironmentVersionDetail']
export type ComplianceReport = Schemas['ComplianceReport']

/** An environment's versions, newest first, and which is its default (docs/plan-environment-versions.md). */
export async function fetchVersions(name: string): Promise<EnvironmentVersions> {
  const { data, error } = await useApi().GET('/registry/environments/{name}/versions', { params: { path: { name } } })
  if (error || !data) throw new Error(errorMessage(error, `Could not list the versions of ${name}`))
  return data
}

/** One version: what it was made from, its lock, and what it installed and provides. */
export async function fetchVersion(name: string, number: number): Promise<EnvironmentVersionDetail> {
  const { data, error } = await useApi().GET('/registry/environments/{name}/versions/{number}', {
    params: { path: { name, number } }
  })
  if (error || !data) throw new Error(errorMessage(error, `Could not read ${name}@${number}`))
  return data
}

/** Where each of a composed version's entries stands there (its compliance cases), and what the checks refuse. */
export async function fetchCompliance(name: string, number: number): Promise<ComplianceReport | null> {
  const { data } = await useApi().GET('/registry/environments/{name}/versions/{number}/compliance', {
    params: { path: { name, number } }
  })
  return data ?? null
}

/** The files that recreate a version locally (pixi.toml and pixi.lock, or a uv project), or null when it has none. */
export async function fetchExport(name: string, number: number, format: 'pixi' | 'uv'): Promise<Record<string, string> | null> {
  const { data } = await useApi().GET('/registry/environments/{name}/versions/{number}/export', {
    params: { path: { name, number }, query: { format } }
  })
  return (data?.files as Record<string, string> | undefined) ?? null
}

export type SimulatorSummary = Schemas['SimulatorSummary']
export type SimulatorDetail = Schemas['SimulatorDetail']

/** Every simulator that is a version or that runs used, newest first; those with no versions ran before versions. */
export async function listSimulators(): Promise<SimulatorSummary[]> {
  const { data, error } = await useApi().GET('/registry/simulators')
  if (error || !data) throw new Error(errorMessage(error, 'Could not list the simulators'))
  return data
}

/** One simulator with its container definition, or null when there is none (or no run you can read used it). */
export async function fetchSimulator(id: number): Promise<SimulatorDetail | null> {
  const { data, error, response } = await useApi().GET('/registry/simulators/{simulator_id}', {
    params: { path: { simulator_id: id } }
  })
  if (response.status === 404) return null
  if (error || !data) throw new Error(errorMessage(error, `Could not read simulator ${id}`))
  return data
}

// Administration (docs/plan-webapp-admin.md, step 6): each needs `environments:admin`, which the API checks again.

export type NewEnvironmentVersion = Schemas['NewEnvironmentVersion']

/** A new version: a composed environment's entries at a date, or a prebuilt one's image. An identical one is returned
 * instead of a second (the API answers 200 rather than 201). */
export async function createVersion(name: string, body: NewEnvironmentVersion): Promise<EnvironmentVersion> {
  const { data, error } = await useApi().POST('/registry/environments/{name}/versions', { params: { path: { name } }, body })
  if (error || !data) throw new Error(errorMessage(error, `Could not make a new version of ${name}`))
  return data
}

export async function setDefaultVersion(name: string, number: number): Promise<EnvironmentVersion> {
  const { data, error } = await useApi().PUT('/registry/environments/{name}/default', { params: { path: { name } }, body: { number } })
  if (error || !data) throw new Error(errorMessage(error, `Could not make ${name}@${number} the default`))
  return data
}

export async function retireVersion(name: string, number: number): Promise<EnvironmentVersion> {
  const { data, error } = await useApi().POST('/registry/environments/{name}/versions/{number}/retire', {
    params: { path: { name, number } }
  })
  if (error || !data) throw new Error(errorMessage(error, `Could not retire ${name}@${number}`))
  return data
}

export async function inspectVersion(name: string, number: number): Promise<EnvironmentVersion> {
  const { data, error } = await useApi().POST('/registry/environments/{name}/versions/{number}/inspect', {
    params: { path: { name, number } }
  })
  if (error || !data) throw new Error(errorMessage(error, `Could not read ${name}@${number} back`))
  return data
}

/** How a version's installed packages differ from another's (`?against=`), or null when either has none read back. */
export async function fetchChanges(name: string, number: number, against: number): Promise<Schemas['PackageChange'][] | null> {
  const { data, response } = await useApi().GET('/registry/environments/{name}/versions/{number}', {
    params: { path: { name, number }, query: { against } }
  })
  if (response.status === 409) return null
  if (!data) throw new Error(`Could not compare ${name}@${number} with @${against} (HTTP ${response.status})`)
  return data.changes ?? []
}
