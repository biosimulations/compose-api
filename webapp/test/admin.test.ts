import { describe, expect, it } from 'vitest'
import type { Schemas } from '../app/composables/useApi'
import { canAdminister, confirmation, creationConfirmation, creationKind, isDigestReference, settled, versionActions } from '../app/utils/admin'

type Version = Schemas['EnvironmentVersion']
const version = (state: Version['state'], extra: Partial<Version> = {}): Version => ({
  database_id: 1, environment_id: 1, environment: 'registry_env', number: 6, state, simulator_id: 300, ...extra
})
const ADMIN = ['environments:admin', 'suites:curate']

describe('environment administration', () => {
  it('is offered only with the capability', () => {
    expect(canAdminister(ADMIN)).toBe(true)
    expect(canAdminister(['suites:curate'])).toBe(false)
    expect(canAdminister(null)).toBe(false)
    expect(versionActions(version('ready'), false, ['simulations:read-all'])).toEqual([])
    expect(versionActions(version('ready'), false, undefined)).toEqual([])
  })

  it('offers what the API allows for each state', () => {
    expect(versionActions(version('ready'), false, ADMIN)).toEqual(['default', 'inspect', 'retire'])
    // the default is never retired, nor made the default again
    expect(versionActions(version('ready'), true, ADMIN)).toEqual(['inspect'])
    expect(versionActions(version('failed'), false, ADMIN)).toEqual(['retire'])
    // still resolving or building: its build will finish it
    expect(versionActions(version('resolving'), false, ADMIN)).toEqual([])
    expect(versionActions(version('building'), false, ADMIN)).toEqual([])
    expect(versionActions(version('retired'), false, ADMIN)).toEqual([])
    // a prebuilt image can be read back whatever its state
    const prebuilt = version('failed', { image: 'ghcr.io/x/y@sha256:' + 'a'.repeat(64) })
    expect(versionActions(prebuilt, false, ADMIN)).toEqual(['inspect', 'retire'])
  })

  it('makes composed versions from a date and prebuilt ones from an image by digest', () => {
    expect(creationKind('shared')).toBe('composed')
    expect(creationKind('mash-up')).toBe('composed')
    expect(creationKind('prebuilt')).toBe('prebuilt')
    expect(isDigestReference('ghcr.io/org/name@sha256:' + '0'.repeat(64))).toBe(true)
    expect(isDigestReference(' ghcr.io/org/name@sha256:' + '0'.repeat(64) + ' ')).toBe(true)
    expect(isDigestReference('ghcr.io/org/name:1.0')).toBe(false)
    expect(isDigestReference('ghcr.io/org/name@sha256:abc')).toBe(false)
  })

  it('stops polling once a version settles', () => {
    expect(['resolving', 'building'].map(s => settled(s as Version['state']))).toEqual([false, false])
    expect(['ready', 'failed', 'retired'].map(s => settled(s as Version['state']))).toEqual([true, true, true])
  })

  it('names the environment, the version and the effect in every dialog', () => {
    const made = confirmation('default', 'registry_env', 6, 5)
    expect(made.title).toBe('Make registry_env@6 the default?')
    expect(made.description).toContain('instead of registry_env@5')
    expect(made.description).toContain('suite runs name their own versions')
    expect(confirmation('default', 'viva-pde-particle', 2, null).description).not.toContain('instead of')
    const retired = confirmation('retire', 'registry_env', 4, 5)
    expect(retired.title).toBe('Retire registry_env@4?')
    expect(retired.danger).toBe(true)
    expect(retired.description).toContain('Runs already recorded keep it')
    expect(confirmation('inspect', 'registry_env', 5, 5).title).toBe('Re-read the contents of registry_env@5?')
    expect(creationConfirmation('registry_env', 'composed', '2026-10-27', '').description).toContain('as of 2026-10-27')
    const image = 'ghcr.io/x/y@sha256:' + 'b'.repeat(64)
    expect(creationConfirmation('viva-pde-particle', 'prebuilt', '', ` ${image}`).description).toContain(`The image ${image} is pulled`)
  })
})
