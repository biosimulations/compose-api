import { describe, expect, it } from 'vitest'
import { Pblang } from 'process-bigraph-lang'
import { layoutGraph, linkPath, NODE_W, STORE_W } from '../app/viewers/composite/layout'

// A document as compose-api receives it in a .pbg: two processes over three stores, one reading a store the other
// writes, plus a wire whose path leaves the composite (null store).
const DOCUMENT = {
  schema: { a: 'float', b: 'float', total: 'float' },
  state: {
    a: 1.0,
    b: 2.0,
    total: 0.0,
    add: {
      _type: 'process',
      address: 'local:!demo.AddFloats',
      _inputs: { left: 'float', right: 'float' },
      _outputs: { result: 'float' },
      inputs: { left: ['a'], right: ['b'] },
      outputs: { result: ['total'] },
      interval: 1.0
    },
    report: {
      _type: 'step',
      address: 'local:!demo.Report',
      _inputs: { value: 'float', env: 'float' },
      inputs: { value: ['total'], env: ['..', 'outside'] }
    }
  }
}

describe('process-bigraph-lang in the webapp', () => {
  it('decompiles a document, checks it and graphs it', async () => {
    const pblang = new Pblang()
    const printed = pblang.decompile(JSON.stringify(DOCUMENT), { name: 'demo' })
    expect(printed.text).toContain('printed from demo')
    expect(printed.text).toContain('composite {')
    expect(printed.text).toContain('process add : AddFloats')
    expect(printed.assets).toEqual({})
    const { diagnostics } = await pblang.check(printed.text)
    expect(diagnostics.every(d => d.severity !== 'error')).toBe(true)
    const graph = await pblang.graph({ document: JSON.stringify(DOCUMENT) })
    expect(graph.nodes.map(n => n.id)).toEqual(['add', 'report'])
    expect(graph.stores.map(s => s.id).sort()).toEqual(['a', 'b', 'total'])
  })
})

describe('layoutGraph', () => {
  it('puts stores left, nodes right, and one link per wired port', async () => {
    const graph = await new Pblang().graph({ document: JSON.stringify(DOCUMENT) })
    const layout = layoutGraph(graph)
    expect(layout.stores.every(s => s.x + s.w < layout.nodes[0]!.x)).toBe(true)
    expect(layout.nodes.map(n => n.id)).toEqual(['add', 'report'])
    expect(layout.links).toHaveLength(5)
    const add = layout.nodes[0]!
    expect(add.ports.map(p => `${p.direction}:${p.name}`)).toEqual(['input:left', 'input:right', 'output:result'])
    // every port anchors on its own row inside its node
    for (const p of add.ports) expect(p.y).toBeGreaterThan(add.y)
    for (const p of add.ports) expect(p.y).toBeLessThan(add.y + add.h)
    expect(new Set(add.ports.map(p => p.y)).size).toBe(3)
    expect(layout.width).toBe(layout.nodes[0]!.x + NODE_W + 12)
    expect(layout.stores[0]!.w).toBe(STORE_W)
  })

  it('orders stores by the rows they connect to, and draws an outside path as a dangling link', async () => {
    const graph = await new Pblang().graph({ document: JSON.stringify(DOCUMENT) })
    const layout = layoutGraph(graph)
    // a and b feed the first node's first rows; total is read by the second node too, so it sorts after them
    expect(layout.stores.map(s => s.id)).toEqual(['a', 'b', 'total'])
    const outside = layout.links.find(l => l.port === 'env')!
    expect(outside.store).toBeNull()
    expect(outside.x1).toBeLessThan(outside.x2)
    expect(linkPath(outside)).toMatch(/^M [\d.]+ [\d.]+ C /)
  })

  it('lays out an empty graph without crashing', () => {
    const layout = layoutGraph({ nodes: [], stores: [], edges: [] })
    expect(layout.links).toEqual([])
    expect(layout.height).toBeGreaterThan(0)
  })
})
