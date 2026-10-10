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

const totalMembers = computed(() => {
  return departments.value.reduce((acc, d) => acc + (d.userCount || 0), 0)
})

const rootDeptsCount = computed(() => {
  return departments.value.filter(d => !d.parentId).length
})

const treeRows = computed(() => {
  const childrenOf = new Map<string | null, Department[]>()
  for (const d of departments.value) {
    const key = d.parentId ?? null
    if (!childrenOf.has(key)) childrenOf.set(key, [])
    childrenOf.get(key)!.push(d)
  }
  const rows: Array<{ id: string; name: string; userCount: number; depth: number; hasChildren: boolean }> = []
  const walk = (parentId: string | null, depth: number) => {
    const children = childrenOf.get(parentId) ?? []
    for (const c of children) {
      const cChildren = childrenOf.get(c.id) ?? []
      rows.push({
        id: c.id,
        name: c.name,
        userCount: c.userCount,
        depth,
        hasChildren: cChildren.length > 0
      })
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
  toast.add({ title: 'Department saved successfully', color: 'success' })
  load()
}

async function confirmDelete(confirmed: boolean) {
  if (!confirmed || !deletingDepartment.value) return
  try {
    await deleteDepartment(deletingDepartment.value.id)
    toast.add({ title: 'Department deleted successfully', color: 'success' })
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
  <div class="space-y-6">
    <!-- Header Title -->
    <div class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 pb-6 border-b border-zinc-200/80 dark:border-zinc-800/80">
      <div class="space-y-1">
        <h1 class="text-2xl sm:text-3xl font-bold tracking-tight text-zinc-950 dark:text-white">
          Organization & Departments
        </h1>
        <p class="text-sm text-zinc-500 dark:text-zinc-400">
          Manage organizational tree hierarchy and track department memberships
        </p>
      </div>
      <div class="flex items-center gap-2.5">
        <UButton
          label="New Department"
          icon="i-lucide-building-2"
          color="primary"
          size="sm"
          class="rounded-xl shadow-xs font-semibold px-4 py-2"
          @click="showCreate = true"
        />
        <UButton
          icon="i-lucide-refresh-cw"
          color="neutral"
          variant="outline"
          size="sm"
          :loading="loading"
          class="rounded-xl shadow-2xs font-medium"
          @click="load"
        />
      </div>
    </div>

    <!-- Loading State -->
    <template v-if="checking || (loading && !departments.length)">
      <div class="flex flex-col items-center justify-center py-24 gap-3">
        <UIcon name="i-lucide-loader-circle" class="size-8 animate-spin text-zinc-900 dark:text-white" />
        <p class="text-sm text-zinc-400">Loading organization hierarchy...</p>
      </div>
    </template>

    <template v-else>
      <UAlert v-if="error" :title="error" color="error" variant="soft" icon="i-lucide-circle-alert" class="rounded-2xl" />

      <!-- Quick Department Stats Ribbon -->
      <div class="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <div class="rounded-2xl bg-white/70 dark:bg-zinc-900/70 border border-zinc-200/80 dark:border-zinc-800/80 p-4 backdrop-blur-xl shadow-xs flex items-center gap-3.5">
          <div class="w-10 h-10 rounded-xl bg-purple-500/10 text-purple-600 dark:text-purple-400 flex items-center justify-center">
            <UIcon name="i-lucide-building-2" class="w-5 h-5" />
          </div>
          <div>
            <p class="text-xs font-medium text-zinc-500 uppercase tracking-wider">Total Departments</p>
            <p class="text-xl font-bold text-zinc-950 dark:text-white mt-0.5">{{ departments.length }} <span class="text-xs font-normal text-zinc-400">units</span></p>
          </div>
        </div>

        <div class="rounded-2xl bg-white/70 dark:bg-zinc-900/70 border border-zinc-200/80 dark:border-zinc-800/80 p-4 backdrop-blur-xl shadow-xs flex items-center gap-3.5">
          <div class="w-10 h-10 rounded-xl bg-blue-500/10 text-blue-600 dark:text-blue-400 flex items-center justify-center">
            <UIcon name="i-lucide-network" class="w-5 h-5" />
          </div>
          <div>
            <p class="text-xs font-medium text-zinc-500 uppercase tracking-wider">Root Divisions</p>
            <p class="text-xl font-bold text-zinc-950 dark:text-white mt-0.5">{{ rootDeptsCount }} <span class="text-xs font-normal text-zinc-400">top-level</span></p>
          </div>
        </div>

        <div class="rounded-2xl bg-white/70 dark:bg-zinc-900/70 border border-zinc-200/80 dark:border-zinc-800/80 p-4 backdrop-blur-xl shadow-xs flex items-center gap-3.5">
          <div class="w-10 h-10 rounded-xl bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 flex items-center justify-center">
            <UIcon name="i-lucide-users" class="w-5 h-5" />
          </div>
          <div>
            <p class="text-xs font-medium text-zinc-500 uppercase tracking-wider">Allocated Members</p>
            <p class="text-xl font-bold text-zinc-950 dark:text-white mt-0.5">{{ totalMembers }} <span class="text-xs font-normal text-zinc-400">members</span></p>
          </div>
        </div>
      </div>

      <!-- Departments Acrylic Table Card -->
      <div class="rounded-2xl bg-white/80 dark:bg-zinc-900/80 border border-zinc-200/90 dark:border-zinc-800/80 backdrop-blur-xl shadow-xs overflow-hidden">
        <UTable
          :data="treeRows"
          :columns="[
            { accessorKey: 'name', header: 'Hierarchy Structure' },
            { accessorKey: 'userCount', header: 'Members' },
            { id: 'actions', header: 'Actions' },
          ]"
          :loading="loading"
          :ui="{
            thead: 'bg-zinc-50/70 dark:bg-zinc-900/50 border-b border-zinc-200/80 dark:border-zinc-800/80 text-xs font-semibold text-zinc-500 uppercase tracking-wider',
            td: 'whitespace-nowrap py-3.5 px-4 text-sm'
          }"
        >
          <template #name-cell="{ row }">
            <div class="flex items-center gap-2">
              <span
                v-for="i in row.original.depth"
                :key="i"
                class="inline-block w-5 border-l-2 border-zinc-200 dark:border-zinc-700 h-6 -my-1 ml-1"
              />
              <div
                class="w-7 h-7 rounded-lg flex items-center justify-center shrink-0"
                :class="row.original.depth === 0 ? 'bg-purple-500/10 text-purple-600 dark:text-purple-400' : 'bg-zinc-100 dark:bg-zinc-800 text-zinc-500'"
              >
                <UIcon :name="row.original.hasChildren ? 'i-lucide-folder-tree' : 'i-lucide-folder'" class="w-4 h-4" />
              </div>
              <span class="text-sm font-semibold text-zinc-900 dark:text-zinc-100">
                {{ row.original.name }}
              </span>
              <span v-if="row.original.depth === 0" class="text-[10px] px-1.5 py-0.5 rounded font-mono bg-zinc-100 dark:bg-zinc-800 text-zinc-500">
                ROOT
              </span>
            </div>
          </template>

          <template #userCount-cell="{ row }">
            <UBadge
              color="neutral"
              variant="subtle"
              size="sm"
              class="rounded-lg font-medium px-2.5 py-0.5"
            >
              <UIcon name="i-lucide-user" class="w-3 h-3 mr-1 text-zinc-400" />
              {{ row.original.userCount }} members
            </UBadge>
          </template>

          <template #actions-cell="{ row }">
            <div class="flex items-center justify-end gap-1.5">
              <UButton
                icon="i-lucide-pencil"
                color="neutral"
                variant="ghost"
                size="sm"
                class="rounded-lg"
                title="Edit Department"
                @click="editingDepartment = departments.find(d => d.id === row.original.id) ?? null"
              />
              <UButton
                icon="i-lucide-trash-2"
                color="error"
                variant="ghost"
                size="sm"
                class="rounded-lg"
                title="Delete Department"
                @click="deletingDepartment = departments.find(d => d.id === row.original.id) ?? null"
              />
            </div>
          </template>
        </UTable>

        <!-- Empty state fallback -->
        <div v-if="!treeRows.length" class="flex flex-col items-center justify-center py-16 text-center space-y-2">
          <UIcon name="i-lucide-building" class="w-10 h-10 text-zinc-300 dark:text-zinc-600" />
          <p class="text-sm font-medium text-zinc-600 dark:text-zinc-400">No departments configured</p>
          <p class="text-xs text-zinc-400">Click "New Department" above to create your first organization unit</p>
        </div>
      </div>

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
        title="Confirm Delete Department"
        :description="`Are you sure you want to delete department &quot;${deletingDepartment.name}&quot;? Child departments will be moved to the root level.`"
        color="error"
        @close="confirmDelete"
      />
    </template>
  </div>
</template>
