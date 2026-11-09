// A comparison's tolerances as the page states them (docs/plan-sedml.md D4; docs/plan-sbml-test-suite.md S4). Pure, so
// the page and its tests share it.

export interface Tolerances { rel_tol?: number, abs_tol_min?: number, abs_tol_scale?: number }

/** `rtol 0.0001, atol 1e-7`, or with a scaled term `atol max(0.001, 1e-5·max|a|, 1e-5·max|b|)`; and where they came
 * from when they are a source's own (an SBML Test Suite case's), not the suite's or the request's. */
export function toleranceText(settings: { tolerances?: Tolerances, tolerances_from?: string } | null | undefined): string {
  const t = settings?.tolerances
  if (!t) return ''
  const min = t.abs_tol_min ?? 0
  const scale = t.abs_tol_scale ?? 0
  const atol = scale ? `max(${min}, ${scale}·max|a|, ${scale}·max|b|)` : `${min}`
  const from = settings?.tolerances_from ? ` (from ${settings.tolerances_from})` : ''
  return `rtol ${t.rel_tol}, atol ${atol}${from}`
}
