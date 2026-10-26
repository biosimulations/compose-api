import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'
import { ComponentIndex, addressKey, interfaceMarkdown, reindentJson, typeText } from '../app/viewers/composite/interfaces'

const here = (path: string) => fileURLToPath(new URL(path, import.meta.url))
const manifest = async (name: string) =>
  JSON.parse(await readFile(here(`fixtures/${name}.json`), 'utf-8'))

describe('looking up the classes a document names', () => {
  it('finds a class by any spelling of its address, or by a unique short name', async () => {
    const index = new ComponentIndex('registry_env', await manifest('registry_env'))
    expect(addressKey('local:!a.b.C')).toBe('a.b.C')
    // run 4577 submitted the registered form; the manifest records the import form
    expect(index.find('local:pbsim_common.simulators.copasi_process.CopasiUTCStep')?.kind).toBe('step')
    expect(index.find('local:!pbsim_common.simulators.copasi_process.CopasiUTCStep')?.name).toBe('CopasiUTCStep')
    expect(index.find('local:CopasiUTCStep')?.name).toBe('CopasiUTCStep')
    expect(index.find('local:elsewhere.CopasiUTCStep')).toBeNull()
  })

  it('describes a class as the manifest declares it', async () => {
    const index = new ComponentIndex('viva-pde-particle', await manifest('viva-pde-particle'))
    expect(typeText({ _type: 'integer', _default: 1 })).toBe('integer = 1')
    const md = interfaceMarkdown(index.named('Stepper')!, 'viva-pde-particle', '/ui/environments/viva-pde-particle#Stepper')
    expect(md).toContain('**Stepper**')
    expect(md).toMatch(/every\s+integer = 1/)
    expect(md).toContain('(/ui/environments/viva-pde-particle#Stepper)')
  })
})

describe('re-indenting a submitted document', () => {
  it('changes whitespace only, keeping number spellings and scalar arrays on one line', () => {
    const text = '{"state":{"s":{"config":{"n_points":100.0,"t":1e-3,"x":[1,2.50, "a,b"],"m":{}},"ports":[{"a":[]}]}}}'
    const pretty = reindentJson(text)
    expect(pretty.replace(/\s+/g, '')).toBe(text.replace(/\s+/g, ''))
    expect(pretty).toContain('"n_points": 100.0')
    expect(pretty).toContain('"t": 1e-3')
    expect(pretty).toContain('"x": [1, 2.50, "a,b"]')
    expect(pretty).toContain('"m": {}')
    expect(JSON.parse(pretty)).toEqual(JSON.parse(text))
  })

  it('reproduces an already indented document', () => {
    const text = JSON.stringify({ a: { b: [1, 2], c: [{ d: 'x' }], e: {} } }, null, 2)
    expect(reindentJson(text)).toBe(text.replace('[\n      1,\n      2\n    ]', '[1, 2]'))
  })
})
