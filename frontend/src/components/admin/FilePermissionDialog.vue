<script setup lang="ts">
import { $fetch } from 'ofetch'
import { ref, computed, watch } from 'vue'
import { useCsrf } from '../../composables/useCsrf'
import { useAdmin, type GrantInput } from '../../composables/useAdmin'
import PermissionSelector from './PermissionSelector.vue'

export interface FileWithPermission {
  id: string
  originalName: string
  visibility: 'private' | 'shared'
  grants?: Array<{ grantType: string; grantId: string | null }>
}

const props = defineProps<{
  file: FileWithPermission | null
  uploadFile: File | null
}>()

const emit = defineEmits<{ close: [boolean]; saved: [] }>()

const toast = useToast()
const { csrf, headerName } = useCsrf()
const { fetchPermissionOptions } = useAdmin()

const isEdit = computed(() => Boolean(props.file))

// Dropdown options
const users = ref<Array<{ id: string; name: string; username: string }>>([])
const departments = ref<Array<{ id: string; name: string }>>([])
const optionsLoading = ref(false)

// Current grants
const grants = ref<GrantInput[]>([])
const submitting = ref(false)
const error = ref('')
const open = ref(true)

function onOpenChange(v: boolean) {
  if (!v) emit('close', false)
}

function scopeFromState(file: FileWithPermission): GrantInput[] {
  const existing = file.grants ?? []
  if (existing.length > 0) {
    return existing.map(g => ({
      grantType: g.grantType as GrantInput['grantType'],
      grantId: g.grantId,
    }))
  }
  if (file.visibility === 'shared') {
    return [{ grantType: 'public', grantId: null }]
  }
  return []
}

watch(
  () => props.file,
  (f) => {
    if (f) {
      grants.value = scopeFromState(f)
    }
  },
  { immediate: true },
)

async function loadOptions() {
  optionsLoading.value = true
  try {
    const opts = await fetchPermissionOptions()
    users.value = opts.users
    departments.value = opts.departments
  }
  catch (e: any) {
    error.value = e?.data?.message || 'Failed to load permission options'
  }
  finally {
    optionsLoading.value = false
  }
}

function normalize() {
  const hasPublic = grants.value.some(g => g.grantType === 'public')
  if (hasPublic) {
    return { visibility: 'shared' as const, grants: [] as GrantInput[] }
  }
  return { visibility: 'private' as const, grants: grants.value }
}

async function submit() {
  if (submitting.value) return
  submitting.value = true
  error.value = ''
  try {
    const { visibility, grants: targetGrants } = normalize()

    if (isEdit.value && props.file) {
      await $fetch(`/api/files/${props.file.id}`, {
        method: 'PATCH',
        headers: { [headerName]: csrf() },
        body: { visibility, grants: targetGrants },
      })
      toast.add({ title: 'Permissions updated', color: 'success' })
    }
    else if (props.uploadFile) {
      const formData = new FormData()
      formData.append('file', props.uploadFile)
      formData.append('visibility', visibility)
      formData.append('grants', JSON.stringify(targetGrants))
      await $fetch('/api/files', {
        method: 'POST',
        headers: { [headerName]: csrf() },
        body: formData,
      })
      toast.add({ title: `Uploaded: ${props.uploadFile.name}`, color: 'success' })
    }
    emit('saved')
    emit('close', true)
  }
  catch (e: any) {
    error.value = e?.data?.message || 'Failed to save permissions'
  }
  finally {
    submitting.value = false
  }
}

loadOptions()
</script>

<template>
  <UModal
    v-model:open="open"
    @update:open="onOpenChange"
    :title="isEdit ? 'Configure File Access' : 'Upload File'"
    :description="isEdit ? `Adjust access perimeter for &quot;${file?.originalName}&quot;.` : 'Configure access scope for the uploaded document.'"
    :ui="{
      footer: 'flex-row-reverse justify-start'
    }"
    :close="false"
  >
    <template #body>
      <div class="space-y-4">
        <UAlert v-if="error" :title="error" color="error" variant="soft" icon="i-lucide-circle-alert" />

        <div v-if="isEdit" class="flex items-center gap-2 text-sm text-(--ui-text-muted)">
          <UIcon name="i-lucide-file" class="size-4" />
          <span class="truncate">{{ file?.originalName }}</span>
        </div>
        <div v-else class="flex items-center gap-2 text-sm text-(--ui-text-muted)">
          <UIcon name="i-lucide-upload" class="size-4" />
          <span class="truncate">{{ uploadFile?.name }}</span>
        </div>

        <div v-if="optionsLoading" class="flex justify-center py-8">
          <UIcon name="i-lucide-loader-circle" class="size-5 animate-spin text-(--ui-text-muted)" />
        </div>
        <PermissionSelector
          v-else
          v-model="grants"
          :users="users"
          :departments="departments"
        />
      </div>
    </template>

    <template #footer>
      <UButton
        :label="isEdit ? 'Save' : 'Upload'"
        icon="i-lucide-check"
        :loading="submitting"
        @click="submit"
      />
      <UButton
        color="neutral"
        variant="ghost"
        label="Cancel"
        @click="emit('close', false)"
      />
    </template>
  </UModal>
</template>
