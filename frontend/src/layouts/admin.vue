<script setup lang="ts">
import { useRoute } from 'vue-router'
import { useUserSession } from '../composables/useUserSession'

const route = useRoute()
const { user } = useUserSession()

const navItems = [
  { label: 'Overview', icon: 'i-lucide-layout-dashboard', to: '/admin' },
  { label: 'Users', icon: 'i-lucide-users', to: '/admin/users' },
  { label: 'Departments', icon: 'i-lucide-building-2', to: '/admin/departments' },
  { label: 'File Permissions', icon: 'i-lucide-folder-lock', to: '/files' },
]
</script>

<template>
  <div class="min-h-screen bg-zinc-50/90 dark:bg-zinc-950 text-zinc-900 dark:text-zinc-100 flex flex-col relative selection:bg-primary-500/20 selection:text-primary-700 dark:selection:text-primary-300">
    <!-- Ambient Atmospheric Glows -->
    <div class="pointer-events-none fixed -top-32 left-1/4 w-[500px] h-[350px] bg-gradient-to-br from-primary-500/8 via-indigo-500/5 to-transparent rounded-full blur-3xl" />
    <div class="pointer-events-none fixed top-1/2 -right-32 w-[450px] h-[350px] bg-gradient-to-bl from-purple-500/6 via-blue-500/4 to-transparent rounded-full blur-3xl" />

    <!-- Frosted Acrylic Header -->
    <header class="sticky top-0 z-40 border-b border-zinc-200/80 dark:border-zinc-800/70 bg-white/70 dark:bg-zinc-900/70 backdrop-blur-2xl shadow-xs transition-all">
      <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between gap-4">
        <!-- Brand & Nav -->
        <div class="flex items-center gap-6 min-w-0">
          <ULink to="/admin" class="flex items-center gap-3 shrink-0 group">
            <div class="w-9 h-9 rounded-xl bg-zinc-900 dark:bg-zinc-100 text-white dark:text-zinc-900 flex items-center justify-center shadow-md shadow-zinc-950/10 group-hover:scale-105 transition-all duration-200">
              <UIcon name="i-lucide-shield-check" class="w-5 h-5" />
            </div>
            <div class="flex flex-col">
              <div class="flex items-center gap-2">
                <span class="font-bold text-sm sm:text-base tracking-tight leading-none text-zinc-900 dark:text-white group-hover:text-primary-600 dark:group-hover:text-primary-400 transition-colors">
                  AI-QA Admin
                </span>
                <span class="hidden sm:inline-flex px-1.5 py-0.5 rounded text-[10px] font-semibold bg-primary-500/10 text-primary-600 dark:text-primary-400 border border-primary-500/20">
                  PRO
                </span>
              </div>
              <span class="text-[11px] text-zinc-400 dark:text-zinc-500 font-medium tracking-wide mt-0.5">
                Admin Console
              </span>
            </div>
          </ULink>

          <!-- Segmented Acrylic Nav Tabs -->
          <nav class="hidden md:flex items-center gap-1 p-1 bg-zinc-200/50 dark:bg-zinc-800/50 rounded-xl border border-zinc-300/40 dark:border-zinc-700/40 backdrop-blur-md">
            <ULink
              v-for="item in navItems"
              :key="item.to"
              :to="item.to"
              :class="[
                'flex items-center gap-2 px-3.5 py-1.5 text-xs sm:text-sm font-medium rounded-lg transition-all duration-200 select-none',
                route.path === item.to
                  ? 'bg-white dark:bg-zinc-900 text-zinc-950 dark:text-white shadow-xs font-semibold'
                  : 'text-zinc-600 dark:text-zinc-400 hover:text-zinc-950 dark:hover:text-white hover:bg-white/40 dark:hover:bg-zinc-800/40'
              ]"
            >
              <UIcon :name="item.icon" class="w-4 h-4 shrink-0" />
              <span>{{ item.label }}</span>
            </ULink>
          </nav>
        </div>

        <!-- Right actions -->
        <div class="flex items-center gap-3 shrink-0">
          <div class="hidden sm:flex items-center gap-2 px-3 py-1.5 rounded-full bg-zinc-100/80 dark:bg-zinc-800/80 border border-zinc-200/60 dark:border-zinc-700/60 text-xs font-medium text-zinc-700 dark:text-zinc-300 backdrop-blur-md">
            <span class="w-2 h-2 rounded-full bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.8)]" />
            <span>{{ user?.name || 'Administrator' }}</span>
          </div>

          <UColorModeButton />

          <UButton
            to="/"
            icon="i-lucide-arrow-left"
            color="neutral"
            variant="ghost"
            size="sm"
            class="rounded-xl font-medium border border-zinc-200 dark:border-zinc-800 hover:bg-zinc-100 dark:hover:bg-zinc-800/80 shadow-2xs"
          >
            Back to Chat
          </UButton>
        </div>
      </div>

      <!-- Mobile subnav -->
      <div class="md:hidden flex items-center gap-1.5 px-4 py-2 border-t border-zinc-200/60 dark:border-zinc-800/60 bg-white/40 dark:bg-zinc-900/40 backdrop-blur-xl overflow-x-auto">
        <ULink
          v-for="item in navItems"
          :key="item.to"
          :to="item.to"
          :class="[
            'flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg whitespace-nowrap transition-all shrink-0',
            route.path === item.to
              ? 'bg-white dark:bg-zinc-800 text-zinc-950 dark:text-white shadow-2xs font-semibold'
              : 'text-zinc-600 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-white'
          ]"
        >
          <UIcon :name="item.icon" class="w-3.5 h-3.5" />
          <span>{{ item.label }}</span>
        </ULink>
      </div>
    </header>

    <!-- Main Container -->
    <main class="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-8 relative z-10">
      <slot>
        <RouterView :key="route.path" />
      </slot>
    </main>
  </div>
</template>
