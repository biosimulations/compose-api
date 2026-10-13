import { describe, expect, it } from 'vitest'
import { imageRepository, matchEnvironment } from '../app/composables/useRegistry'

// What /simulations/{id} records as `simulator` (production, 2026-10-12): null for the shared image, the image itself
// for a prebuilt one, at the digest it ran (run 4569 ran an earlier digest than today's pin).
const environments = [
  { name: 'registry_env', simulator: null, image: 'ghcr.io/biosimulations/registry_env:c7e984d31f441805315590a4c53e7f9f' },
  {
    name: 'viva-pde-particle',
    simulator: 'viva-pde-particle',
    image: 'ghcr.io/vivarium-collective/viva-pde-particle-compose@sha256:e3c0b03e938ba47eedf2c9fee523cec9a88e6cb7b611fa8283f3048dd3418f28'
  }
]

describe('the environment a run used', () => {
  it('strips digests and tags, not registry ports', () => {
    expect(imageRepository('ghcr.io/a/b@sha256:abc')).toBe('ghcr.io/a/b')
    expect(imageRepository('ghcr.io/a/b:1.0')).toBe('ghcr.io/a/b')
    expect(imageRepository('localhost:5000/a/b')).toBe('localhost:5000/a/b')
    expect(imageRepository('localhost:5000/a/b:1.0@sha256:abc')).toBe('localhost:5000/a/b')
  })

  it('matches the shared image, a prebuilt image at any digest, and a bare name', () => {
    expect(matchEnvironment(environments, null)?.name).toBe('registry_env')
    expect(matchEnvironment(environments,
      'ghcr.io/vivarium-collective/viva-pde-particle-compose@sha256:531fcac07dbb7278c266080b597d6dbcbb60ebd81527e3cde7cda468ad2bccc1'
    )?.name).toBe('viva-pde-particle')
    expect(matchEnvironment(environments, 'viva-pde-particle')?.name).toBe('viva-pde-particle')
    expect(matchEnvironment(environments, 'ghcr.io/someone/else:1')).toBeNull()
  })
})
