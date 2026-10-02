<route lang="yaml">
meta:
  layout: admin
</route>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import DepartmentCreateDialog from '../../components/admin/DepartmentCreateDialog.vue'
import ModalConfirm from '../../components/ModalConfirm.vue'
import { useAdmin, useAdminAccess } from '../../composables/useAdmin'
import type { Department } from '../../composables/useAdmin'

const { listDepartments, deleteDepartment } = useAdmin()
const { checking, allowed, check } = useAdminAccess()
const toast = useToast()

const departments = ref<Department[]>([])
const loading = ref(false)
const error = ref('')

const showCreate = ref(false)
const editingDepartment = ref<Department | null>(null)
const deletingDepartment = ref<Department | null>(null)

const treeRows = computed(() => {
  const childrenOf = new Map<string | null, Department[]>()
  for (const d of departments.value) {
    const key = d.parentId ?? null
    if (!childrenOf.has(key)) childrenOf.set(key, [])
    childrenOf.get(key)!.push(d)
  }
  const rows: Array<{ id: string; name: string; userCount: number; depth: number; isLast?: boolean }> = []
  const walk = (parentId: string | null, depth: number) => {
    const children = childrenOf.get(parentId) ?? []
    for (const c of children) {
      rows.push({ id: c.id, name: c.name, userCount: c.userCount, depth })
      walk(c.id, depth + 1)
    }
  }
  walk(null, 0)
  return rows
})

async function load() {
  loading.value = true
  error.value = ''
  try {
    const result = await listDepartments()
    departments.value = result
  }
  catch (e: any) {
    error.value = e?.data?.message || e?.message || 'Failed to load departments'
  }
  finally {
    loading.value = false
  }
}

function onSaved() {
  toast.add({ title: '部门信息已保存', color: 'success' })
  load()
}

async function confirmDelete(confirmed: boolean) {
  if (!confirmed || !deletingDepartment.value) return
  try {
    await deleteDepartment(deletingDepartment.value.id)
    toast.add({ title: '部门已删除', color: 'success' })
    deletingDepartment.value = null
    load()
  }
  catch (e: any) {
    toast.add({ title: e?.data?.message || '删除部门失败', color: 'error' })
    deletingDepartment.value = null
  }
}

onMounted(async () => {
  await check()
  if (allowed.value) await load()
})
</script>

<template>
  <div class="space-y-6">
    <!-- Header Title -->
    <div class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 pb-2 border-b border-zinc-200 dark:border-zinc-800">
      <div>
        <h1 class="text-2xl font-bold tracking-tight text-zinc-900 dark:text-white">组织与部门架构</h1>
        <p class="text-sm text-zinc-500 dark:text-zinc-400 mt-1">管理企业与系统层级架构部门，分配用户所属组织</p>
      </div>
      <div class="flex items-center gap-2">
        <UButton
          label="新建部门"
          icon="i-lucide-building-2"
          color="primary"
          size="sm"
          class="shadow-xs font-medium"
          @click="showCreate = true"
        />
        <UButton
          icon="i-lucide-refresh-cw"
          color="neutral"
          variant="outline"
          size="sm"
          :loading="loading"
          @click="load"
        />
      </div>
    </div>

    <!-- Loading State -->
    <template v-if="checking || loading && !departments.length">
      <div class="flex flex-col items-center justify-center py-20 gap-3">
        <UIcon name="i-lucide-loader-circle" class="size-8 animate-spin text-primary-500" />
        <p class="text-sm text-zinc-400">正在载入部门架构...</p>
      </div>
    </template>

    <template v-else>
      <UAlert v-if="error" :title="error" color="error" variant="soft" icon="i-lucide-circle-alert" />

      <!-- Departments Table Card -->
      <UCard :ui="{ body: 'p-0' }" class="border border-zinc-200 dark:border-zinc-800/80 shadow-xs overflow-hidden">
        <UTable
          :data="treeRows"
          :columns="[
            { accessorKey: 'name', header: '部门名称' },
            { accessorKey: 'userCount', header: '成员人数' },
            { id: 'actions', header: '操作' },
          ]"
          :loading="loading"
          :ui="{ td: 'whitespace-nowrap py-3' }"
        >
          <template #name-cell="{ row }">
            <div class="flex items-center gap-2">
              <span
                v-for="i in row.original.depth"
                :key="i"
                class="inline-block w-4 border-l border-zinc-300 dark:border-zinc-700"
              />
              <UIcon name="i-lucide-folder" class="size-4 text-primary-500" />
              <span class="text-sm font-medium text-zinc-900 dark:text-zinc-100">{{ row.original.name }}</span>
            </div>
          </template>

          <template #userCount-cell="{ row }">
            <span class="text-sm text-zinc-600 dark:text-zinc-400">{{ row.original.userCount }} 人</span>
          </template>

          <template #actions-cell="{ row }">
            <div class="flex items-center justify-end gap-1">
              <UButton
                icon="i-lucide-pencil"
                color="neutral"
                variant="ghost"
                size="sm"
                title="编辑部门"
                @click="editingDepartment = departments.find(d => d.id === row.original.id) ?? null"
              />
              <UButton
                icon="i-lucide-trash-2"
                color="error"
                variant="ghost"
                size="sm"
                title="删除部门"
                @click="deletingDepartment = departments.find(d => d.id === row.original.id) ?? null"
              />
            </div>
          </template>
        </UTable>
      </UCard>

      <DepartmentCreateDialog
        v-if="showCreate"
        :department="null"
        :departments="departments"
        @close="showCreate = false"
        @saved="onSaved"
      />

      <DepartmentCreateDialog
        v-if="editingDepartment"
        :department="editingDepartment"
        :departments="departments"
        @close="editingDepartment = null"
        @saved="onSaved"
      />

      <ModalConfirm
        v-if="deletingDepartment"
        title="确认删除部门"
        :description="`确定要删除部门“${deletingDepartment.name}”吗？其子部门将被移至顶层，成员关联将被移除。`"
        color="error"
        @close="confirmDelete"
      />
    </template>
  </div>
</template>
