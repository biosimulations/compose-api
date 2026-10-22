import { describe, expect, it } from 'vitest'
import { isApiRequest } from '../app/utils/apiAuth'

// The cases from ../platform/frontend/tests/api-auth.test.mjs, for both of this app's shapes: deployed, where the API
// serves the UI from its own origin (apiBase ''), and in development, where apiBase names another origin.
const PAGE = 'https://compose.cam.uchc.edu'

describe('a token goes only to the API', () => {
  it('same origin when deployed', () => {
    expect(isApiRequest('/simulations?limit=5', '', PAGE)).toBe(true)
    expect(isApiRequest('https://compose.cam.uchc.edu/datasets/x/content', '', PAGE)).toBe(true)
    expect(isApiRequest(new URL('/auth/me', PAGE), '', PAGE)).toBe(true)
    expect(isApiRequest(new Request('https://compose.cam.uchc.edu/auth/me'), '', PAGE)).toBe(true)
  })

  it('never to another host, however it is spelled', () => {
    for (const url of [
      'https://dev-bu7yo7484tyxu6a1.us.auth0.com/oauth/token',
      'https://compose.cam.uchc.edu.evil.example/simulations',
      'https://evilcompose.cam.uchc.edu/simulations',
      '//evil.example/simulations',
      'https://user:pass@compose.cam.uchc.edu/simulations',
      'https://compose.cam.uchc.edu@evil.example/simulations',
      'http://compose.cam.uchc.edu/simulations', // another origin: the scheme differs
      'https://compose.cam.uchc.edu:8443/simulations',
      'https://ui.perfetto.dev/#!/'
    ]) {
      expect(isApiRequest(url, '', PAGE), url).toBe(false)
    }
  })

  it('only http(s) API bases', () => {
    expect(isApiRequest('javascript:alert(1)', '', PAGE)).toBe(false)
    expect(isApiRequest('/simulations', 'file:///etc', PAGE)).toBe(false)
  })

  it('in development, the configured API origin and nothing else', () => {
    const base = 'http://localhost:8000'
    const dev = 'http://localhost:4200'
    expect(isApiRequest('http://localhost:8000/simulations', base, dev)).toBe(true)
    expect(isApiRequest('/simulations', base, dev)).toBe(false) // the dev server itself, not the API
    expect(isApiRequest('http://localhost:8001/simulations', base, dev)).toBe(false)
  })

  it('under an API path prefix only', () => {
    const base = 'https://gateway.example/compose'
    expect(isApiRequest('https://gateway.example/compose/simulations', base, PAGE)).toBe(true)
    expect(isApiRequest('https://gateway.example/compose', base, PAGE)).toBe(true)
    expect(isApiRequest('https://gateway.example/composer/simulations', base, PAGE)).toBe(false)
    expect(isApiRequest('https://gateway.example/other', base, PAGE)).toBe(false)
  })

  it('fails closed on what it cannot parse', () => {
    expect(isApiRequest('/simulations', 'http://[', PAGE)).toBe(false)
  })
})
