import { describe, expect, it } from 'vitest'
import type { WebappConfig } from '../app/composables/useAuth'
import { LONG_RUNS, maxIntervalTime } from '../app/utils/interval'

const BASE: WebappConfig = { auth0_domain: '', auth0_audience: '', auth0_client_id: '', prebuilt_simulators: [] }

describe('the longest interval a run may ask for', () => {
  const config = { ...BASE, max_interval_time: 1000, max_long_run_interval_time: 86400 }

  it('is the long-run cap only for a caller the API says may run long', () => {
    expect(maxIntervalTime(config, [LONG_RUNS])).toBe(86400)
    expect(maxIntervalTime(config, ['environments:admin', LONG_RUNS])).toBe(86400)
  })

  it('is the usual cap for anyone else, signed in or not', () => {
    for (const capabilities of [null, undefined, [], ['environments:admin']]) {
      expect(maxIntervalTime(config, capabilities)).toBe(1000)
    }
  })

  it('is 1000 for everyone from an API that does not publish its caps', () => {
    for (const published of [null, BASE]) {
      expect(maxIntervalTime(published, [])).toBe(1000)
      expect(maxIntervalTime(published, [LONG_RUNS])).toBe(1000)
    }
  })
})
