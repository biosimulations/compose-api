import { describe, expect, it } from 'vitest'
import type { Schemas } from '../app/composables/useApi'
import { appliesTo, canCurate, clearConfirmation, editConfirmation, jobCount, knownCategories, markable, markConfirmation, problemToClear, validMark, rowProblems, rowVerdict, runVersions, suiteEnvironments, versionChoices, versionParameters } from '../app/utils/suites'

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

describe('curating known problems', () => {
  it('is offered only with the capability', () => {
    expect(canCurate(['suites:curate'])).toBe(true)
    expect(canCurate(['environments:admin'])).toBe(false)
    expect(canCurate(undefined)).toBe(false)
  })

  it('marks rows that finished without agreeing, and clears the problem a resolved solver had', () => {
    expect(markable(row({ close: false }))).toBe(true)
    expect(markable(row({ status: 'incomplete', close: null }))).toBe(true)
    expect(markable(row({ close: true, status: 'complete' }))).toBe(false)
    expect(markable(row({ status: 'running' }))).toBe(false)
    expect(markable(row({ close: false, expected: 'whole source excused' }))).toBe(false)
    const open = problem({ problem_id: 7 })
    const cleared = problem({ problem_id: 8, cleared_run: 3 })
    expect(problemToClear(row({}), 'vcell', [cleared, open])?.problem_id).toBe(7)
    expect(problemToClear(row({}), 'copasi', [open])).toBeUndefined()
  })

  it('suggests the categories in use and checks a mark as the API does', () => {
    expect(knownCategories([problem({ category: 'DELAY' }), problem({ category: 'DELAY' }), problem({})])).toEqual(['DELAY', 'NONINTEGER_STOICH'])
    expect(validMark(' DELAY ', 'delays are not supported')).toBe(true)
    expect(validMark('', 'x')).toBe(false)
    expect(validMark('x', '   ')).toBe(false)
    expect(validMark('x'.repeat(65), 'r')).toBe(false)
  })

  it('says what each change does to which runs', () => {
    expect(markConfirmation('biomodels:BIOMD0000000039', 'vcell', 4).description).toContain('vcell on this model is excused from run 4 on')
    expect(markConfirmation('s', null, 4).description).toMatch(/^Every solver on this model/)
    const c = clearConfirmation(problem({ problem_id: 7 }), 5)
    expect(c.title).toBe('Clear problem 7 at run 5?')
    expect(c.description).toContain('runs before 5 still excuse it')
    expect(c.danger).toBe(true)
    expect(editConfirmation(problem({ problem_id: 7 })).description).toContain('does not change')
  })
})
