<script setup lang="ts">
import type { FavoriteKind } from '~/composables/useFavorites'

// The signed-in caller's star on a simulation, a comparison or a suite run (docs/plan-favorites-and-studies.md, F5):
// private to them, so it is not shown signed out. It changes at once and goes back if the API refuses.
const props = defineProps<{ kind: FavoriteKind, refId: string | number, size?: 'sm' | 'md' }>()
const starred = defineModel<boolean>({ default: false })
const { isAuthenticated } = useAuth()
const busy = ref(false)
const failed = ref<string | null>(null)

async function toggle(e: Event) {
  e.stopPropagation() // a row that opens its page on click keeps still
  if (busy.value) return
  const next = !starred.value
  starred.value = next
  busy.value = true
  failed.value = await setFavorite(props.kind, String(props.refId), next)
  busy.value = false
  if (failed.value) starred.value = !next
}

const label = computed(() => failed.value ?? (starred.value ? 'Starred: click to unstar' : 'Star it, to find it under Favorites'))
</script>

<template>
  <button
    v-if="isAuthenticated"
    type="button"
    :title="label"
    :aria-label="label"
    :aria-pressed="starred"
    class="inline-flex items-center justify-center rounded p-0.5 hover:bg-elevated cursor-pointer"
    :class="[starred ? 'text-warning' : 'text-dimmed hover:text-warning', failed ? 'text-error' : '']"
    @click="toggle"
  >
    <!-- lucide's star, filled when starred (the icon set has no filled star) -->
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      :class="size === 'md' ? 'size-5' : 'size-4'"
      :fill="starred ? 'currentColor' : 'none'"
      stroke="currentColor"
      stroke-width="2"
      stroke-linecap="round"
      stroke-linejoin="round"
    >
      <path d="M11.525 2.295a.53.53 0 0 1 .95 0l2.31 4.679a2.123 2.123 0 0 0 1.595 1.16l5.166.756a.53.53 0 0 1 .294.904l-3.736 3.638a2.123 2.123 0 0 0-.611 1.878l.882 5.14a.53.53 0 0 1-.771.56l-4.618-2.428a2.122 2.122 0 0 0-1.973 0L6.396 21.01a.53.53 0 0 1-.77-.56l.881-5.139a2.122 2.122 0 0 0-.611-1.879L2.16 9.795a.53.53 0 0 1 .294-.906l5.165-.755a2.122 2.122 0 0 0 1.597-1.16z" />
    </svg>
  </button>
</template>
