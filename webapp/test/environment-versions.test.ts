import { describe, expect, it } from 'vitest'
import type { Schemas } from '../app/composables/useApi'
import { corePackages, packageChanges, parseInstalled, ranInLink, runsLink, specEntries, stateColor } from '../app/utils/environments'

// registry_env@1 (pbest's uv image) against @4 (composed with pixi), as their read-backs listed them (2026-10-26).
const v1 = 'process-bigraph==1.0.5\nbigraph-schema==1.6.0\nlibvcell==0.0.22\npbest==0.6.5\nCopasi_Basico==0.86\n'
const v4 = 'process-bigraph==1.9.1\nbigraph-schema==1.8.1\nlibvcell==0.0.24\ncopasi-basico==0.86\n\n'

describe('environment versions', () => {
  it('reads an installed list by normalized name', () => {
    const installed = parseInstalled(v1)
    expect(installed.get('copasi-basico')).toBe('0.86')
    expect(installed.size).toBe(5)
    expect(parseInstalled(null).size).toBe(0)
  })

  it('lists what changed, was added or removed between two versions', () => {
    expect(packageChanges(parseInstalled(v1), parseInstalled(v4))).toEqual([
      { name: 'bigraph-schema', from: '1.6.0', to: '1.8.1' },
      { name: 'libvcell', from: '0.0.22', to: '0.0.24' },
      { name: 'pbest', from: '0.6.5', to: null },
      { name: 'process-bigraph', from: '1.0.5', to: '1.9.1' }
    ])
  })

  it('says how each entry of a composed version was installed', () => {
    const spec = { entries: [
      { id: 'pbsim-common', install: { git: 'https://github.com/biosimulations/pbsim_common', commit: 'c6c18044912f8bf9' } },
      { id: 'tellurium', install: { pypi: 'tellurium', version: '2.2.13.1' } },
      { id: 'readdy', install: null, conda: { readdy: '==2.0.13' } }
    ] }
    expect(specEntries(spec)).toEqual([
      { id: 'pbsim-common', install: 'biosimulations/pbsim_common@c6c1804' },
      { id: 'tellurium', install: 'tellurium==2.2.13.1' },
      { id: 'readdy', install: 'conda readdy==2.0.13' }
    ])
    expect(specEntries(null)).toEqual([])
  })

  it('takes the core from a composed spec, else from what was installed', () => {
    const composed = { spec: { core: { 'process-bigraph': '1.9.1', 'bigraph-schema': '1.8.1' } } } as unknown as Schemas['EnvironmentVersion']
    expect(corePackages(composed, new Map())).toEqual(['process-bigraph 1.9.1', 'bigraph-schema 1.8.1'])
    const shared = { spec: {} } as unknown as Schemas['EnvironmentVersion']
    expect(corePackages(shared, parseInstalled(v1))).toEqual(['process-bigraph 1.0.5', 'bigraph-schema 1.6.0'])
    expect(stateColor('failed')).toBe('error')
  })
})

describe('where runs ran', () => {
  const v5 = { environment: 'registry_env', number: 5 }

  it('links a run to its version, or to its simulator when it ran before versions', () => {
    expect(ranInLink(v5, 290)).toEqual({ to: '/environments/registry_env/versions/5', label: 'registry_env@5' })
    expect(ranInLink(null, 132)).toEqual({ to: '/simulators/132', label: 'legacy environment 132' })
    expect(ranInLink({ environment: 'a b', number: 1 }, 1).to).toBe('/environments/a%20b/versions/1')
  })

  it('links an environment, a version or a simulator to the runs that used it', () => {
    expect(runsLink({ environment: 'registry_env' })).toBe('/simulations?environment=registry_env')
    expect(runsLink({ environment_version: v5 })).toBe('/simulations?environment_version=registry_env%405')
    expect(runsLink({ simulator_id: 132 })).toBe('/simulations?simulator_id=132')
  })
})
