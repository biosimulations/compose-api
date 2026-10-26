import { describe, expect, it } from 'vitest'
import type { Schemas } from '../app/composables/useApi'
import { appliesTo, rowProblems, rowVerdict } from '../app/utils/suites'

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
