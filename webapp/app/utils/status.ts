import prettyBytes from 'pretty-bytes'
import prettyMs from 'pretty-ms'

export const STATUSES = [
  'submitting', 'waiting', 'queued', 'pending', 'running', 'completed',
  'failed', 'cancelled', 'out_of_memory', 'suspended', 'timeout', 'unknown'
] as const

const TERMINAL = new Set(['completed', 'failed', 'cancelled', 'out_of_memory', 'timeout'])

export function isTerminal(status: string | null | undefined): boolean {
  return !!status && TERMINAL.has(status)
}

type BadgeColor = 'primary' | 'secondary' | 'success' | 'info' | 'warning' | 'error' | 'neutral'

export function statusColor(status: string | null | undefined): BadgeColor {
  switch (status) {
    case 'completed': return 'success'
    case 'running': return 'info'
    case 'failed': case 'out_of_memory': case 'timeout': return 'error'
    case 'cancelled': case 'suspended': return 'warning'
    case 'unknown': case null: case undefined: return 'neutral'
    default: return 'secondary'
  }
}

export function formatTime(value: string | null | undefined): string {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}

export function formatBytes(n: number | null | undefined): string {
  return n == null ? '—' : prettyBytes(n, { binary: true })
}

export function formatDuration(seconds: number | null | undefined): string {
  return seconds == null ? '—' : prettyMs(seconds * 1000, { secondsDecimalDigits: 1 })
}
