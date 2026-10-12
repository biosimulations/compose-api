import type { Graph, GraphEdge } from 'process-bigraph-lang'

/**
 * A two-column layout of a composite's wiring graph (process-bigraph-lang's `Pblang.graph`): stores on the left,
 * processes and steps on the right, one link per wired port. Each node lists its ports, so links fan out from their
 * own row; stores are ordered by the rows they connect to (one barycenter pass), which keeps most links short and
 * uncrossed. Pure: the SVG component only draws what this returns, and the tests check it without a browser.
 */

export const STORE_W = 170
export const NODE_W = 230
export const COLUMN_GAP = 170
export const PAD = 12
export const ROW_GAP = 22
export const LINE_H = 18
export const TITLE_H = 30
export const STORE_H = 30

export interface PortRow {
  name: string
  direction: 'input' | 'output'
  type: string | null
  /** absolute y of the port's anchor */
  y: number
  /** the store it is wired to, or null when the path leaves the composite */
  store: string | null
}

export interface NodeBox {
  id: string
  kind: string
  interface: string | null
  address: string | null
  interval: number | null
  doc: string | null
  dynamicPorts: boolean
  hasChildren: boolean
  x: number
  y: number
  w: number
  h: number
  ports: PortRow[]
}

export interface StoreBox {
  id: string
  type: string | null
  declared: boolean
  open: boolean
  x: number
  y: number
  w: number
  h: number
}

export interface Link {
  node: string
  port: string
  store: string | null
  direction: 'input' | 'output'
  type: string | null
  /** from the store's right edge (input) or the port anchor (output) ... */
  x1: number
  y1: number
  /** ... to the port anchor (input) or the store's right edge (output) */
  x2: number
  y2: number
}

export interface Layout {
  width: number
  height: number
  stores: StoreBox[]
  nodes: NodeBox[]
  links: Link[]
}

/** The port rows of a node: every wired port plus every declared one, inputs first, in declaration order. */
function portRows(id: string, graph: Graph, edges: GraphEdge[]): Omit<PortRow, 'y'>[] {
  const node = graph.nodes.find(n => n.id === id)
  const rows: Omit<PortRow, 'y'>[] = []
  const seen = new Set<string>()
  for (const direction of ['input', 'output'] as const) {
    const declared = direction === 'input' ? node?.ports.inputs : node?.ports.outputs
    for (const name of Object.keys(declared ?? {})) {
      const wired = edges.find(e => e.direction === direction && e.port === name)
      rows.push({ name, direction, type: wired?.type ?? declared?.[name] ?? null, store: wired?.store ?? null })
      seen.add(`${direction}:${name}`)
    }
    for (const e of edges) {
      if (e.direction !== direction || seen.has(`${direction}:${e.port}`)) continue
      rows.push({ name: e.port, direction, type: e.type, store: e.store })
      seen.add(`${direction}:${e.port}`)
    }
  }
  return rows
}

export function layoutGraph(graph: Graph): Layout {
  const nodeX = PAD + STORE_W + COLUMN_GAP
  const nodes: NodeBox[] = []
  let y = PAD
  for (const n of graph.nodes) {
    const edges = graph.edges.filter(e => e.node === n.id)
    const rows = portRows(n.id, graph, edges)
    const h = TITLE_H + rows.length * LINE_H + (rows.length ? 6 : 0)
    const ports: PortRow[] = rows.map((r, i) => ({ ...r, y: y + TITLE_H + i * LINE_H + LINE_H / 2 }))
    nodes.push({
      id: n.id,
      kind: n.kind,
      interface: n.interface,
      address: n.address,
      interval: n.interval,
      doc: n.doc,
      dynamicPorts: n.dynamic_ports,
      hasChildren: n.children != null,
      x: nodeX,
      y,
      w: NODE_W,
      h,
      ports
    })
    y += h + ROW_GAP
  }
  const nodesHeight = y - ROW_GAP + PAD

  // stores: ordered by the mean row of the ports wired to them; unwired ones keep their place at the end
  const anchors = new Map<string, number[]>()
  for (const node of nodes) {
    for (const p of node.ports) {
      if (p.store == null) continue
      if (!anchors.has(p.store)) anchors.set(p.store, [])
      anchors.get(p.store)!.push(p.y)
    }
  }
  const mean = (ys: number[] | undefined) => (ys && ys.length ? ys.reduce((a, b) => a + b, 0) / ys.length : Infinity)
  const ordered = [...graph.stores].sort((a, b) => mean(anchors.get(a.id)) - mean(anchors.get(b.id)))
  const stores: StoreBox[] = []
  y = PAD
  for (const s of ordered) {
    stores.push({ id: s.id, type: s.type, declared: s.declared, open: s.open, x: PAD, y, w: STORE_W, h: STORE_H })
    y += STORE_H + ROW_GAP
  }
  const storesHeight = y - ROW_GAP + PAD

  const storeBox = new Map(stores.map(s => [s.id, s]))
  const links: Link[] = []
  for (const node of nodes) {
    for (const p of node.ports) {
      const store = p.store == null ? undefined : storeBox.get(p.store)
      const storeX = store ? store.x + store.w : nodeX - COLUMN_GAP / 2
      const storeY = store ? store.y + store.h / 2 : p.y
      const portX = node.x
      links.push(
        p.direction === 'input'
          ? { node: node.id, port: p.name, store: p.store, direction: 'input', type: p.type, x1: storeX, y1: storeY, x2: portX, y2: p.y }
          : { node: node.id, port: p.name, store: p.store, direction: 'output', type: p.type, x1: portX, y1: p.y, x2: storeX, y2: storeY }
      )
    }
  }

  return {
    width: nodeX + NODE_W + PAD,
    height: Math.max(nodesHeight, storesHeight, PAD * 2 + STORE_H),
    stores,
    nodes,
    links
  }
}

/** A cubic Bézier between two anchors, horizontal at both ends. */
export function linkPath(l: Link): string {
  const dx = Math.max(40, Math.abs(l.x2 - l.x1) / 2)
  return `M ${l.x1} ${l.y1} C ${l.x1 + dx} ${l.y1}, ${l.x2 - dx} ${l.y2}, ${l.x2} ${l.y2}`
}
