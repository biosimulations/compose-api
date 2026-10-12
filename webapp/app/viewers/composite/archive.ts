import { unzipSync } from 'fflate'

/**
 * The composite documents a submitted input holds, read the way the service reads them at submission
 * (compose_api/registry/validation.py): an OMEX (COMBINE) archive is a zip whose `.pbg` and `.json` members are
 * documents, and whose `.omex` members are searched in turn, at most three deep; other members (SBML models,
 * manifest.xml, data) are not documents. Anything that is not a zip is taken as one document, since some inputs are a
 * bare `.pbg` under an `.omex` name.
 */
export interface ArchiveDocument {
  /** the member's path inside the archive (nested archives joined with `/`), or the file's own name */
  path: string
  text: string
}

const DOCUMENT = /\.(pbg|json)$/i
const NESTED = /\.omex$/i
const MAX_NESTING = 3

export function isZip(bytes: Uint8Array): boolean {
  return bytes.length >= 4 && bytes[0] === 0x50 && bytes[1] === 0x4b && bytes[2] === 0x03 && bytes[3] === 0x04
}

export function compositeDocuments(bytes: Uint8Array, name: string): ArchiveDocument[] {
  if (!isZip(bytes)) return [{ path: name, text: new TextDecoder().decode(bytes) }]
  return fromArchive(bytes, '', 0)
}

function fromArchive(bytes: Uint8Array, prefix: string, depth: number): ArchiveDocument[] {
  if (depth > MAX_NESTING) throw new Error(`archives are nested more than ${MAX_NESTING} deep`)
  const members = unzipSync(bytes, { filter: f => !f.name.endsWith('/') && (DOCUMENT.test(f.name) || NESTED.test(f.name)) })
  const documents: ArchiveDocument[] = []
  for (const [member, content] of Object.entries(members)) {
    const path = `${prefix}${member}`
    if (DOCUMENT.test(member)) documents.push({ path, text: new TextDecoder().decode(content) })
    else documents.push(...fromArchive(content, `${path}/`, depth + 1))
  }
  return documents
}

/** A document's name for the decompiled text: its file name without the suffix. */
export function documentName(path: string): string {
  return (path.split('/').pop() ?? 'composite').replace(/\.(pbg|json|omex|ya?ml)$/i, '') || 'composite'
}
