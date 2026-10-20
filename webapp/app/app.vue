<script setup lang="ts">
import type { NavigationMenuItem } from '@nuxt/ui'

// Shell after ../platform/frontend/app/app.vue: UHeader + UNavigationMenu + UMain + footer.
const { rejected, clearRejected } = useAuth()

// Starting something new and the registry are menus; the four kinds of results stay one click away. Nine flat tabs
// did not fit a laptop-width header.
const route = useRoute()
const under = (...prefixes: string[]) => prefixes.some(p => route.path === p || route.path.startsWith(`${p}/`))
const items = computed<NavigationMenuItem[][]>(() => [
  [
    {
      label: 'New',
      icon: 'i-lucide-plus',
      active: under('/simulations/new', '/composites', '/sedml'),
      children: [
        { label: 'Run a simulation', icon: 'i-lucide-play', to: '/simulations/new', description: 'Upload a composite or a COMBINE archive.' },
        { label: 'Write a composite', icon: 'i-lucide-square-pen', to: '/composites/new', description: 'Author a process-bigraph document, then run it.' },
        { label: 'Run SED-ML', icon: 'i-lucide-scale', to: '/sedml', description: 'Run an archive on several solvers and compare them.' }
      ]
    },
    { label: 'Simulations', icon: 'i-lucide-list', to: '/simulations', active: under('/simulations') && !under('/simulations/new') },
    { label: 'Comparisons', icon: 'i-lucide-git-compare', to: '/comparisons' },
    { label: 'Suites', icon: 'i-lucide-list-checks', to: '/suites' },
    { label: 'Datasets', icon: 'i-lucide-files', to: '/datasets' },
    {
      label: 'Registry',
      icon: 'i-lucide-boxes',
      active: under('/environments', '/catalog'),
      children: [
        { label: 'Environments', icon: 'i-lucide-package-check', to: '/environments', description: 'Where documents run, and the interfaces each provides.' },
        { label: 'Catalog', icon: 'i-lucide-boxes', to: '/catalog', description: 'Every registered component and its curation level.' }
      ]
    }
  ],
  [
    { label: 'API docs', icon: 'i-lucide-book-open', to: '/docs', external: true, target: '_blank' },
    { label: 'GitHub', icon: 'i-simple-icons-github', to: 'https://github.com/biosimulations/compose-api', target: '_blank' }
  ]
])

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
        <UTooltip v-for="link in items[1]" :key="link.label" :text="link.label">
          <UButton
            :to="link.to"
            :external="link.external"
            :target="link.target"
            :icon="link.icon"
            :aria-label="link.label"
            color="neutral"
            variant="ghost"
            class="hidden lg:inline-flex"
          />
        </UTooltip>
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
