import type { Schemas } from '~/composables/useApi'
import type { Verdict } from '~/utils/suites'

// The verify oracle on the pages (docs/plan-verify-oracle.md, V5): what a verification against BioSimulators'
// simulators reads, on a suite run's row and on its comparison. Pure, so the pages and their tests share them.

type Row = Schemas['SuiteRunRow']
type Verification = Schemas['Verification']

const ORIGIN = 'biosimulators:'

/** `biosimulators:copasi:4.45.296` as `copasi 4.45.296`; another origin as it is. */
export function oracleName(origin: string): string {
  if (!origin.startsWith(ORIGIN)) return origin
  const [name, version] = origin.slice(ORIGIN.length).split(':')
  return version ? `${name} ${version}` : name!
}

/** Whether a reference came from a verification (BioSimulators' simulators), not a legacy biosimulations.org run. */
export function isOracle(origin: string): boolean {
  return origin.startsWith(ORIGIN)
}

/** What a verification reads: still going, failed, or which way BioSimulators' simulators went. They agree with each
 * other, and with the solvers named; or they disagree with each other, so the model is hard and no one solver is at
 * fault (D1). */
export function oracleVerdict(state: string | null | undefined, verifyClose: boolean | null | undefined, agreesWith: string[]): Verdict | null {
  if (!state) return null
  if (state === 'requested' || state === 'submitted') return { color: 'neutral', text: 'verifying', hint: 'BioSimulators is running it' }
  if (state === 'failed') return { color: 'warning', text: 'not verified', hint: 'The verification failed; it can be asked for again' }
  const sides = agreesWith.length ? `, with ${agreesWith.join(' and ')}` : ''
  if (verifyClose === true) {
    return {
      color: agreesWith.length ? 'success' : 'error',
      text: agreesWith.length ? `agrees${sides}` : 'agrees, with neither',
      hint: 'BioSimulators\' simulators agree with each other' + (agreesWith.length ? sides : ', but not with any of our solvers')
    }
  }
  if (verifyClose === false) return { color: 'warning', text: 'disagrees', hint: 'BioSimulators\' simulators disagree with each other: the model is hard' + sides }
  return { color: 'neutral', text: 'no verdict', hint: 'Fewer than two of BioSimulators\' simulators produced results' + sides }
}

export const rowOracle = (row: Row): Verdict | null => oracleVerdict(row.verification, row.verify_close, row.oracle_agrees_with ?? [])
export const verificationOracle = (v: Verification): Verdict | null => oracleVerdict(v.state, v.verify_close, v.agrees_with ?? [])

/** A verification may be asked for once the comparison has finished and none is queued or running. */
export function canVerify(status: string | undefined, verifications: Verification[]): boolean {
  return !!status && status !== 'running' && !verifications.some(v => v.state === 'requested' || v.state === 'submitted')
}

/** The summary's `oracle_agrees_with_<solver>` counts, by solver. */
export function oracleSides(summary: Record<string, number>): [string, number][] {
  const prefix = 'oracle_agrees_with_'
  return Object.entries(summary).filter(([k]) => k.startsWith(prefix)).map(([k, n]) => [k.slice(prefix.length), n])
}
