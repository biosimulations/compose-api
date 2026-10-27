<script setup lang="ts">
import type { Schemas } from '~/composables/useApi'
import type { EnvironmentVersion, EnvironmentVersions } from '~/composables/useRegistry'
import type { Confirmation, VersionAction } from '~/utils/admin'

// An environment's administrative actions (docs/plan-webapp-admin.md, step 6), shown only to a caller whose
// capabilities include environments:admin. Each is confirmed in a dialog first, and the API checks every request
// again. The page's version rows start the per-version ones through `act`.
const props = defineProps<{ name: string, kind: string, versions: EnvironmentVersions }>()
const emit = defineEmits<{ changed: [] }>()

const creation = computed(() => creationKind(props.kind))
const defaultNumber = computed(() => props.versions.default ?? null)

// -- making a version ------------------------------------------------------------------------------------------
const today = () => new Date().toISOString().slice(0, 10)
const creating = ref(false)
const asOf = ref(today())
const image = ref('')
const note = ref('')
const createBusy = ref(false)
const createError = ref<string | null>(null)
const createConfirmation = computed(() => creationConfirmation(props.name, creation.value, asOf.value, image.value))
const createInvalid = computed(() => creation.value === 'prebuilt' ? !isDigestReference(image.value) : !asOf.value)

function startCreate() {
  asOf.value = today()
  image.value = ''
  note.value = ''
  createError.value = null
  creating.value = true
}

async function create() {
  createBusy.value = true
  createError.value = null
  try {
    const body = creation.value === 'prebuilt'
      ? { image: image.value.trim(), note: note.value || null }
      // today: now (the API's default); an earlier day: as the end of that day, UTC
      : { resolved_at: asOf.value === today() ? null : `${asOf.value}T23:59:59Z`, note: note.value || null }
    follow(await createVersion(props.name, body))
    creating.value = false
    emit('changed')
  } catch (e) {
    createError.value = (e as Error).message
  } finally {
    createBusy.value = false
  }
}

// -- following a new version until it settles --------------------------------------------------------------------
const followed = ref<EnvironmentVersion | null>(null)
const { pause, resume } = useIntervalFn(async () => {
  if (!followed.value) return pause()
  try {
    const list = await fetchVersions(props.name)
    const now = list.versions?.find(v => v.number === followed.value!.number)
    if (now) followed.value = now
  } catch {
    // the next tick tries again
  }
  if (!followed.value || settled(followed.value.state)) {
    pause()
    emit('changed')
  }
}, 5000, { immediate: false })

function follow(version: EnvironmentVersion) {
  followed.value = version
  if (!settled(version.state)) resume()
}

// -- per-version actions ---------------------------------------------------------------------------------------------
const pending = ref<{ action: VersionAction, version: EnvironmentVersion } | null>(null)
const acting = ref(false)
const actBusy = ref(false)
const actError = ref<string | null>(null)
const actConfirmation = computed<Confirmation | null>(() =>
  pending.value ? confirmation(pending.value.action, props.name, pending.value.version.number, defaultNumber.value) : null)
const notice = ref<string | null>(null)

// what making it the default changes: its packages against the current default's
const changes = ref<Schemas['PackageChange'][] | null>(null)
const changesState = ref<'idle' | 'loading' | 'none' | 'error'>('idle')

async function act(action: VersionAction, version: EnvironmentVersion) {
  pending.value = { action, version }
  actError.value = null
  changes.value = null
  changesState.value = 'idle'
  acting.value = true
  if (action === 'default' && defaultNumber.value != null) {
    changesState.value = 'loading'
    try {
      changes.value = await fetchChanges(props.name, version.number, defaultNumber.value)
      changesState.value = changes.value === null ? 'none' : 'idle'
    } catch {
      changesState.value = 'error'
    }
  }
}

async function confirmAct() {
  if (!pending.value) return
  const { action, version } = pending.value
  actBusy.value = true
  actError.value = null
  try {
    if (action === 'default') await setDefaultVersion(props.name, version.number)
    else if (action === 'retire') await retireVersion(props.name, version.number)
    else await inspectVersion(props.name, version.number)
    notice.value = {
      default: `${props.name}@${version.number} is now the default.`,
      retire: `${props.name}@${version.number} is retired.`,
      inspect: `${props.name}@${version.number} is being read back; its page shows the result in a minute or two.`
    }[action]
    acting.value = false
    emit('changed')
  } catch (e) {
    actError.value = (e as Error).message
  } finally {
    actBusy.value = false
  }
}

defineExpose({ act })
</script>

<template>
  <div class="flex flex-col gap-2">
    <div class="flex flex-wrap items-center gap-2">
      <UButton
        icon="i-lucide-plus"
        :label="creation === 'prebuilt' ? 'Register an image' : 'New version'"
        size="sm"
        color="primary"
        variant="subtle"
        @click="startCreate"
      />
      <span class="text-xs text-muted">You can administer environments.</span>
    </div>
    <UAlert
      v-if="notice"
      color="success"
      variant="subtle"
      icon="i-lucide-circle-check"
      :description="notice"
      :close="true"
      @update:open="notice = null"
    />
    <UAlert
      v-if="followed"
      :color="followed.state === 'failed' ? 'error' : followed.state === 'ready' ? 'success' : 'info'"
      variant="subtle"
      :icon="settled(followed.state) ? (followed.state === 'failed' ? 'i-lucide-circle-x' : 'i-lucide-circle-check') : 'i-lucide-loader-circle'"
      :title="`${name}@${followed.number} is ${followed.state}`"
      :close="settled(followed.state)"
      @update:open="followed = null"
    >
      <template #description>
        <p v-if="followed.failure" class="whitespace-pre-wrap font-mono text-xs">{{ followed.failure }}</p>
        <p v-else-if="!settled(followed.state)">Checked every 5 seconds. Resolving and building can take several minutes.</p>
        <p v-else-if="followed.state === 'ready'">
          <NuxtLink :to="`/environments/${encodeURIComponent(name)}/versions/${followed.number}`" class="text-primary">
            Compare its packages with the default
          </NuxtLink>, then make it the default when it is right.
        </p>
      </template>
    </UAlert>

    <ConfirmDialog
      v-model:open="creating"
      :confirmation="createConfirmation"
      :busy="createBusy"
      :error="createError"
      :disabled="createInvalid"
      @confirm="create"
    >
      <UFormField v-if="creation === 'composed'" label="Resolve its entries as of" help="Its dependencies as they were published by this date (today: now).">
        <UInput v-model="asOf" type="date" :max="today()" />
      </UFormField>
      <UFormField
        v-else
        label="Image, by digest"
        :error="image && !isDigestReference(image) ? 'Use repository@sha256:<64 hex digits>; tags are refused' : undefined"
      >
        <UInput v-model="image" placeholder="ghcr.io/org/image@sha256:…" class="w-full font-mono" />
      </UFormField>
      <UFormField label="Note" help="Why this version: shown beside it.">
        <UInput v-model="note" class="w-full" />
      </UFormField>
    </ConfirmDialog>

    <ConfirmDialog
      v-model:open="acting"
      :confirmation="actConfirmation"
      :busy="actBusy"
      :error="actError"
      :disabled="changesState === 'loading'"
      @confirm="confirmAct"
    >
      <template v-if="pending?.action === 'default' && defaultNumber != null">
        <p v-if="changesState === 'loading'" class="text-muted">Comparing its packages with {{ name }}@{{ defaultNumber }}…</p>
        <p v-else-if="changesState === 'none'" class="text-muted">One of the two has no packages read back, so they cannot be compared.</p>
        <p v-else-if="changesState === 'error'" class="text-warning">Its packages could not be compared with the default's.</p>
        <template v-else-if="changes">
          <p>
            {{ changes.length }} package{{ changes.length === 1 ? ' differs' : 's differ' }} from {{ name }}@{{ defaultNumber }}<template v-if="!changes.length">: the same packages</template>.
          </p>
          <table v-if="changes.length" class="text-xs">
            <tbody>
              <tr v-for="c in changes.slice(0, 20)" :key="c.name" class="border-t border-default">
                <td class="pr-3 py-0.5 font-mono">{{ c.name }}</td>
                <td class="pr-3 text-muted">{{ c.before ?? 'added' }}</td>
                <td>{{ c.after ?? 'removed' }}</td>
              </tr>
            </tbody>
          </table>
          <NuxtLink v-if="changes.length > 20" :to="`/environments/${encodeURIComponent(name)}/versions/${pending.version.number}`" class="text-primary text-xs">
            and {{ changes.length - 20 }} more on its page
          </NuxtLink>
        </template>
      </template>
    </ConfirmDialog>
  </div>
</template>
