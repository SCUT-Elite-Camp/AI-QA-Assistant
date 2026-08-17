<script setup lang="ts">
import { ref, computed } from 'vue'
import { useAdmin, type Department } from '../../composables/useAdmin'

const props = defineProps<{
  /** 传入时为编辑模式，否则为创建模式 */
  department?: Department | null
  departments: Department[]
}>()

const emit = defineEmits<{ close: [boolean]; saved: [] }>()

const { createDepartment, updateDepartment } = useAdmin()
const toast = useToast()

// 用非空字符串作为“根部门”占位值（SelectItem 不允许空字符串 value）
const ROOT_VALUE = '__root__'

const isEdit = computed(() => Boolean(props.department))

const form = ref({
  name: props.department?.name ?? '',
  parentId: props.department?.parentId ?? ROOT_VALUE, // 根部门 → 显示占位项
})
const submitting = ref(false)
const error = ref('')
const open = ref(true)

function onOpenChange(v: boolean) {
  if (!v) emit('close', false)
}

const parentOptions = computed(() => {
  const selfId = props.department?.id
  const flatten = (deps: Department[], depth = 0): Array<{ label: string; value: string }> => {
    const result: Array<{ label: string; value: string }> = []
    for (const d of deps) {
      if (d.id === selfId) continue // 不能选择自己作为父级，避免环
      result.push({ label: '— '.repeat(depth) + d.name, value: d.id })
      const children = props.departments.filter(c => c.parentId === d.id)
      result.push(...flatten(children, depth + 1))
    }
    return result
  }
  return [{ label: 'No parent (root)', value: ROOT_VALUE }, ...flatten(props.departments.filter(d => !d.parentId))]
})

const canSubmit = computed(() => Boolean(form.value.name.trim()))

async function submit() {
  if (!canSubmit.value || submitting.value) return
  submitting.value = true
  error.value = ''
  try {
    const payload = {
      name: form.value.name.trim(),
      parentId: form.value.parentId === ROOT_VALUE ? null : form.value.parentId,
    }
    if (isEdit.value && props.department) {
      await updateDepartment(props.department.id, payload)
    }
    else {
      await createDepartment(payload)
    }
    toast.add({ title: isEdit.value ? 'Department updated' : 'Department created', color: 'success' })
    emit('saved')
    emit('close', true)
  }
  catch (e: any) {
    error.value = e?.data?.message || 'Failed to save department'
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
    :title="isEdit ? 'Edit department' : 'Create department'"
    :description="isEdit ? 'Rename the department or move it under a new parent.' : 'Create a new department to organize users.'"
    :ui="{
      footer: 'flex-row-reverse justify-start'
    }"
    :close="false"
  >
    <template #body>
      <div class="space-y-4">
        <UAlert v-if="error" :title="error" color="error" variant="soft" icon="i-lucide-circle-alert" />

        <UFormField label="Name" required>
          <UInput v-model="form.name" placeholder="e.g. Retail Banking" class="w-full" />
        </UFormField>

        <UFormField label="Parent department" hint="Optional, supports hierarchy">
          <USelect
            v-model="form.parentId"
            :items="parentOptions"
            value-key="value"
            class="w-full"
          />
        </UFormField>
      </div>
    </template>

    <template #footer>
      <UButton
        :label="isEdit ? 'Save' : 'Create'"
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
