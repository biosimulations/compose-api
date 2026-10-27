<script setup lang="ts">
import type { Confirmation } from '~/utils/admin'

// Every administrative action is confirmed here first (docs/plan-webapp-admin.md, A3): the dialog names the
// environment, the version and the effect; the slot shows what the action would change, or asks for its inputs.
const open = defineModel<boolean>('open', { required: true })
defineProps<{ confirmation: Confirmation | null, busy?: boolean, error?: string | null, disabled?: boolean }>()
const emit = defineEmits<{ confirm: [] }>()
</script>

<template>
  <UModal v-model:open="open" :title="confirmation?.title" :description="confirmation?.description" :dismissible="!busy">
    <template #body>
      <div class="flex flex-col gap-3 text-sm">
        <slot />
        <UAlert v-if="error" color="error" variant="subtle" icon="i-lucide-circle-alert" :description="error" />
      </div>
    </template>
    <template #footer>
      <div class="flex w-full justify-end gap-2">
        <UButton label="Cancel" color="neutral" variant="ghost" :disabled="busy" @click="open = false" />
        <UButton
          :label="confirmation?.confirm"
          :color="confirmation?.danger ? 'error' : 'primary'"
          :loading="busy"
          :disabled="disabled"
          @click="emit('confirm')"
        />
      </div>
    </template>
  </UModal>
</template>
