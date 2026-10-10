import type { Dataset } from '~/composables/useApi'

/** The whole content of a (small) single-file dataset, for viewers that need all of it at once. */
export function useDatasetFile(dataset: () => Dataset, as: 'text' | 'blob', maxBytes = 5 * 1024 * 1024) {
  const text = ref<string | null>(null)
  const blobUrl = ref<string | null>(null)
  const error = ref<string | null>(null)
  const loading = ref(false)
  const tooBig = computed(() => (dataset().size_bytes ?? 0) > maxBytes)

  onMounted(async () => {
    if (tooBig.value) return
    loading.value = true
    try {
      const response = await fetchContent(`/datasets/${dataset().id}/content`)
      if (!response.ok) throw new Error(`Could not read the file (${response.status})`)
      if (as === 'blob') blobUrl.value = URL.createObjectURL(await response.blob())
      else text.value = await response.text()
    } catch (e) {
      error.value = (e as Error).message
    } finally {
      loading.value = false
    }
  })
  onBeforeUnmount(() => {
    if (blobUrl.value) URL.revokeObjectURL(blobUrl.value)
  })
  return { text, blobUrl, error, loading, tooBig }
}
