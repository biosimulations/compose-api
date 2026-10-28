import Papa from 'papaparse'

// Tables and plots made from each other (docs/plan-viewers.md): a delimited table plotted, and a Plotly figure's data
// as a table. Pure, so the viewers (TableViewer, TablePlotViewer, FigureTableViewer) and their tests share them.

export interface Table { header: string[], rows: string[][] }
export type Trace = Record<string, unknown>

/** A delimited text file as its header and rows; null when it has no header. */
export function parseTable(text: string): Table | null {
  const parsed = Papa.parse<string[]>(text.trim(), { skipEmptyLines: true })
  const [header, ...rows] = parsed.data
  return header ? { header: header.map(h => h.trim()), rows } : null
}

/** A table as lines: the first column as x, every other all-numeric column as a line. Null when there is nothing to
 * plot (a non-numeric first column, fewer than two rows, or no numeric column besides it). */
export function tableTraces(t: Table): Trace[] | null {
  if (t.header.length < 2 || t.rows.length < 2) return null
  const numeric = (i: number) => t.rows.every(r => r[i] !== undefined && r[i] !== '' && !Number.isNaN(Number(r[i])))
  if (!numeric(0)) return null
  const x = t.rows.map(r => Number(r[0]))
  const ys = t.header.map((h, i) => ({ h, i })).slice(1).filter(({ i }) => numeric(i))
  if (!ys.length) return null
  return ys.map(({ h, i }) => ({ type: 'scatter', mode: 'lines', name: h, x, y: t.rows.map(r => Number(r[i])) }))
}

const TYPED: Record<string, (b: ArrayBuffer) => ArrayLike<number>> = {
  f8: b => new Float64Array(b), f4: b => new Float32Array(b),
  i4: b => new Int32Array(b), i2: b => new Int16Array(b), i1: b => new Int8Array(b),
  u4: b => new Uint32Array(b), u2: b => new Uint16Array(b), u1: b => new Uint8Array(b)
}

/** A trace's values: a plain array, or Plotly's typed-array encoding (`{dtype, bdata}`, base64, as plotly.py 6 writes
 * it). Null for anything else (a 2-D array, an unknown dtype). */
export function traceValues(v: unknown): (string | number | null)[] | null {
  if (Array.isArray(v)) return v.every(x => x === null || typeof x === 'number' || typeof x === 'string') ? v : null
  if (v && typeof v === 'object' && 'bdata' in v && 'dtype' in v) {
    const { dtype, bdata, shape } = v as { dtype: string, bdata: string, shape?: unknown }
    const make = TYPED[dtype]
    if (!make || (typeof shape === 'string' && shape.includes(','))) return null
    const bytes = Uint8Array.from(atob(bdata), c => c.charCodeAt(0))
    return Array.from(make(bytes.buffer))
  }
  return null
}

const cell = (v: string | number | null | undefined) => (v == null ? '' : String(v))
const sameValues = (a: unknown[], b: unknown[]) => a.length === b.length && a.every((v, i) => v === b[i])

/** A Plotly figure's data as a table, when its traces are x/y series: one column for x and one per trace when they all
 * share their x values, otherwise one row per point (trace, x, y). Null when no trace has both. */
export function figureTable(figure: { data: Trace[], layout?: Record<string, unknown> }): Table | null {
  const series = figure.data.flatMap((t, i) => {
    const x = traceValues(t.x)
    const y = traceValues(t.y)
    return x && y && x.length === y.length ? [{ name: typeof t.name === 'string' && t.name ? t.name : `trace ${i + 1}`, x, y }] : []
  })
  if (!series.length) return null
  const axis = (figure.layout?.xaxis as { title?: { text?: unknown } | string } | undefined)?.title
  const xName = (typeof axis === 'string' ? axis : typeof axis?.text === 'string' ? axis.text : '') || 'x'
  const first = series[0]!
  if (series.every(s => sameValues(s.x, first.x))) {
    return {
      header: [xName, ...series.map(s => s.name)],
      rows: first.x.map((x, i) => [cell(x), ...series.map(s => cell(s.y[i]))])
    }
  }
  return { header: ['trace', xName, 'y'], rows: series.flatMap(s => s.x.map((x, i) => [s.name, cell(x), cell(s.y[i])])) }
}
