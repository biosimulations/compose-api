import type { Schemas } from '~/composables/useApi'

// A suite run's rows against the suite's known problems (docs/plan-known-problems.md): what each row's verdict reads,
// and each solver's problem there with its category. Pure, so the page and its tests share them.

type Row = Schemas['SuiteRunRow']
type Problem = Schemas['KnownProblem']
type BadgeColor = 'success' | 'error' | 'warning' | 'neutral'

export interface Verdict { color: BadgeColor, text: string, hint?: string }

/** The row's verdict: running, agree, excused (it fails or differs only through solvers with a known problem), or
 * differ. A row whose whole source is expected keeps its raw verdict; its note says why. */
export function rowVerdict(row: Row): Verdict {
  if (row.status === 'running') return { color: 'neutral', text: 'running' }
  if (row.close === true) return { color: 'success', text: 'agree' }
  if (row.excused) {
    return { color: 'neutral', text: 'excused', hint: 'Only solvers with a known problem fail or differ; the others agree' }
  }
  if (row.close === false) return { color: 'error', text: 'differ' }
  return { color: 'neutral', text: '—' }
}

/** Whether a problem applies to run ``number``: open, or cleared by a later run (K2). */
export function appliesTo(problem: Problem, number: number): boolean {
  return problem.cleared_run == null || problem.cleared_run > number
}

export interface RowProblem { solver: string, reason: string, category?: string, resolved: boolean }

/** Each solver's known problem on the row, with its category from the suite's problems, and whether the solver now
 * completes and agrees (resolved: the problem can be cleared). */
export function rowProblems(row: Row, problems: Problem[], number: number): RowProblem[] {
  const resolved = new Set(row.resolved ?? [])
  return Object.entries(row.known_problems ?? {}).map(([solver, reason]) => ({
    solver,
    reason,
    category: problems.find(p => p.source === row.source && p.solver === solver && appliesTo(p, number))?.category,
    resolved: resolved.has(solver)
  })).sort((a, b) => a.solver.localeCompare(b.solver))
}

// Running a suite in chosen environment versions (docs/plan-webapp-admin.md, step 5; A4).

type Suite = Schemas['Suite']
type Solver = Schemas['Solver']
type Version = Schemas['EnvironmentVersion']

/** The solvers a suite runs: the ones it names, or every solver when it names none (as the API chooses them). */
export function suiteSolvers(suite: Suite, solvers: Solver[]): Solver[] {
  return suite.solvers?.length ? solvers.filter(s => suite.solvers!.includes(s.id)) : solvers
}

/** The environments those solvers run in, sorted: each needs a version named when the suite runs. */
export function suiteEnvironments(suite: Suite, solvers: Solver[]): string[] {
  return [...new Set(suiteSolvers(suite, solvers).map(s => s.environment))].sort()
}

/** How many simulations a run submits, about: one per source and solver. */
export function jobCount(suite: Suite, solvers: Solver[]): number {
  return suite.sources.length * suiteSolvers(suite, solvers).length
}

export interface VersionChoice { label: string, value: string }

/** What a suite run may name for one environment: its default (first), then each ready version, newest first. */
export function versionChoices(environment: string, versions: Version[], defaultNumber: number | null | undefined): VersionChoice[] {
  const ready = versions.filter(v => v.state === 'ready').sort((a, b) => b.number - a.number)
  return [
    { label: `default${defaultNumber != null ? ` (@${defaultNumber})` : ''}`, value: 'default' },
    ...ready.map(v => ({ label: `@${v.number}${v.number === defaultNumber ? ' (the default)' : ''}`, value: String(v.number) }))
  ]
}

/** The `environment_version` parameters for the chosen versions: `name@number`, or `name@default`. */
export function versionParameters(chosen: Record<string, string>): string[] {
  return Object.entries(chosen).sort(([a], [b]) => a.localeCompare(b)).map(([env, v]) => `${env}@${v}`)
}

/** A run's versions as links' labels, sorted: `registry_env@5`; none for a run started before versions. */
export function runVersions(versions: Record<string, number> | null | undefined): Schemas['VersionRef'][] {
  return Object.entries(versions ?? {}).sort(([a], [b]) => a.localeCompare(b)).map(([environment, number]) => ({ environment, number }))
}
