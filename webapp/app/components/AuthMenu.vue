<script setup lang="ts">
import type { DropdownMenuItem } from '@nuxt/ui'

// After ../platform/frontend/app/components/AuthMenu.client.vue. Renders nothing unless the API publishes an
// Auth0 configuration (see plugins/webapp-config.client.ts).
const { enabled, isAuthenticated, isLoading, user, principal, error, login, signup, logout } = useAuth()

const items = computed<DropdownMenuItem[][]>(() => [
  [
    {
      type: 'label',
      label: user.value?.email || user.value?.name || 'Signed in',
      // Roles as the API sees them (GET /auth/me), which is what it authorizes by.
      description: principal.value ? `Roles: ${principal.value.roles.join(', ') || 'none'}` : undefined
    }
  ],
  // what the API says this caller may do (A2): administration sits next to what it acts on, so link there
  ...(canAdminister(principal.value?.capabilities)
    ? [[{ label: 'You can administer environments', icon: 'i-lucide-shield-check', to: '/environments' }]]
    : []),
  [{ label: 'Sign out', icon: 'i-lucide-log-out', onSelect: () => logout() }]
])
</script>

<template>
  <div v-if="enabled" class="flex items-center gap-1">
    <USkeleton v-if="isLoading" class="h-8 w-20" />
    <template v-else-if="!isAuthenticated">
      <UButton label="Sign in" variant="ghost" color="neutral" leading-icon="i-lucide-user" @click="login()" />
      <UButton label="Create account" variant="ghost" color="neutral" class="hidden sm:inline-flex" @click="signup()" />
    </template>
    <UDropdownMenu v-else :items="items">
      <UButton
        :label="user?.name || user?.email || 'Account'"
        leading-icon="i-lucide-user-circle"
        trailing-icon="i-lucide-chevron-down"
        color="neutral"
        variant="ghost"
      />
    </UDropdownMenu>
    <UTooltip v-if="error" :text="error.message">
      <UIcon name="i-lucide-circle-alert" class="text-error" />
    </UTooltip>
  </div>
</template>
