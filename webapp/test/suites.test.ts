import { describe, expect, it } from 'vitest'
import type { Schemas } from '../app/composables/useApi'
import { appliesTo, jobCount, rowProblems, rowVerdict, runVersions, suiteEnvironments, versionChoices, versionParameters } from '../app/utils/suites'

// Rows as run 4 of biomodels-curated-300 shows them once its VCell import failures are known problems (2026-10-26).
const row = (fields: Partial<Schemas['SuiteRunRow']>): Schemas['SuiteRunRow'] =>
  ({ source: 'biomodels:BIOMD0000000039', status: 'incomplete', excused: false, ...fields }) as Schemas['SuiteRunRow']
const problem = (fields: Partial<Schemas['KnownProblem']>): Schemas['KnownProblem'] =>
  ({ problem_id: 1, suite: 's', source: 'biomodels:BIOMD0000000039', solver: 'vcell', category: 'NONINTEGER_STOICH',
    reason: 'Non-integer stoichiometry', marked_by: 'auth0|x', ...fields }) as Schemas['KnownProblem']

describe('a suite run row against its known problems', () => {
  it('reads excused, not differ, when only a solver with a known problem fails', () => {
    expect(rowVerdict(row({ close: false, excused: true })).text).toBe('excused')
    expect(rowVerdict(row({ close: false })).text).toBe('differ')
    expect(rowVerdict(row({ close: true, status: 'complete' })).text).toBe('agree')
    expect(rowVerdict(row({ status: 'running' })).text).toBe('running')
  })

  it('lists each solver\'s problem with the category that applies to the run, and whether it is resolved', () => {
    const problems = [
      problem({ problem_id: 1, category: 'DELAY', cleared_run: 3 }), // cleared before run 4: not this run's
      problem({ problem_id: 2, category: 'NONINTEGER_STOICH' })
    ]
    const r = row({ known_problems: { vcell: 'Non-integer stoichiometry', tellurium: 'delay' }, resolved: ['tellurium'] })
    expect(rowProblems(r, problems, 4)).toEqual([
      { solver: 'tellurium', reason: 'delay', category: undefined, resolved: true },
      { solver: 'vcell', reason: 'Non-integer stoichiometry', category: 'NONINTEGER_STOICH', resolved: false }
    ])
    expect(rowProblems(r, problems, 2)[1]!.category).toBe('DELAY')
  })

  it('applies a problem to the runs before the one that cleared it', () => {
    expect(appliesTo(problem({}), 9)).toBe(true)
    expect(appliesTo(problem({ cleared_run: 4 }), 3)).toBe(true)
    expect(appliesTo(problem({ cleared_run: 4 }), 4)).toBe(false)
  })
})

describe('running a suite in chosen versions', () => {
  const solver = (id: string, environment: string) =>
    ({ id, name: id, role: 'TimeCourseSolver', environment, address: `local:x.${id}`, algorithms: ['KISAO_0000019'] }) as Schemas['Solver']
  const solvers = [solver('copasi', 'registry_env'), solver('tellurium', 'registry_env'), solver('vcell', 'registry_env'), solver('pde', 'viva-pde-particle')]
  const suite = (fields: Partial<Schemas['Suite']>) => ({ name: 's', description: '', sources: ['a', 'b', 'c'], ...fields }) as Schemas['Suite']
  const version = (number: number, state: Schemas['EnvironmentVersion']['state']) =>
    ({ database_id: number, environment_id: 1, environment: 'registry_env', number, state, simulator_id: number }) as Schemas['EnvironmentVersion']

  it('needs a version of each environment its solvers run in', () => {
    expect(suiteEnvironments(suite({ solvers: ['copasi', 'tellurium'] }), solvers)).toEqual(['registry_env'])
    expect(suiteEnvironments(suite({}), solvers)).toEqual(['registry_env', 'viva-pde-particle'])
    expect(jobCount(suite({ solvers: ['copasi', 'tellurium'] }), solvers)).toBe(6)
    expect(jobCount(suite({}), solvers)).toBe(12)
  })

  it('offers the default first, then ready versions newest first', () => {
    const choices = versionChoices('registry_env', [version(1, 'ready'), version(3, 'failed'), version(5, 'ready'), version(4, 'ready')], 5)
    expect(choices.map(c => c.value)).toEqual(['default', '5', '4', '1'])
    expect(choices[0]!.label).toBe('default (@5)')
    expect(choices[1]!.label).toBe('@5 (the default)')
    expect(versionChoices('x', [], null)).toEqual([{ label: 'default', value: 'default' }])
  })

  it('names every environment in the request, and reads the versions of a run back', () => {
    expect(versionParameters({ 'viva-pde-particle': 'default', 'registry_env': '4' })).toEqual(['registry_env@4', 'viva-pde-particle@default'])
    expect(runVersions({ registry_env: 5 })).toEqual([{ environment: 'registry_env', number: 5 }])
    expect(runVersions(undefined)).toEqual([])
  })
})
