<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import type { GrantInput } from '../../composables/useAdmin'

const props = defineProps<{
  /** 当前授权记录，v-model */
  modelValue: GrantInput[]
  users: Array<{ id: string; name: string; username?: string }>
  departments: Array<{ id: string; name: string }>
  disabled?: boolean
}>()

const emit = defineEmits<{ 'update:modelValue': [GrantInput[]] }>()

type Scope = 'private' | 'public' | 'user' | 'department'

const scope = ref<Scope>(toScope(props.modelValue))
const selectedUserIds = ref<string[]>(initialUserIds(props.modelValue))
const selectedDeptIds = ref<string[]>(initialDeptIds(props.modelValue))

function toScope(grants: GrantInput[]): Scope {
  if (!grants || grants.length === 0) return 'private'
  if (grants.some(g => g.grantType === 'public')) return 'public'
  if (grants.some(g => g.grantType === 'user')) return 'user'
  if (grants.some(g => g.grantType === 'department')) return 'department'
  return 'private'
}

function initialUserIds(grants: GrantInput[]): string[] {
  return grants.filter(g => g.grantType === 'user' && g.grantId).map(g => g.grantId!)
}

function initialDeptIds(grants: GrantInput[]): string[] {
  return grants.filter(g => g.grantType === 'department' && g.grantId).map(g => g.grantId!)
}

function emitGrants() {
  let grants: GrantInput[] = []
  switch (scope.value) {
    case 'public':
      grants = [{ grantType: 'public', grantId: null }]
      break
    case 'user':
      grants = selectedUserIds.value.map(id => ({ grantType: 'user', grantId: id }))
      break
    case 'department':
      grants = selectedDeptIds.value.map(id => ({ grantType: 'department', grantId: id }))
      break
    default:
      grants = []
  }
  emit('update:modelValue', grants)
}

watch(scope, emitGrants)
watch(selectedUserIds, emitGrants)
watch(selectedDeptIds, emitGrants)

const userOptions = computed(() =>
  props.users.map(u => ({ label: u.name || u.username || u.id, value: u.id }))
)
const deptOptions = computed(() =>
  props.departments.map(d => ({ label: d.name, value: d.id }))
)

const scopeOptions: Array<{ label: string; value: Scope }> = [
  { label: '仅自己', value: 'private' },
  { label: '全员', value: 'public' },
  { label: '指定用户', value: 'user' },
  { label: '指定部门', value: 'department' },
]
</script>

<template>
  <div class="space-y-3">
    <URadioGroup
      v-model="scope"
      :items="scopeOptions"
      :disabled="disabled"
      class="gap-2"
    />

    <div v-if="scope === 'user'" class="space-y-2">
      <p class="text-sm text-(--ui-text-muted)">选择可以访问此文件的用户：</p>
      <UCheckboxGroup v-model="selectedUserIds" :items="userOptions" :disabled="disabled" />
    </div>

    <div v-else-if="scope === 'department'" class="space-y-2">
      <p class="text-sm text-(--ui-text-muted)">选择可以访问此文件的部门：</p>
      <UCheckboxGroup v-model="selectedDeptIds" :items="deptOptions" :disabled="disabled" />
    </div>
  </div>
</template>
