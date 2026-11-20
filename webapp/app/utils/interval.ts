import type { WebappConfig } from '~/composables/useAuth'

/** The capability GET /auth/me lists for a caller who may ask for long runs (LONG_RUN_ROLE). */
export const LONG_RUNS = 'simulations:long-runs'

/**
 * The longest interval POST /simulation/run takes from this caller: the long-run cap for one whose capabilities
 * (GET /auth/me) include long runs, the usual cap for everyone else (both from GET /webapp/config). An API that does
 * not publish its caps takes 1000 from everyone.
 */
export function maxIntervalTime(config: WebappConfig | null, capabilities: readonly string[] | null | undefined): number {
  const usual = config?.max_interval_time ?? 1000
  return (capabilities ?? []).includes(LONG_RUNS) ? (config?.max_long_run_interval_time ?? usual) : usual
}
