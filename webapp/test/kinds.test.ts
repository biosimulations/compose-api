import { describe, expect, it } from 'vitest'
import type { Dataset } from '../app/composables/useApi'
import { isComposite, isFigure } from '../app/viewers/kinds'

const dataset = (fields: Partial<Dataset>): Dataset =>
  ({ id: 'd', simulation_id: 1, kind: 'output', path: 'output/x', display_name: 'x', available: true, ...fields }) as Dataset

describe('a simulation\'s figures', () => {
  it('are the outputs a visualization is registered for', () => {
    expect(isFigure(dataset({ path: 'output/plots/sim.sedml/plot1.plotly.json', media_type: 'application/json' }))).toBe(true)
    expect(isFigure(dataset({ path: 'output/frame.png', media_type: 'image/png' }))).toBe(true)
    expect(isFigure(dataset({ kind: 'results-bundle', path: 'output/run.fenics', media_type: 'application/vnd.zarr' }))).toBe(true)
  })

  it('leave out tables, text, results files and the input, which have viewers of their own', () => {
    expect(isFigure(dataset({ path: 'output/report.csv', media_type: 'text/csv' }))).toBe(false)
    expect(isFigure(dataset({ path: 'output/state.pbg', media_type: 'application/json' }))).toBe(false)
    expect(isFigure(dataset({ kind: 'results', path: 'results.zip', media_type: 'application/zip' }))).toBe(false)
    const input = dataset({ kind: 'input', path: 'experiment.omex', media_type: 'application/zip' })
    expect(isFigure(input)).toBe(false)
    expect(isComposite(input)).toBe(true)
  })
})
