import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { strToU8, zipSync } from 'fflate'
import { describe, expect, it } from 'vitest'
import { Pblang } from 'process-bigraph-lang'
import { compositeDocuments, documentName, isZip } from '../app/viewers/composite/archive'

// The documents a submitted input holds, found as the service finds them at submission: .pbg and .json members,
// nested .omex archives (at most three deep), nothing else; a non-zip input is one document.
const DOC = JSON.stringify({ state: { a: 1.0 } })
const zip = (files: Record<string, Uint8Array>) => zipSync(files)

describe('compositeDocuments', () => {
  it('reads a real run\'s archive (run 4565) and its document decompiles', async () => {
    const bytes = new Uint8Array(await readFile(fileURLToPath(new URL('./fixtures/run_4565.omex', import.meta.url))))
    expect(isZip(bytes)).toBe(true)
    const documents = compositeDocuments(bytes, 'run.omex')
    expect(documents.map(d => d.path)).toEqual(['experiment.pbg'])
    const printed = new Pblang().decompile(documents[0]!.text, { name: documentName(documents[0]!.path) })
    expect(printed.text).toContain('process ensemble at "local:viva_pde_particle.ensemble.EnsembleRunner"')
  })

  it('takes documents only, from nested archives too, with their paths', () => {
    const inner = zip({ 'inner.pbg': strToU8(DOC), 'notes.txt': strToU8('x') })
    const bytes = zip({
      'manifest.xml': strToU8('<omexManifest/>'),
      'model.sbml': strToU8('<sbml/>'),
      'a.pbg': strToU8(DOC),
      'sub/b.json': strToU8(DOC),
      'nested.omex': inner
    })
    expect(compositeDocuments(bytes, 'x.omex').map(d => d.path).sort()).toEqual(['a.pbg', 'nested.omex/inner.pbg', 'sub/b.json'])
  })

  it('an archive with no document yields none, and a non-zip input is one document', () => {
    expect(compositeDocuments(zip({ 'model.sbml': strToU8('<sbml/>') }), 'x.omex')).toEqual([])
    expect(compositeDocuments(strToU8(DOC), 'bare.omex')).toEqual([{ path: 'bare.omex', text: DOC }])
  })

  it('refuses archives nested more than three deep, like the service', () => {
    let bytes = zip({ 'deep.pbg': strToU8(DOC) })
    for (let i = 0; i < 4; i++) bytes = zip({ [`level${i}.omex`]: bytes })
    expect(() => compositeDocuments(bytes, 'x.omex')).toThrow(/nested more than 3 deep/)
  })

  it('names a document by its file name', () => {
    expect(documentName('sub/updated.pbg')).toBe('updated')
    expect(documentName('nested.omex/inner.json')).toBe('inner')
    expect(documentName('c7e984d3_4F3aBE3.omex')).toBe('c7e984d3_4F3aBE3')
  })
})
