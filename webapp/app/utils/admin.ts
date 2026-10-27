import type { Schemas } from '~/composables/useApi'

// Environment administration in the webapp (docs/plan-webapp-admin.md, step 6). The API decides who may administer
// (A1: the caller's capabilities) and checks every request again; these only decide what to offer and what each
// confirmation says. Pure, so the pages and their tests share them.

type Version = Schemas['EnvironmentVersion']

export const ENVIRONMENTS_ADMIN = 'environments:admin'

/** Whether the caller may administer environments, as the API says (GET /auth/me). */
export function canAdminister(capabilities: readonly string[] | null | undefined): boolean {
  return (capabilities ?? []).includes(ENVIRONMENTS_ADMIN)
}

export type VersionAction = 'default' | 'retire' | 'inspect'

/**
 * What an administrator may do to a version, as the API allows it: make a ready version the default; retire any
 * version but the default once it has settled (ready or failed; a version still resolving or building would be
 * overwritten by its build); read a version's image back again (a prebuilt one's, or a built one's).
 */
export function versionActions(version: Version, isDefault: boolean, capabilities: readonly string[] | null | undefined): VersionAction[] {
  if (!canAdminister(capabilities)) return []
  const actions: VersionAction[] = []
  if (version.state === 'ready' && !isDefault) actions.push('default')
  if (version.state === 'ready' || (version.image != null && version.state !== 'retired')) actions.push('inspect')
  if (!isDefault && (version.state === 'ready' || version.state === 'failed')) actions.push('retire')
  return actions
}

/** Which way a new version is made: a composed environment's entries at a date, or a prebuilt one's image. */
export function creationKind(kind: string): 'composed' | 'prebuilt' {
  return kind === 'prebuilt' ? 'prebuilt' : 'composed'
}

/** An image reference by digest (`repository@sha256:<64 hex>`): the only kind the API registers. */
export function isDigestReference(image: string): boolean {
  return /^[^\s@]+@sha256:[0-9a-f]{64}$/.test(image.trim())
}

/** A version that will change no more on its own: polling for it stops. */
export function settled(state: Version['state']): boolean {
  return state === 'ready' || state === 'failed' || state === 'retired'
}

export interface Confirmation { title: string, description: string, confirm: string, danger: boolean }

/** What a confirmation dialog says (A3): the environment, the version, and the effect. */
export function confirmation(
  action: VersionAction,
  environment: string,
  number: number,
  defaultNumber: number | null | undefined
): Confirmation {
  const label = `${environment}@${number}`
  switch (action) {
    case 'default':
      return {
        title: `Make ${label} the default?`,
        description: `Runs that name no version will run in ${label}${defaultNumber != null ? ` instead of ${environment}@${defaultNumber}` : ''}. `
          + 'Runs already recorded keep the version they ran in, and suite runs name their own versions, so neither changes.',
        confirm: 'Make it the default',
        danger: false
      }
    case 'retire':
      return {
        title: `Retire ${label}?`,
        description: `${label} will refuse new runs. Runs already recorded keep it as their version, and its images are kept. `
          + 'This cannot be undone from here.',
        confirm: 'Retire it',
        danger: true
      }
    case 'inspect':
      return {
        title: `Read ${label} back again?`,
        description: `Its image is run again in the background to list what it installed and the classes it provides. `
          + 'Nothing else about the version changes.',
        confirm: 'Read it back',
        danger: false
      }
  }
}

/** What the dialog that makes a new version says. */
export function creationConfirmation(environment: string, kind: 'composed' | 'prebuilt', asOf: string, image: string): Confirmation {
  return kind === 'composed'
    ? {
        title: `Make a new version of ${environment}?`,
        description: `Its registry entries are resolved as of ${asOf} and locked together, then its image is built and `
          + 'its compliance cases run. A lock identical to an existing version\'s gives that version instead. '
          + 'It does not become the default until you make it so.',
        confirm: 'Make the version',
        danger: false
      }
    : {
        title: `Register a new version of ${environment}?`,
        description: `The image ${image.trim()} is pulled and read back. An image already registered gives its version `
          + 'instead. It does not become the default until you make it so.',
        confirm: 'Register the image',
        danger: false
      }
}
