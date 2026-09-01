<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import Navbar from '../../components/Navbar.vue'
import AdminNav from '../../components/admin/AdminNav.vue'
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
  toast.add({ title: 'Department saved', color: 'success' })
  load()
}

async function confirmDelete(confirmed: boolean) {
  if (!confirmed || !deletingDepartment.value) return
  try {
    await deleteDepartment(deletingDepartment.value.id)
    toast.add({ title: 'Department deleted', color: 'success' })
    deletingDepartment.value = null
    load()
  }
  catch (e: any) {
    toast.add({ title: e?.data?.message || 'Failed to delete department', color: 'error' })
    deletingDepartment.value = null
  }
}

onMounted(async () => {
  await check()
  if (allowed.value) await load()
})
</script>

<template>
  <UDashboardPanel
    id="admin-departments"
    class="min-h-0"
    :ui="{ body: 'p-0 sm:p-0' }"
  >
    <template #header>
      <Navbar />
    </template>

    <template #body>
      <UContainer class="flex-1 py-6 sm:py-8 space-y-6">
        <AdminNav />

        <template v-if="checking">
          <div class="flex justify-center py-16">
            <UIcon name="i-lucide-loader-circle" class="size-6 animate-spin text-(--ui-text-muted)" />
          </div>
        </template>

        <template v-else-if="!allowed">
          <UCard>
            <div class="flex flex-col items-center gap-3 py-12 text-center">
              <UIcon name="i-lucide-shield-alert" class="size-10 text-(--ui-text-muted)" />
              <h2 class="text-lg font-semibold">Access denied</h2>
              <p class="text-sm text-(--ui-text-muted)">You need administrator privileges to view this page.</p>
            </div>
          </UCard>
        </template>

        <template v-else>
          <UAlert v-if="error" :title="error" color="error" variant="soft" icon="i-lucide-circle-alert" />

          <div class="flex items-center justify-between">
            <div>
              <h2 class="text-lg font-semibold">Departments</h2>
              <p class="text-sm text-(--ui-text-muted)">Organize users into departments with hierarchy.</p>
            </div>
            <UButton
              label="Create department"
              icon="i-lucide-building-2-plus"
              @click="showCreate = true"
            />
          </div>

          <UCard :ui="{ body: 'p-0' }">
            <UTable
              :data="treeRows"
              :columns="[
                { accessorKey: 'name', header: 'Name' },
                { accessorKey: 'userCount', header: 'Users' },
                { id: 'actions', header: ' ' },
              ]"
              :loading="loading"
              :ui="{ td: { base: 'whitespace-nowrap' } }"
            >
              <template #name-cell="{ row }">
                <div class="flex items-center gap-2">
                  <span
                    v-for="i in row.original.depth"
                    :key="i"
                    class="inline-block w-4 border-l border-(--ui-border)"
                  />
                  <UIcon name="i-lucide-folder" class="size-4 text-(--ui-text-muted)" />
                  <span class="text-sm font-medium">{{ row.original.name }}</span>
                </div>
              </template>

              <template #userCount-cell="{ row }">
                <span class="text-sm text-(--ui-text-muted)">{{ row.original.userCount }} user{{ row.original.userCount === 1 ? '' : 's' }}</span>
              </template>

              <template #actions-cell="{ row }">
                <div class="flex items-center justify-end gap-1">
                  <UButton
                    icon="i-lucide-pencil"
                    color="neutral"
                    variant="ghost"
                    size="sm"
                    title="Edit department"
                    @click="editingDepartment = departments.find(d => d.id === row.original.id) ?? null"
                  />
                  <UButton
                    icon="i-lucide-trash-2"
                    color="error"
                    variant="ghost"
                    size="sm"
                    title="Delete department"
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
            title="Delete department"
            :description="`Delete ${deletingDepartment.name}? Child departments will be moved to top level and members will lose access via this department.`"
            color="error"
            @close="confirmDelete"
          />
        </template>
      </UContainer>
    </template>
  </UDashboardPanel>
</template>
