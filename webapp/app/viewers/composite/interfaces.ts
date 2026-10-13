import type { InterfaceManifest } from '../../composables/useRegistry'

/**
 * The classes an environment provides, from its interface manifest (`pbg-interfaces/1`, generated inside its image),
 * looked up the ways a document names them, and described for a hover or a page. Types are shown as the manifest
 * gives them: bigraph-schema's own forms, as the class declares them.
 */
export type Component = InterfaceManifest['components'][number]

/** An address without its protocol and import marker: `local:!a.b.C` and `local:a.b.C` → `a.b.C`. */
export function addressKey(address: string): string {
  return address.replace(/^[a-z]+:/, '').replace(/^!/, '')
}

export class ComponentIndex {
  private readonly byAddress = new Map<string, Component>()
  private readonly names = new Map<string, Component[]>()

  constructor(readonly environment: string, manifest: InterfaceManifest) {
    for (const c of manifest.components) {
      this.byAddress.set(addressKey(c.address), c)
      this.names.set(c.name, [...(this.names.get(c.name) ?? []), c])
    }
  }

  /** The class a document's `address` names: by module path, or by a registered short name (`local:Stepper`). */
  find(address: string): Component | null {
    const key = addressKey(address)
    return this.byAddress.get(key) ?? (key.includes('.') ? null : this.named(key))
  }

  /** The class with this short name, when only one class has it. */
  named(name: string): Component | null {
    const found = this.names.get(name)
    return found?.length === 1 ? found[0]! : null
  }

  get size(): number {
    return this.byAddress.size
  }
}

/** A type as the manifest gives it: a bigraph-schema string, or `{_type, _default}` shown as `type = default`. */
export function typeText(spec: unknown): string {
  if (typeof spec === 'string') return spec
  if (spec && typeof spec === 'object' && !Array.isArray(spec)) {
    const { _type, _default, ...rest } = spec as Record<string, unknown>
    if (typeof _type === 'string' && !Object.keys(rest).length) {
      return _default === undefined ? _type : `${_type} = ${JSON.stringify(_default)}`
    }
  }
  return JSON.stringify(spec)
}

/** The rows of one face (config, inputs, outputs): name and type. */
export function faceRows(face: Record<string, unknown> | null | undefined): { name: string, type: string }[] {
  return Object.entries(face ?? {}).map(([name, spec]) => ({ name, type: typeText(spec) }))
}

/** A class's interface as hover markdown, with a link to its environment's page (`href`, when given). */
export function interfaceMarkdown(c: Component, environment: string, href?: string): string {
  const lines = [`**${c.name}** · ${c.kind} · in \`${environment}\``, '', `\`${c.address}\``]
  if (c.description) lines.push('', c.description)
  const block: string[] = []
  const face = (title: string, rows: { name: string, type: string }[], open = false) => {
    block.push(`${title}${rows.length ? '' : open ? ' (any ports)' : ' (none)'}`)
    const width = Math.max(0, ...rows.map(r => r.name.length))
    for (const r of rows) block.push(`  ${r.name.padEnd(width)}  ${r.type}`)
  }
  face('config', faceRows(c.config_schema))
  face('inputs', faceRows(c.inputs), c.dynamic_ports)
  face('outputs', faceRows(c.outputs), c.dynamic_ports)
  lines.push('', '```', ...block, '```')
  const entry = c.registry_entry
  const notes = [
    c.dynamic_ports ? 'Its ports are dynamic: it declares them from its config.' : null,
    entry ? `Registry entry \`${entry.id}\` (${entry.level}).` : null,
    href ? `[${c.name} among ${environment}'s classes](${href})` : null
  ].filter(Boolean)
  if (notes.length) lines.push('', notes.join(' '))
  return lines.join('\n')
}

/**
 * JSON re-indented, its tokens untouched: numbers keep their spelling (`100.0` stays a float, which the value's type
 * depends on), keys their order. Arrays that hold no object or array stay on one line.
 */
export function reindentJson(text: string, indent = '  '): string {
  const out: string[] = []
  let depth = 0
  let i = 0
  const n = text.length
  const newline = () => out.push('\n', indent.repeat(depth))
  /** The end of the string literal starting at `at` (the index after its closing quote). */
  const stringEnd = (at: number) => {
    let j = at + 1
    while (j < n && text[j] !== '"') j += text[j] === '\\' ? 2 : 1
    return j + 1
  }
  /** The index of the `]` closing the array at `at`, when it holds only scalars; else -1. */
  const flatArrayEnd = (at: number) => {
    for (let j = at + 1; j < n;) {
      const ch = text[j]!
      if (ch === '"') j = stringEnd(j)
      else if (ch === ']') return j
      else if (ch === '[' || ch === '{') return -1
      else j++
    }
    return -1
  }
  const isSpace = (ch: string) => ch === ' ' || ch === '\n' || ch === '\r' || ch === '\t'
  /** The next significant character after `at`. */
  const peek = (at: number) => {
    let j = at
    while (j < n && isSpace(text[j]!)) j++
    return text[j]
  }
  while (i < n) {
    const ch = text[i]!
    if (ch === '"') {
      const end = stringEnd(i)
      out.push(text.slice(i, end))
      i = end
    } else if (isSpace(ch)) {
      i++
    } else if (ch === '{' || ch === '[') {
      const flat = ch === '[' ? flatArrayEnd(i) : -1
      if (flat >= 0) {
        // [1, 2, "a"]: the scalars with one space after each comma
        const parts: string[] = []
        let j = i + 1
        let token = ''
        while (j < flat) {
          const c = text[j]!
          if (c === '"') {
            const end = stringEnd(j)
            token += text.slice(j, end)
            j = end
          } else if (c === ',') {
            parts.push(token)
            token = ''
            j++
          } else {
            if (!isSpace(c)) token += c
            j++
          }
        }
        if (token || parts.length) parts.push(token)
        out.push(`[${parts.join(', ')}]`)
        i = flat + 1
      } else {
        const close = ch === '{' ? '}' : ']'
        if (peek(i + 1) === close) {
          out.push(ch + close)
          i = text.indexOf(close, i + 1) + 1
        } else {
          out.push(ch)
          depth++
          newline()
          i++
        }
      }
    } else if (ch === '}' || ch === ']') {
      depth--
      newline()
      out.push(ch)
      i++
    } else if (ch === ',') {
      out.push(',')
      newline()
      i++
    } else if (ch === ':') {
      out.push(': ')
      i++
    } else {
      let j = i
      while (j < n && !isSpace(text[j]!) && !',:{}[]"'.includes(text[j]!)) j++
      out.push(text.slice(i, j))
      i = j
    }
  }
  return out.join('')
}
