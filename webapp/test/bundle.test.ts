import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'
import { Bundle, type Readable } from '../app/viewers/bundle/bundle'

// small.fenics: written by test/fixtures/make_fixture.py; row k of cell/u is (1 + k) * exp(-r^2) on a 5x5x5 grid.
const FIXTURE = fileURLToPath(new URL('./fixtures/small.fenics', import.meta.url))

function diskStore(requests: string[] = []): Readable {
  return {
    async get(key: string) {
      requests.push(key)
      try {
        return new Uint8Array(await readFile(FIXTURE + key))
      } catch {
        return undefined
      }
    }
  }
}

describe('Bundle', () => {
  it('reads the manifest', async () => {
    const b = await Bundle.open(diskStore())
    expect(b.times).toEqual([0, 0.5, 1])
    expect(b.live).toBe(false)
    expect(Object.keys(b.manifest.domains)).toEqual(['cell'])
    expect(b.variablesOf('cell').map(v => v.name)).toEqual(['u'])
    expect(b.particleSpecies).toEqual(['A'])
    expect(b.web).toBeUndefined()
  })

  it('reads one row with one chunk request', async () => {
    const requests: string[] = []
    const b = await Bundle.open(diskStore(requests))
    const u = b.variablesOf()[0]!
    const row0 = await b.row(u, 0)
    requests.length = 0
    const row2 = await b.row(u, 2)
    expect(row2.length).toBe(125)
    expect(requests).toEqual(['/cell/u/2.0'])
    for (let i = 0; i < row0.length; i++) expect(row2[i]).toBeCloseTo(3 * row0[i]!, 12)
  })

  it('reads stats over the recorded rows only', async () => {
    const b = await Bundle.open(diskStore())
    const u = b.variablesOf()[0]!
    const s = await b.stats(u)
    expect(s.times).toEqual([0, 0.5, 1])
    expect(s.max.length).toBe(3)
    expect(s.max[2]! / s.max[0]!).toBeCloseTo(3, 9)
    const [lo, hi] = await b.range(u)
    expect(lo).toBeCloseTo(s.min[0]!, 12)
    expect(hi).toBeCloseTo(s.max[2]!, 12)
  })

  it('reads particles up to their count', async () => {
    const b = await Bundle.open(diskStore())
    const p = await b.particles('A', 2)
    expect(p.length).toBe(3 * 3)
    expect(p[0]).toBeCloseTo(1.2, 12)
  })
})
