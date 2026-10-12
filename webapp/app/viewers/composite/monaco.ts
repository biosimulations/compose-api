import * as monaco from 'monaco-editor/editor/editor.api'
import EditorWorker from 'monaco-editor/editor/editor.worker.js?worker'
import monarch from 'process-bigraph-lang/monarch'
import type { Diagnostic } from 'process-bigraph-lang'

/**
 * Monaco for `.pblang` text: the language registered once with process-bigraph-lang's Monarch tokenizer, and the
 * checker's findings as markers. The language server (`process-bigraph-lang/worker`, hover and completion) is not
 * connected yet: the viewer is read-only and checks on the main thread.
 */

export const LANGUAGE = 'pblang'
let registered = false

export function registerLanguage(): typeof monaco {
  if (registered) return monaco
  registered = true
  const env = self as unknown as { MonacoEnvironment?: monaco.Environment }
  env.MonacoEnvironment = { getWorker: () => new EditorWorker() }
  monaco.languages.register({ id: LANGUAGE, extensions: ['.pblang', '.pbl'] })
  monaco.languages.setMonarchTokensProvider(LANGUAGE, monarch as unknown as monaco.languages.IMonarchLanguage)
  // process-bigraph-lang/language-configuration is JSON with comments, which a bundler's JSON import rejects
  monaco.languages.setLanguageConfiguration(LANGUAGE, {
    comments: { lineComment: '//', blockComment: ['/*', '*/'] },
    brackets: [['{', '}'], ['[', ']'], ['(', ')']],
    autoClosingPairs: [
      { open: '{', close: '}' },
      { open: '[', close: ']' },
      { open: '(', close: ')' },
      { open: '"', close: '"' }
    ]
  })
  return monaco
}

const SEVERITY: Record<Diagnostic['severity'], monaco.MarkerSeverity> = {
  error: monaco.MarkerSeverity.Error,
  warning: monaco.MarkerSeverity.Warning,
  info: monaco.MarkerSeverity.Info,
  hint: monaco.MarkerSeverity.Hint
}

/** The checker's findings as Monaco markers (its ranges are zero-based; Monaco's are one-based). */
export function toMarkers(diagnostics: Diagnostic[]): monaco.editor.IMarkerData[] {
  return diagnostics.map(d => ({
    severity: SEVERITY[d.severity],
    code: d.code,
    message: d.path ? `${d.message} (${d.path})` : d.message,
    startLineNumber: d.range.start.line + 1,
    startColumn: d.range.start.character + 1,
    endLineNumber: d.range.end.line + 1,
    endColumn: d.range.end.character + 1
  }))
}
