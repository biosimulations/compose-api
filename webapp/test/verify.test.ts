import { describe, expect, it } from 'vitest'
import type { Schemas } from '../app/composables/useApi'
import { canVerify, isOracle, oracleName, oracleSides, oracleVerdict, rowOracle, verificationOracle } from '../app/utils/verify'

const verification = (fields: Partial<Schemas['Verification']>): Schemas['Verification'] =>
  ({ verification_id: 1, comparison_id: 7, state: 'completed', simulators: ['copasi', 'tellurium', 'amici'], ...fields }) as Schemas['Verification']

describe('a verification against BioSimulators', () => {
  it('names the solvers it sides with when its simulators agree', () => {
    expect(oracleVerdict('completed', true, ['copasi'])).toMatchObject({ color: 'success', text: 'agrees, with copasi' })
    expect(oracleVerdict('completed', true, ['copasi', 'tellurium'])?.text).toBe('agrees, with copasi and tellurium')
    expect(oracleVerdict('completed', true, [])).toMatchObject({ color: 'error', text: 'agrees, with neither' })
  })

  it('reads a model its simulators disagree on as hard, not as a fault of ours', () => {
    expect(oracleVerdict('completed', false, [])).toMatchObject({ color: 'warning', text: 'disagrees' })
    expect(oracleVerdict('completed', false, [])!.hint).toContain('the model is hard')
    expect(oracleVerdict('completed', null, [])!.text).toBe('no verdict')
  })

  it('reads as going until it completes, and has nothing to say without one', () => {
    expect(oracleVerdict('submitted', null, [])!.text).toBe('verifying')
    expect(oracleVerdict('requested', null, [])!.text).toBe('verifying')
    expect(oracleVerdict('failed', null, [])!.text).toBe('not verified')
    expect(oracleVerdict(null, null, [])).toBeNull()
  })

  it('reads the same from a suite row and from the comparison', () => {
    const row = { source: 's', status: 'complete', excused: false, verification: 'completed', verify_close: true, oracle_agrees_with: ['tellurium'] } as Schemas['SuiteRunRow']
    expect(rowOracle(row)).toEqual(verificationOracle(verification({ verify_close: true, agrees_with: ['tellurium'] })))
  })

  it('may be asked for once the comparison finished and none is going', () => {
    expect(canVerify('differ', [])).toBe(true)
    expect(canVerify('running', [])).toBe(false)
    expect(canVerify('complete', [verification({ state: 'submitted' })])).toBe(false)
    expect(canVerify('complete', [verification({ state: 'failed' })])).toBe(true)
  })
})

describe('the oracle\'s names and counts', () => {
  it('names a simulator by its version, and tells oracle references from legacy runs', () => {
    expect(oracleName('biosimulators:copasi:4.45.296')).toBe('copasi 4.45.296')
    expect(oracleName('biosimulations:copasi')).toBe('biosimulations:copasi')
    expect(isOracle('biosimulators:amici:0.34.2')).toBe(true)
    expect(isOracle('biosimulations:copasi')).toBe(false)
  })

  it('reads the summary\'s per-solver counts', () => {
    expect(oracleSides({ agree: 3, oracle_agrees: 2, oracle_agrees_with_copasi: 2, oracle_agrees_with_tellurium: 0 }))
      .toEqual([['copasi', 2], ['tellurium', 0]])
  })
})
