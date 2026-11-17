import { describe, expect, it } from 'vitest'
import { toleranceText } from '../app/utils/tolerances'

describe('toleranceText', () => {
  it('states the scaled absolute tolerance of the platform default', () => {
    expect(toleranceText({ tolerances: { rel_tol: 0.0001, abs_tol_min: 0.001, abs_tol_scale: 0.00001 } }))
      .toBe('rtol 0.0001, atol max(0.001, 0.00001·max|a|, 0.00001·max|b|)')
  })

  it('states a case\'s own tolerances and where they came from', () => {
    expect(toleranceText({
      tolerances: { rel_tol: 0.0001, abs_tol_min: 1e-7, abs_tol_scale: 0 },
      tolerances_from: 'sbml-test-suite:3.5.0/00001',
    })).toBe('rtol 0.0001, atol 1e-7 (from sbml-test-suite:3.5.0/00001)')
  })

  it('says nothing without tolerances', () => {
    expect(toleranceText(null)).toBe('')
    expect(toleranceText({})).toBe('')
  })
})
