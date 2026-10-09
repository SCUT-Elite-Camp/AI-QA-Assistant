<script setup lang="ts">
import { ref, computed } from 'vue'
import { useAdmin, type Department } from '../../composables/useAdmin'

const props = defineProps<{
  departments: Department[]
}>()

const emit = defineEmits<{ close: [boolean]; created: [] }>()

const { createUser } = useAdmin()
const toast = useToast()

const form = ref({
  email: '',
  name: '',
  username: '',
  avatar: '',
  role: 'user' as 'admin' | 'user',
  ssoId: '',
  departmentIds: [] as string[],
})
const submitting = ref(false)
const error = ref('')
const open = ref(true)

function onOpenChange(v: boolean) {
  if (!v) emit('close', false)
}

const canSubmit = computed(() =>
  Boolean(form.value.email.trim() && form.value.name.trim() && form.value.username.trim())
)

const departmentOptions = computed(() =>
  props.departments.map(d => ({ label: d.name, value: d.id }))
)

async function submit() {
  if (!canSubmit.value || submitting.value) return
  submitting.value = true
  error.value = ''
  try {
    await createUser({
      email: form.value.email.trim(),
      name: form.value.name.trim(),
      username: form.value.username.trim(),
      avatar: form.value.avatar.trim() || undefined,
      role: form.value.role,
      ssoId: form.value.ssoId.trim() || undefined,
      departmentIds: form.value.departmentIds,
    })
    toast.add({ title: 'User created', color: 'success' })
    emit('created')
    emit('close', true)
  }
  catch (e: any) {
    error.value = e?.data?.message || 'Failed to create user'
  }
  finally {
    submitting.value = false
  }
}
</script>

<template>
  <UModal
    v-model:open="open"
    @update:open="onOpenChange"
    title="Create user"
    description="Create a user account and assign departments."
    :ui="{
      footer: 'flex-row-reverse justify-start'
    }"
    :close="false"
  >
    <template #body>
      <div class="space-y-4">
        <UAlert v-if="error" :title="error" color="error" variant="soft" icon="i-lucide-circle-alert" />

        <UFormField label="Email" required>
          <UInput v-model="form.email" type="email" placeholder="user@example.com" class="w-full" />
        </UFormField>

        <div class="grid grid-cols-2 gap-3">
          <UFormField label="Name" required>
            <UInput v-model="form.name" placeholder="Full name" class="w-full" />
          </UFormField>
          <UFormField label="Username" required>
            <UInput v-model="form.username" placeholder="username" class="w-full" />
          </UFormField>
        </div>

        <UFormField label="Role">
          <USelect
            v-model="form.role"
            :items="[
              { label: 'User', value: 'user' },
              { label: 'Admin', value: 'admin' }
            ]"
            value-key="value"
            class="w-full"
          />
        </UFormField>

        <UFormField label="Departments">
          <UCheckboxGroup v-model="form.departmentIds" :items="departmentOptions" />
        </UFormField>

        <div class="grid grid-cols-2 gap-3">
          <UFormField label="SSO ID" hint="Optional, for SSO/LDAP users">
            <UInput v-model="form.ssoId" placeholder="sso-user-id" class="w-full" />
          </UFormField>
          <UFormField label="Avatar URL" hint="Optional">
            <UInput v-model="form.avatar" placeholder="https://..." class="w-full" />
          </UFormField>
        </div>
      </div>
    </template>

    <template #footer>
      <UButton
        label="Create"
        icon="i-lucide-user-plus"
        :loading="submitting"
        :disabled="!canSubmit"
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
