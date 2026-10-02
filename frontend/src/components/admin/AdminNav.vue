<script setup lang="ts">
import { useRoute } from 'vue-router'

const route = useRoute()

const items = [
  { label: 'Overview', icon: 'i-lucide-layout-dashboard', to: '/admin' },
  { label: 'Users', icon: 'i-lucide-users', to: '/admin/users' },
  { label: 'Departments', icon: 'i-lucide-building-2', to: '/admin/departments' },
]
</script>

<template>
  <div class="flex items-center gap-1 rounded-lg bg-(--ui-bg-elevated) p-1 w-fit">
    <ULink
      v-for="item in items"
      :key="item.to"
      :to="item.to"
      :class="[
        'flex items-center gap-2 px-3 py-1.5 text-sm font-medium rounded-md transition-colors',
        route.path === item.to
          ? 'bg-(--ui-bg-default) text-(--ui-text-highlighted) shadow-sm'
          : 'text-(--ui-text-muted) hover:text-(--ui-text)',
      ]"
    >
      <UIcon :name="item.icon" class="size-4" />
      {{ item.label }}
    </ULink>
  </div>
</template>
