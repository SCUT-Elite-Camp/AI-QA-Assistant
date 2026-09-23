<script setup lang="ts">
import { ref, computed } from 'vue'
import { useAdmin, type AdminUser, type Department } from '../../composables/useAdmin'

const props = defineProps<{
  user: AdminUser
  departments: Department[]
}>()

const emit = defineEmits<{ close: [boolean]; updated: [] }>()

const { updateUser } = useAdmin()
const toast = useToast()

const form = ref({
  email: props.user.email ?? '',
  name: props.user.name ?? '',
  username: props.user.username ?? '',
  avatar: props.user.avatar ?? '',
  role: props.user.role as 'admin' | 'user',
  ssoId: props.user.ssoId ?? '',
  disabled: Boolean(props.user.disabled),
  departmentIds: [...(props.user.departmentIds ?? [])],
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
    await updateUser(props.user.id, {
      email: form.value.email.trim(),
      name: form.value.name.trim(),
      username: form.value.username.trim(),
      avatar: form.value.avatar.trim() || undefined,
      role: form.value.role,
      ssoId: form.value.ssoId.trim() || undefined,
      disabled: form.value.disabled,
      departmentIds: form.value.departmentIds,
    })
    toast.add({ title: 'User updated', color: 'success' })
    emit('updated')
    emit('close', true)
  }
  catch (e: any) {
    error.value = e?.data?.message || 'Failed to update user'
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
    title="Edit user"
    description="Update profile, role, departments or disable the account."
    :ui="{
      footer: 'flex-row-reverse justify-start'
    }"
    :close="false"
  >
    <template #body>
      <div class="space-y-4">
        <UAlert v-if="error" :title="error" color="error" variant="soft" icon="i-lucide-circle-alert" />

        <UFormField label="Email" required>
          <UInput v-model="form.email" type="email" class="w-full" />
        </UFormField>

        <div class="grid grid-cols-2 gap-3">
          <UFormField label="Name" required>
            <UInput v-model="form.name" class="w-full" />
          </UFormField>
          <UFormField label="Username" required>
            <UInput v-model="form.username" class="w-full" />
          </UFormField>
        </div>

        <div class="grid grid-cols-2 gap-3">
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
          <UFormField label="SSO ID" hint="For SSO/LDAP users">
            <UInput v-model="form.ssoId" class="w-full" />
          </UFormField>
        </div>

        <UFormField label="Departments">
          <UCheckboxGroup v-model="form.departmentIds" :items="departmentOptions" />
        </UFormField>

        <UFormField label="Avatar URL">
          <UInput v-model="form.avatar" class="w-full" />
        </UFormField>

        <UCheckbox v-model="form.disabled" label="禁用该用户" description="禁止此用户登录系统。" />
      </div>
    </template>

    <template #footer>
      <UButton
        label="Save"
        icon="i-lucide-save"
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
