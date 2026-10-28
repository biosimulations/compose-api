import { describe, expect, it } from 'vitest'
import { figureTable, parseTable, tableTraces, traceValues } from '../app/viewers/tabular'

describe('a delimited table', () => {
  it('plots its numeric columns against its first', () => {
    const t = parseTable('time, A, label, B\n0, 1, a, 2\n1, 3, b, 4\n')!
    expect(t.header).toEqual(['time', 'A', 'label', 'B'])
    expect(tableTraces(t)!.map(x => x.name)).toEqual(['A', 'B'])
    expect(tableTraces(parseTable('name,v\na,1\nb,2')!)).toBeNull() // a non-numeric first column
    expect(tableTraces(parseTable('t,v\n0,1')!)).toBeNull() // one row
  })
})

describe('a Plotly figure as a table', () => {
  it('is one column per trace when they share their x (as SED-ML plots do)', () => {
    const t = figureTable({
      data: [
        { type: 'scatter', name: 'Sic1', x: [0, 0.7, 1.4], y: [0.1, 0.2, 0.3] },
        { type: 'scatter', name: 'SBF', x: [0, 0.7, 1.4], y: [1, 2, 3] }
      ],
      layout: { xaxis: { title: { text: 'time' } } }
    })
    expect(t).toEqual({ header: ['time', 'Sic1', 'SBF'], rows: [['0', '0.1', '1'], ['0.7', '0.2', '2'], ['1.4', '0.3', '3']] })
  })

  it('is one row per point when their x differ, and names an unnamed trace', () => {
    const t = figureTable({ data: [{ name: 'a', x: [0, 1], y: [5, 6] }, { x: [0, 2], y: [7, null] }] })
    expect(t).toEqual({ header: ['trace', 'x', 'y'], rows: [['a', '0', '5'], ['a', '1', '6'], ['trace 2', '0', '7'], ['trace 2', '2', '']] })
  })

  it('reads plotly.py\'s typed arrays, and has no table without x/y series', () => {
    const f8 = (values: number[]) => ({ dtype: 'f8', bdata: Buffer.from(new Float64Array(values).buffer).toString('base64') })
    expect(traceValues(f8([1.5, 2.5]))).toEqual([1.5, 2.5])
    expect(figureTable({ data: [{ name: 'v', x: f8([0, 1]), y: f8([2, 3]) }] })!.rows).toEqual([['0', '2'], ['1', '3']])
    expect(figureTable({ data: [{ type: 'heatmap', z: [[1, 2], [3, 4]] }] })).toBeNull()
    expect(traceValues([[1, 2]])).toBeNull()
  })
})
