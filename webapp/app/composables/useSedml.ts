import type { Schemas, Violation } from './useApi'

/**
 * SED-ML archives run on several solvers (docs/plan-sedml.md): preview a translation, run it, and the sources it can
 * come from (an upload, a BioModels entry, a biosimulations.org project). Each run answers with comparisons.
 */
export type SedmlPreview = Schemas['SedmlPreview']
export type SedmlRunResult = Schemas['SedmlRunResult']
export type Comparison = Schemas['Comparison']
export type ComparisonSeries = Schemas['ComparisonSeries']
export type Solver = Schemas['Solver']
export type BiomodelHit = Schemas['BiomodelHit']
export type ProjectInfo = Schemas['ProjectInfo']

/** Where an archive comes from: a file chosen here, or a source the API fetches. */
export type ArchiveSource =
  | { kind: 'upload', file: File }
  | { kind: 'biomodels', id: string }
  | { kind: 'biosimulations', id: string }

export interface RunChoice {
  solvers: string[]
  tags: string[]
  description: string
}

export type Outcome<T> = { ok: true, value: T } | { ok: false, error: string, violations: Violation[], findings: Schemas['SedmlFinding'][] }

function failed<T>(error: unknown, status: number, fallback: string): Outcome<T> {
  const detail = (error as { detail?: { findings?: Schemas['SedmlFinding'][] } } | undefined)?.detail
  return {
    ok: false,
    error: errorMessage(error, `${fallback} (${status})`),
    violations: errorViolations(error),
    findings: detail?.findings ?? []
  }
}

const form = (file: File) => {
  const data = new FormData()
  data.append('archive', file)
  return data
}

/** The archive a source names, as a File (a BioModels entry or biosimulations.org project is fetched by the API). */
export async function archiveOf(source: ArchiveSource): Promise<File> {
  if (source.kind === 'upload') return source.file
  const path = source.kind === 'biomodels'
    ? `/sources/biomodels/${encodeURIComponent(source.id)}/omex`
    : `/sources/biosimulations/${encodeURIComponent(source.id)}/omex`
  const response = await fetchContent(path)
  if (!response.ok) throw new Error(`Could not fetch ${source.id} (${response.status})`)
  return new File([await response.blob()], `${source.id}.omex`, { type: 'application/zip' })
}

export async function previewSedml(file: File, solvers: string[] = []): Promise<Outcome<SedmlPreview>> {
  const result = await useApi().POST('/sedml/preview', {
    params: { query: { solvers: solvers.length ? solvers : undefined } },
    body: form(file) as never,
    bodySerializer: (b: unknown) => b as FormData
  })
  return result.data ? { ok: true, value: result.data } : failed(result.error, result.response.status, 'Preview failed')
}

/** Run the archive on the chosen solvers; a BioModels or biosimulations.org source runs through its shortcut, so its
 * runs are labelled with it (and a project's original results become the comparison's reference). */
export async function runSedml(source: ArchiveSource, choice: RunChoice): Promise<Outcome<SedmlRunResult>> {
  const query = {
    solvers: choice.solvers.length ? choice.solvers : undefined,
    tags: choice.tags.length ? choice.tags : undefined,
    description: choice.description.trim() || undefined
  }
  const api = useApi()
  const result = source.kind === 'upload'
    ? await api.POST('/sedml/run', {
        params: { query },
        body: form(source.file) as never,
        bodySerializer: (b: unknown) => b as FormData
      })
    : source.kind === 'biomodels'
      ? await api.POST('/sources/biomodels/{model_id}/run', { params: { path: { model_id: source.id }, query } })
      : await api.POST('/sources/biosimulations/{project_id}/run', { params: { path: { project_id: source.id }, query } })
  return result.data ? { ok: true, value: result.data } : failed(result.error, result.response.status, 'Run failed')
}

let solversCache: Promise<Solver[]> | null = null
export function listSolvers(): Promise<Solver[]> {
  solversCache ??= useApi()
    .GET('/registry/solvers')
    .then(({ data, error }) => {
      if (error || !data) throw new Error(errorMessage(error, 'Could not list the solvers'))
      return data
    })
    .catch((e) => {
      solversCache = null
      throw e
    })
  return solversCache
}

/** A score as the comparison shows it: close below 1 (the platform's closeness score). */
export function scoreColor(close: boolean | null | undefined): 'success' | 'error' | 'neutral' {
  return close === true ? 'success' : close === false ? 'error' : 'neutral'
}
