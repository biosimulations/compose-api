import { describe, expect, it } from 'vitest'
import type { Dataset } from '../app/composables/useApi'
import { datasetGlyph, isComposite, isFigure } from '../app/viewers/kinds'

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

describe('a dataset\'s glyph', () => {
  // simulation 8823's datasets (a SED-ML run on Tellurium), and a viva-pde-particle run's bundle
  const glyph = (fields: Partial<Dataset>) => datasetGlyph(dataset(fields)).icon
  it('names what each one is', () => {
    expect(glyph({ kind: 'input', path: 'x.omex', media_type: 'application/zip' })).toBe('i-lucide-file-input')
    expect(glyph({ kind: 'json', path: 'output/plots/simulation_1/Figure_3a.plotly.json', media_type: 'application/json' })).toBe('i-lucide-chart-spline')
    expect(glyph({ kind: 'table', path: 'output/results.csv', media_type: 'text/csv' })).toBe('i-lucide-table')
    expect(glyph({ kind: 'log', path: 'job.out', media_type: 'text/plain' })).toBe('i-lucide-file-terminal')
    expect(glyph({ kind: 'archive', path: 'results.zip', media_type: 'application/zip' })).toBe('i-lucide-file-archive')
    expect(glyph({ kind: 'sedml-omex', path: 'source.omex', media_type: 'application/zip' })).toBe('i-lucide-file-archive')
    expect(glyph({ kind: 'file', path: 'output/task_1.pbg', media_type: 'application/json' })).toBe('i-lucide-workflow')
    expect(glyph({ kind: 'file', path: 'output/task_1.pblang', media_type: 'application/octet-stream' })).toBe('i-lucide-file-code')
    expect(glyph({ kind: 'file', path: 'output/model.xml', media_type: 'text/xml' })).toBe('i-lucide-file-code')
    expect(glyph({ kind: 'results-bundle', path: 'output/run.fenics', media_type: 'application/vnd.zarr' })).toBe('i-lucide-box')
    expect(glyph({ path: 'output/frame.png', media_type: 'image/png' })).toBe('i-lucide-image')
    expect(glyph({ path: 'output/blob', media_type: 'application/octet-stream' })).toBe('i-lucide-file')
  })
})
