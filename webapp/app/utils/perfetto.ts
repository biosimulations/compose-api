/**
 * Opening a trace in ui.perfetto.dev already loaded. Perfetto takes a trace from the page that opened it by
 * `postMessage` (https://perfetto.dev/docs/visualization/deep-linking-to-perfetto-ui): the opener pings with `'PING'`
 * until the UI, once ready, answers `'PONG'`, then posts `{perfetto: {buffer, title, fileName}}`. Its `?url=` parameter
 * only takes a few allowlisted hosts, and this API's trace route needs the caller's token anyway.
 */
export const PERFETTO_ORIGIN = 'https://ui.perfetto.dev'

interface MessageTarget {
  postMessage: (message: unknown, targetOrigin: string, transfer?: Transferable[]) => void
}

interface MessageSource {
  addEventListener: (type: 'message', listener: (e: MessageEvent) => void) => void
  removeEventListener: (type: 'message', listener: (e: MessageEvent) => void) => void
}

/** Ping `target` until Perfetto answers, then hand it the trace. Rejects after `timeoutMs` without an answer. */
export function handOverTrace(
  target: MessageTarget,
  source: MessageSource,
  trace: { buffer: ArrayBuffer, title: string, fileName: string },
  { intervalMs = 100, timeoutMs = 30_000 }: { intervalMs?: number, timeoutMs?: number } = {}
): Promise<void> {
  return new Promise((resolve, reject) => {
    const ping = setInterval(() => target.postMessage('PING', PERFETTO_ORIGIN), intervalMs)
    const deadline = setTimeout(() => {
      stop()
      reject(new Error('Perfetto did not answer; download the Chrome trace and drag it into Perfetto instead'))
    }, timeoutMs)
    function stop() {
      clearInterval(ping)
      clearTimeout(deadline)
      source.removeEventListener('message', onMessage)
    }
    function onMessage(e: MessageEvent) {
      if (e.origin !== PERFETTO_ORIGIN || e.data !== 'PONG') return
      stop()
      target.postMessage({ perfetto: trace }, PERFETTO_ORIGIN)
      resolve()
    }
    source.addEventListener('message', onMessage)
  })
}

/**
 * Open Perfetto with the trace `load` fetches. Call it straight from a click: the window is opened before anything is
 * awaited, which is what lets it past pop-up blockers. On failure the window is closed and the error rethrown.
 */
export async function openInPerfetto(load: () => Promise<ArrayBuffer>, title: string, fileName: string): Promise<void> {
  const win = window.open(`${PERFETTO_ORIGIN}/#!/viewer`, '_blank')
  if (!win) throw new Error('The browser blocked the Perfetto window: allow pop-ups for this site')
  try {
    const buffer = await load()
    await handOverTrace(win, window, { buffer, title, fileName })
  } catch (e) {
    win.close()
    throw e
  }
}
