<script setup lang="ts">
import type { NavigationMenuItem } from '@nuxt/ui'

// Shell after ../platform/frontend/app/app.vue: UHeader + UNavigationMenu + UMain + footer.
const { rejected, clearRejected } = useAuth()

const items: NavigationMenuItem[][] = [
  [
    { label: 'Run a simulation', icon: 'i-lucide-play', to: '/simulations/new' },
    { label: 'Simulations', icon: 'i-lucide-list', to: '/simulations' },
    { label: 'Datasets', icon: 'i-lucide-files', to: '/datasets' },
    { label: 'Catalog', icon: 'i-lucide-boxes', to: '/catalog' }
  ],
  [
    { label: 'API docs', icon: 'i-lucide-book-open', to: '/docs', external: true, target: '_blank' },
    { label: 'GitHub', icon: 'i-simple-icons-github', to: 'https://github.com/biosimulations/compose-api', target: '_blank' }
  ]
]

const version = ref<string | null>(null)
onMounted(async () => {
  const { data } = await useApi().GET('/version')
  version.value = data ?? null
})
</script>

<template>
  <UApp>
    <UHeader mode="drawer">
      <template #title>
        <NuxtLink to="/" class="flex items-center gap-2">
          <img :src="`${$config.app.baseURL}favicon.svg`" alt="" class="h-7 w-7">
          <span class="font-bold">compose-api</span>
        </NuxtLink>
      </template>

      <UNavigationMenu :items="items[0]" class="hidden lg:flex" />

      <template #right>
        <UNavigationMenu :items="items[1]" class="hidden lg:flex" />
        <AuthMenu />
      </template>

      <template #body>
        <UNavigationMenu :items="items" orientation="vertical" class="-mx-2.5" />
      </template>
    </UHeader>

    <UMain>
      <UAlert
        v-if="rejected"
        color="warning"
        variant="subtle"
        icon="i-lucide-shield-alert"
        title="Sign-in not accepted"
        :description="rejected"
        :close="{ onClick: clearRejected }"
        class="rounded-none"
      />
      <NuxtPage />
    </UMain>

    <UFooter>
      <template #left>
        <p class="text-sm text-muted">
          compose-api{{ version ? ` ${version}` : '' }} · Center for Reproducible Biomedical Modeling · UConn Health
        </p>
      </template>
      <template #right>
        <UButton to="/health" external target="_blank" variant="ghost" color="neutral" size="sm" label="Health" />
      </template>
    </UFooter>
  </UApp>
</template>
