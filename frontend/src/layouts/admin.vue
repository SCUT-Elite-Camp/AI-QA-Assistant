<script setup lang="ts">
import { useRoute } from 'vue-router'
import { useUserSession } from '../composables/useUserSession'

const route = useRoute()
const { user } = useUserSession()

const navItems = [
  { label: '系统概览', icon: 'i-lucide-layout-dashboard', to: '/admin' },
  { label: '用户管理', icon: 'i-lucide-users', to: '/admin/users' },
  { label: '部门管理', icon: 'i-lucide-building-2', to: '/admin/departments' },
  { label: '文件权限', icon: 'i-lucide-folder-lock', to: '/files' },
]
</script>

<template>
  <div class="min-h-screen bg-zinc-50 dark:bg-zinc-950 text-zinc-900 dark:text-zinc-100 flex flex-col">
    <!-- Admin Header Navbar -->
    <header class="sticky top-0 z-40 border-b border-zinc-200 dark:border-zinc-800 bg-white/80 dark:bg-zinc-900/80 backdrop-blur">
      <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between gap-4">
        <!-- Brand & Nav -->
        <div class="flex items-center gap-6 min-w-0">
          <ULink to="/admin" class="flex items-center gap-2.5 shrink-0 group">
            <div class="w-9 h-9 rounded-xl bg-gradient-to-br from-indigo-500 to-primary-600 flex items-center justify-center text-white shadow-md shadow-primary-500/20 group-hover:scale-105 transition-transform">
              <UIcon name="i-lucide-shield-check" class="w-5 h-5" />
            </div>
            <div class="flex flex-col">
              <span class="font-bold text-base tracking-tight leading-none group-hover:text-primary-500 transition-colors">
                AI-QA 控制台
              </span>
              <span class="text-[11px] text-zinc-400 dark:text-zinc-500 font-mono mt-0.5">
                Admin Management
              </span>
            </div>
          </ULink>

          <nav class="hidden md:flex items-center gap-1 ml-4 pl-4 border-l border-zinc-200 dark:border-zinc-800">
            <ULink
              v-for="item in navItems"
              :key="item.to"
              :to="item.to"
              :class="[
                'flex items-center gap-2 px-3 py-1.5 text-sm font-medium rounded-lg transition-colors',
                route.path === item.to
                  ? 'bg-zinc-100 dark:bg-zinc-800 text-primary-600 dark:text-primary-400 font-semibold shadow-xs'
                  : 'text-zinc-600 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-200 hover:bg-zinc-100/60 dark:hover:bg-zinc-800/50'
              ]"
            >
              <UIcon :name="item.icon" class="w-4 h-4" />
              <span>{{ item.label }}</span>
            </ULink>
          </nav>
        </div>

        <!-- Right actions -->
        <div class="flex items-center gap-3 shrink-0">
          <UBadge
            color="primary"
            variant="subtle"
            size="md"
            class="hidden sm:inline-flex items-center gap-1.5 py-1 px-2.5 font-normal"
          >
            <span class="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
            {{ user?.name || '系统管理员' }} (免登录开发模式)
          </UBadge>

          <UColorModeButton />

          <UButton
            to="/"
            icon="i-lucide-arrow-left"
            color="neutral"
            variant="outline"
            size="sm"
            class="rounded-lg shadow-2xs font-medium"
          >
            返回问答
          </UButton>
        </div>
      </div>

      <!-- Mobile subnav -->
      <div class="md:hidden flex items-center gap-1 px-4 py-2 border-t border-zinc-200 dark:border-zinc-800 overflow-x-auto">
        <ULink
          v-for="item in navItems"
          :key="item.to"
          :to="item.to"
          :class="[
            'flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium rounded-md whitespace-nowrap transition-colors shrink-0',
            route.path === item.to
              ? 'bg-zinc-100 dark:bg-zinc-800 text-primary-600 dark:text-primary-400'
              : 'text-zinc-600 dark:text-zinc-400'
          ]"
        >
          <UIcon :name="item.icon" class="w-3.5 h-3.5" />
          <span>{{ item.label }}</span>
        </ULink>
      </div>
    </header>

    <!-- Main Container -->
    <main class="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-8">
      <slot>
        <RouterView :key="route.path" />
      </slot>
    </main>
  </div>
</template>
