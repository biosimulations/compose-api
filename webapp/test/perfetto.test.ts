import { describe, expect, it } from 'vitest'
import { handOverTrace, PERFETTO_ORIGIN } from '../app/utils/perfetto'

// The opener's side of Perfetto's postMessage protocol: PING until a PONG from ui.perfetto.dev, then the trace, once.
function fakePerfetto(answerAfterPings: number, origin = PERFETTO_ORIGIN) {
  const opener = new EventTarget()
  const posted: unknown[] = []
  const target = {
    postMessage(message: unknown, targetOrigin: string) {
      expect(targetOrigin).toBe(PERFETTO_ORIGIN)
      posted.push(message)
      if (message === 'PING' && posted.filter(m => m === 'PING').length === answerAfterPings) {
        opener.dispatchEvent(new MessageEvent('message', { data: 'PONG', origin }))
      }
    }
  }
  return { opener, target, posted }
}

const trace = { buffer: new TextEncoder().encode('{"traceEvents":[]}').buffer as ArrayBuffer, title: 'Simulation 1', fileName: 't.json' }

describe('handing a trace to Perfetto', () => {
  it('pings until Perfetto answers, then posts the trace once', async () => {
    const { opener, target, posted } = fakePerfetto(3)
    await handOverTrace(target, opener, trace, { intervalMs: 1, timeoutMs: 1000 })
    expect(posted.filter(m => m === 'PING')).toHaveLength(3)
    expect(posted.at(-1)).toEqual({ perfetto: trace })
    await new Promise(r => setTimeout(r, 10))
    expect(posted.filter(m => m === 'PING')).toHaveLength(3) // no pings after the answer
  })

  it('ignores a PONG from any other origin and gives up after the timeout', async () => {
    const { opener, target, posted } = fakePerfetto(1, 'https://example.org')
    await expect(handOverTrace(target, opener, trace, { intervalMs: 1, timeoutMs: 30 })).rejects.toThrow(/did not answer/)
    expect(posted.some(m => typeof m === 'object')).toBe(false)
  })
})
