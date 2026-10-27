import type { Schemas } from '~/composables/useApi'

// Environment versions as the pages show them (docs/plan-webapp-admin.md, step 5): what a version installed, how two
// versions' packages differ, and what its state and spec say. Pure, so the pages and their tests share them.

type Version = Schemas['EnvironmentVersion']
type BadgeColor = 'success' | 'error' | 'warning' | 'info' | 'neutral'

/** A version's installed packages (`name==version` per line, as its image's read-back recorded them), by name. */
export function parseInstalled(text: string | null | undefined): Map<string, string> {
  const packages = new Map<string, string>()
  for (const line of (text ?? '').split('\n')) {
    const [name, version] = line.trim().split('==')
    if (name && version !== undefined) packages.set(normalize(name), version.trim())
  }
  return packages
}

// PyPI names compare case-insensitively, with `-`, `_` and `.` alike (PEP 503)
const normalize = (name: string) => name.toLowerCase().replace(/[-_.]+/g, '-')

export interface PackageChange { name: string, from: string | null, to: string | null }

/** How the packages changed from ``before`` to ``after``: added (from null), removed (to null) or a new version. */
export function packageChanges(before: Map<string, string>, after: Map<string, string>): PackageChange[] {
  const names = [...new Set([...before.keys(), ...after.keys()])].sort()
  return names
    .map(name => ({ name, from: before.get(name) ?? null, to: after.get(name) ?? null }))
    .filter(c => c.from !== c.to)
}

export function stateColor(state: Version['state'] | string): BadgeColor {
  switch (state) {
    case 'ready': return 'success'
    case 'failed': return 'error'
    case 'retired': return 'neutral'
    case 'building': case 'resolving': return 'info'
    default: return 'warning'
  }
}

export interface SpecEntry { id: string, install: string }

/** The registry entries a composed version is made of, each with how it was installed. */
export function specEntries(spec: Version['spec']): SpecEntry[] {
  const entries = (spec?.entries ?? []) as { id?: string, install?: Record<string, string> | null, conda?: Record<string, string> }[]
  return entries.filter(e => e.id).map((e) => {
    const install = e.install ?? {}
    const how = install.git
      ? `${install.git.replace('https://github.com/', '')}@${(install.commit ?? '').slice(0, 7)}`
      : install.pypi
        ? `${install.pypi}==${install.version ?? '?'}`
        : Object.entries(e.conda ?? {}).map(([k, v]) => `conda ${k}${v}`).join(', ') || 'listed'
    return { id: e.id!, install: how }
  })
}

/** What a version's core packages are, from its spec (composed) or its read-back packages. */
export function corePackages(version: Version, installed: Map<string, string>): string[] {
  const core = (version.spec?.core ?? {}) as Record<string, string>
  const names = ['process-bigraph', 'bigraph-schema']
  return names.map(n => core[n] ?? installed.get(n)).map((v, i) => (v ? `${names[i]} ${v}` : '')).filter(Boolean)
}

// Where a run ran, and the runs that ran somewhere (docs/plan-webapp-admin.md, step 5c). A run since environment
// versions names its version; one from before names only its simulator, which has a page of its own.
type VersionRef = Schemas['VersionRef']

/** `registry_env@5` */
export function versionLabel(ref: VersionRef): string {
  return `${ref.environment}@${ref.number}`
}

/** The page of the version a run ran in, or of its simulator when it ran before versions. */
export function ranInLink(version: VersionRef | null | undefined, simulatorId: number): { to: string, label: string } {
  return version
    ? { to: `/environments/${encodeURIComponent(version.environment)}/versions/${version.number}`, label: versionLabel(version) }
    : { to: `/simulators/${simulatorId}`, label: `simulator ${simulatorId}` }
}

export type RunsFilter = { environment: string } | { environment_version: VersionRef } | { simulator_id: number }

/** The simulation list filtered to the runs of an environment, a version or a simulator. */
export function runsLink(filter: RunsFilter): string {
  const query = 'environment' in filter
    ? `environment=${encodeURIComponent(filter.environment)}`
    : 'environment_version' in filter
      ? `environment_version=${encodeURIComponent(versionLabel(filter.environment_version))}`
      : `simulator_id=${filter.simulator_id}`
  return `/simulations?${query}`
}
