import * as zarr from 'zarrita'

/**
 * Reads a vcell-fenics results bundle (ADR 010: a zarr v2 group) chunk by chunk, so a viewer fetches one time row at a
 * time and the server only serves files (docs/plan-viewers.md). Shared by every bundle viewer.
 *
 * The root `.zattrs` holds the manifest; `times` is authoritative (arrays are preallocated to `planned_times`), and a
 * running simulation replaces it atomically after each row, so `refresh()` while `status == 'running'` follows a live
 * run. Remeshed bundles (more than one segment) are read from their first segment only for now.
 */

export type Readable = zarr.Readable

export interface BundleDomain {
  kind: 'volume' | 'membrane'
  dim: number
  gdim: number
  mesh: string
  n_points: number
  n_cells: number
  cell_type: number
}

export interface BundleVariable {
  name: string
  domain: string
  path: string
  stats?: string
  assoc?: string
  element?: string
}

export interface BundleManifest {
  schema: number
  status: 'running' | 'completed' | 'failed'
  progress?: number
  message?: string | null
  times: number[]
  planned_times?: number[]
  domains: Record<string, BundleDomain>
  variables: BundleVariable[]
  stats_columns?: string[]
  segments?: { index: number, t0: number, count: number, motion: string, prefix: string }[]
  source?: Record<string, unknown>
}

/** The optional web extension (written by producers for browser viewers): a precomputed triangle surface per domain. */
export interface WebExtension {
  schema: number
  surfaces: Record<string, { points: string, triangles: string }>
}

export interface Stats {
  times: number[]
  mean: number[]
  total: number[]
  min: number[]
  max: number[]
}

export interface Surface {
  points: Float32Array // (N, 3) flattened, in mesh point order: rows index it directly
  triangles: Uint32Array // (M, 3) flattened
}

const decoder = new TextDecoder()

/** A zarrita store over plain GETs of `<base>/<key>` with the caller's fetch (it adds the auth header). */
export function httpStore(base: string, fetchFn: typeof fetch = fetch): Readable {
  const root = base.replace(/\/$/, '')
  return {
    async get(key: string) {
      const r = await fetchFn(`${root}${key}`, { cache: 'no-cache' })
      if (r.status === 404) return undefined
      if (!r.ok) throw new Error(`GET ${key}: ${r.status}`)
      return new Uint8Array(await r.arrayBuffer())
    }
  }
}

export class Bundle {
  private readonly arrays = new Map<string, Promise<zarr.Array<zarr.DataType, Readable>>>()
  private readonly root: zarr.Location<Readable>

  private constructor(readonly store: Readable, public manifest: BundleManifest, public attrs: Record<string, unknown>) {
    this.root = zarr.root(store)
  }

  static async open(store: Readable): Promise<Bundle> {
    const attrs = await readAttrs(store)
    return new Bundle(store, manifestOf(attrs), attrs)
  }

  /** Re-read the manifest: a running simulation appends rows. True when it changed. */
  async refresh(): Promise<boolean> {
    const attrs = await readAttrs(this.store)
    const next = manifestOf(attrs)
    const changed = next.times.length !== this.manifest.times.length || next.status !== this.manifest.status
    this.manifest = next
    this.attrs = attrs
    return changed
  }

  get times(): number[] {
    return this.manifest.times
  }

  get live(): boolean {
    return this.manifest.status === 'running'
  }

  get web(): WebExtension | undefined {
    return this.attrs.web as WebExtension | undefined
  }

  get particleSpecies(): string[] {
    const p = this.attrs.particles as { species?: Record<string, unknown> } | undefined
    return Object.keys(p?.species ?? {})
  }

  variablesOf(domain?: string): BundleVariable[] {
    return this.manifest.variables.filter(v => !domain || v.domain === domain)
  }

  private array(path: string) {
    let a = this.arrays.get(path)
    if (!a) {
      a = zarr.open.v2(this.root.resolve(path), { kind: 'array' })
      this.arrays.set(path, a)
    }
    return a
  }

  /** One variable at time row `k`: one chunk, one request. */
  async row(variable: BundleVariable, k: number): Promise<Float64Array> {
    const arr = await this.array(variable.path)
    const { data } = await zarr.get(arr, [k, null])
    return Float64Array.from(data as ArrayLike<number>)
  }

  /** mean/total/min/max over the recorded rows, from the bundle's stats array (no field rows are read). */
  async stats(variable: BundleVariable): Promise<Stats> {
    const n = this.times.length
    const out: Stats = { times: this.times.slice(0, n), mean: [], total: [], min: [], max: [] }
    if (!variable.stats || n === 0) return out
    const arr = await this.array(variable.stats)
    const { data } = await zarr.get(arr, [zarr.slice(0, n), null])
    const values = data as ArrayLike<number>
    for (let k = 0; k < n; k++) {
      out.mean.push(values[k * 4]!)
      out.total.push(values[k * 4 + 1]!)
      out.min.push(values[k * 4 + 2]!)
      out.max.push(values[k * 4 + 3]!)
    }
    return out
  }

  /** Global value range of a variable over all recorded rows, from its stats. */
  async range(variable: BundleVariable): Promise<[number, number]> {
    const s = await this.stats(variable)
    const lo = Math.min(...s.min.filter(Number.isFinite))
    const hi = Math.max(...s.max.filter(Number.isFinite))
    return Number.isFinite(lo) && Number.isFinite(hi) ? [lo, hi] : [0, 1]
  }

  /** Particle positions of species `sp` at row `k`, (count, 3) flattened. */
  async particles(sp: string, k: number): Promise<Float64Array> {
    const count = await this.array(`particles/${sp}/count`)
    const n = Number(((await zarr.get(count, [k, 0])) as unknown as number))
    if (!n) return new Float64Array()
    const xyz = await this.array(`particles/${sp}/xyz`)
    const { data } = await zarr.get(xyz, [k, zarr.slice(0, n), null])
    return Float64Array.from(data as ArrayLike<number>)
  }

  /** The domain's precomputed surface from the web extension, or undefined if the producer wrote none. */
  async surface(domain: string): Promise<Surface | undefined> {
    const entry = this.web?.surfaces?.[domain]
    if (!entry) return undefined
    const [pts, tris] = await Promise.all([this.array(entry.points), this.array(entry.triangles)])
    const [p, t] = await Promise.all([zarr.get(pts), zarr.get(tris)])
    return {
      points: Float32Array.from(p.data as ArrayLike<number>),
      triangles: Uint32Array.from(t.data as ArrayLike<number>)
    }
  }
}

async function readAttrs(store: Readable): Promise<Record<string, unknown>> {
  const bytes = await store.get('/.zattrs')
  if (!bytes) throw new Error('Not a results bundle: it has no .zattrs')
  return JSON.parse(decoder.decode(bytes)) as Record<string, unknown>
}

function manifestOf(attrs: Record<string, unknown>): BundleManifest {
  const m = attrs.vcell_fenics as BundleManifest | undefined
  if (!m || !Array.isArray(m.times)) throw new Error('Not a results bundle: .zattrs has no vcell_fenics manifest')
  return m
}
