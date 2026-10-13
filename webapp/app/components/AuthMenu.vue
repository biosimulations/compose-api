<script setup lang="ts">
// After ../platform/frontend/app/components/AuthMenu.client.vue. Renders nothing unless the API publishes an
// Auth0 configuration (see plugins/auth.client.ts).
const { enabled, isAuthenticated, isLoading, user, error, login, logout } = useAuth()
</script>

<template>
  <div v-if="enabled" class="flex items-center gap-2">
    <USkeleton v-if="isLoading" class="h-8 w-20" />
    <UButton v-else-if="!isAuthenticated" label="Sign in" variant="ghost" color="neutral" leading-icon="i-lucide-user" @click="login()" />
    <UDropdownMenu v-else :items="[[{ label: 'Sign out', icon: 'i-lucide-log-out', onSelect: () => logout() }]]">
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
