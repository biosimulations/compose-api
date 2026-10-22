import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'
import { Pblang } from 'process-bigraph-lang'

// A real run (simulation 4571, the viva-pde-particle hybrid) checked against the manifest committed for the
// environment it ran in (compose_api/registry/manifests/, generated inside that image): its processes resolve.
const here = (path: string) => fileURLToPath(new URL(path, import.meta.url))
const document = () => readFile(here('./fixtures/hybrid_4571.pbg'), 'utf-8')
const manifest = async () => JSON.parse(await readFile(here('../../compose_api/registry/manifests/viva-pde-particle.json'), 'utf-8'))

const unresolved = (codes: (string | undefined)[]) => codes.filter(c => c === 'S020').length

describe('checking a run against its environment\'s manifest', () => {
  it('resolves every process the hybrid uses', async () => {
    const without = new Pblang()
    const plain = without.decompile(await document(), { name: 'hybrid' })
    expect(unresolved((await without.check(plain.text)).diagnostics.map(d => d.code))).toBeGreaterThan(0)

    const pblang = new Pblang().addManifest(await manifest())
    const printed = pblang.decompile(await document(), { name: 'hybrid' })
    const { diagnostics } = await pblang.check(printed.text)
    expect(unresolved(diagnostics.map(d => d.code))).toBe(0)
    expect(diagnostics.filter(d => d.severity === 'error')).toEqual([])

    const graph = await pblang.graph({ document: await document() })
    const interfaces = graph.nodes.map(n => n.interface).filter(Boolean)
    expect(interfaces).toEqual(expect.arrayContaining(['FVReactionDiffusion', 'Stepper', 'SpatialRecorder']))
  })
})
