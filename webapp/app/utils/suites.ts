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
