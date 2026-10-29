import type { Schemas, Violation } from './useApi'

export interface RunOptions {
  /** the runner's interval, 0 to 1000 */
  intervalTime: number
  /** a batch job (smaller partition, 1 CPU) */
  batch?: boolean
  /** the environment to run in, by name; none: chosen from the classes the document names, or a mash-up made for it */
  environment?: string | null
  /** stored with the run, to find it by later */
  tags?: string[]
  /** what the run is for */
  description?: string | null
  /** who may read it; omitted, the service's default (private signed in, public anonymous) */
  visibility?: Schemas['Visibility']
}

export type RunOutcome =
  | { ok: true, simulationId: number }
  | { ok: false, error: string, violations: Violation[] }

/** Submit a `.pbg`, `.omex` or `.sbml` file to `POST /simulation/run` (the API types an upload by its suffix). */
export async function submitRun(file: File, options: RunOptions): Promise<RunOutcome> {
  const form = new FormData()
  form.append('uploaded_file', file)
  const result = await useApi().POST('/simulation/run', {
    params: {
      query: {
        interval_time: options.intervalTime,
        batch_submission: options.batch ?? false,
        environment: options.environment || undefined,
        tags: options.tags?.length ? options.tags : undefined,
        description: options.description?.trim() || undefined,
        visibility: options.visibility
      }
    },
    body: form as never,
    bodySerializer: (b: unknown) => b as FormData
  })
  if (result.error || !result.data) {
    return {
      ok: false,
      error: errorMessage(result.error, `Submission failed (${result.response.status})`),
      violations: errorViolations(result.error)
    }
  }
  return { ok: true, simulationId: result.data.simulation_database_id }
}
