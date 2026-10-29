import type { Schemas } from './useApi'

export type FavoriteKind = Schemas['FavoriteKind']

/** Star or unstar a simulation, a comparison (by id) or a suite run (`<suite>@<number>`) for the signed-in caller
 * (docs/plan-favorites-and-studies.md, step 2b); an error message, or null. */
export async function setFavorite(kind: FavoriteKind, ref: string, starred: boolean): Promise<string | null> {
  const params = { params: { path: { kind, ref } } }
  const { error, response } = starred
    ? await useApi().PUT('/favorites/{kind}/{ref}', params)
    : await useApi().DELETE('/favorites/{kind}/{ref}', params)
  return error ? errorMessage(error, `Could not ${starred ? 'star' : 'unstar'} it (${response.status})`) : null
}

/** The references the signed-in caller starred, of one kind. */
export async function favoriteRefs(kind: FavoriteKind): Promise<Set<string>> {
  const { data } = await useApi().GET('/favorites', { params: { query: { kind } } })
  return new Set((data ?? []).map(f => f.ref))
}
