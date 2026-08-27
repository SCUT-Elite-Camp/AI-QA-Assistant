<script setup lang="ts">
import { computed } from 'vue'
import { useColorMode } from '@vueuse/core'
import { useRouter } from 'vue-router'
import type { DropdownMenuItem } from '@nuxt/ui'
import { useUserSession } from '../composables/useUserSession'
import { useCsrf } from '../composables/useCsrf'

defineProps<{
  collapsed?: boolean
}>()

const router = useRouter()
const colorMode = useColorMode()
const appConfig = useAppConfig()
const { user, clearSession, fetchSession } = useUserSession()
const { csrf, headerName } = useCsrf()

/**
 * 开发环境身份切换器。
 * 复用后端已有的 POST /api/auth/dev-login，以指定身份登录（自动建号）。
 * 仅用于开发/演示（服务端要求 NODE_ENV=development 或 ALLOW_DEV_LOGIN=true）。
 */
const DEV_ACCOUNTS = [
  { userId: 'admin', username: 'admin', name: '管理员 (admin)', role: 'admin' as const },
  { userId: 'group-a', username: 'group-a', name: '项目组A用户', role: 'user' as const },
  { userId: 'group-b', username: 'group-b', name: '项目组B用户', role: 'user' as const },
]

async function switchIdentity (account: { userId: string, username: string, name: string, role: 'admin' | 'user' }) {
  await $fetch('/api/auth/dev-login', {
    method: 'POST',
    headers: { [headerName]: csrf() },
    body: {
      userId: account.userId,
      username: account.username,
      name: account.name,
      role: account.role,
    },
  })
  await fetchSession()
}

const colors = ['red', 'orange', 'amber', 'yellow', 'lime', 'green', 'emerald', 'teal', 'cyan', 'sky', 'blue', 'indigo', 'violet', 'purple', 'fuchsia', 'pink', 'rose']
const neutrals = ['slate', 'gray', 'zinc', 'neutral', 'stone']

const items = computed<DropdownMenuItem[][]>(() => ([[{
  type: 'label',
  label: user.value?.name,
  avatar: {
    src: user.value?.avatar,
    alt: user.value?.name
  }
}], [{
  label: 'Theme',
  icon: 'i-lucide-palette',
  children: [{
    label: 'Primary',
    slot: 'chip',
    chip: appConfig.ui.colors.primary,
    content: {
      align: 'center',
      collisionPadding: 16
    },
    children: colors.map(color => ({
      label: color,
      chip: color,
      slot: 'chip',
      checked: appConfig.ui.colors.primary === color,
      type: 'checkbox',
      onSelect: (e) => {
        e.preventDefault()

        appConfig.ui.colors.primary = color
      }
    }))
  }, {
    label: 'Neutral',
    slot: 'chip',
    chip: appConfig.ui.colors.neutral === 'neutral' ? 'old-neutral' : appConfig.ui.colors.neutral,
    content: {
      align: 'end',
      collisionPadding: 16
    },
    children: neutrals.map(color => ({
      label: color,
      chip: color === 'neutral' ? 'old-neutral' : color,
      slot: 'chip',
      type: 'checkbox',
      checked: appConfig.ui.colors.neutral === color,
      onSelect: (e) => {
        e.preventDefault()

        appConfig.ui.colors.neutral = color
      }
    }))
  }]
}, {
  label: 'Appearance',
  icon: 'i-lucide-sun-moon',
  children: [{
    label: 'Light',
    icon: 'i-lucide-sun',
    type: 'checkbox',
    checked: colorMode.value === 'light',
    onSelect(e: Event) {
      e.preventDefault()

      colorMode.value = 'light'
    }
  }, {
    label: 'Dark',
    icon: 'i-lucide-moon',
    type: 'checkbox',
    checked: colorMode.value === 'dark',
    onUpdateChecked(checked: boolean) {
      if (checked) {
        colorMode.value = 'dark'
      }
    },
    onSelect(e: Event) {
      e.preventDefault()
    }
  }]
}], [{
  label: 'Templates',
  icon: 'i-lucide-layout-template',
  children: [{
    label: 'Starter',
    to: 'https://starter-vue-template.nuxt.dev/'
  }, {
    label: 'Dashboard',
    to: 'https://dashboard-vue-template.nuxt.dev/'
  }, {
    label: 'Chat',
    to: 'https://chat-vue-template.nuxt.dev/',
    color: 'primary',
    checked: true,
    type: 'checkbox'
  }]
}], [{
  label: 'Settings',
  icon: 'i-lucide-settings',
  to: '/settings'
}, {
  label: 'Files',
  icon: 'i-lucide-folder',
  to: '/files'
}, ...(user.value?.role === 'admin' ? [{
  label: 'Admin',
  icon: 'i-lucide-shield',
  to: '/admin'
}] : [])], [{
  label: 'Docs',
  icon: 'i-lucide-book-open',
  to: 'https://ui.nuxt.com/docs/getting-started/installation/vue',
  target: '_blank'
}, {
  label: 'GitHub Repo',
  icon: 'i-simple-icons:github',
  to: 'https://github.com/nuxt-ui-templates/chat-vue',
  target: '_blank'
}], [{
  type: 'label',
  label: '开发者 · 切换身份'
}, ...DEV_ACCOUNTS.map(account => ({
  label: account.name,
  icon: 'i-lucide-user-switch',
  type: 'checkbox' as const,
  checked: user.value?.id === account.userId,
  onSelect: (e: Event) => {
    e.preventDefault()
    switchIdentity(account)
  }
}))], [{
  label: 'Log out',
  icon: 'i-lucide-log-out',
  onSelect() {
    clearSession()
    router.push('/')
  }
}]]))
</script>

<template>
  <UDropdownMenu
    :items="items"
    :content="{ align: 'center', collisionPadding: 12 }"
    :ui="{ content: collapsed ? 'w-48' : 'w-(--reka-dropdown-menu-trigger-width)' }"
  >
    <UButton
      v-bind="{
        label: collapsed ? undefined : (user?.name || user?.username),
        trailingIcon: collapsed ? undefined : 'i-lucide-chevrons-up-down'
      }"
      :avatar="{
        src: user?.avatar || undefined,
        alt: user?.name || user?.username
      }"
      color="neutral"
      variant="ghost"
      block
      :square="collapsed"
      class="data-[state=open]:bg-elevated"
      :ui="{
        trailingIcon: 'text-dimmed'
      }"
    />

    <template #chip-leading="{ item }">
      <div class="inline-flex items-center justify-center shrink-0 size-5">
        <span
          class="rounded-full ring ring-bg bg-(--chip-light) dark:bg-(--chip-dark) size-2"
          :style="{
            '--chip-light': `var(--color-${(item as any).chip}-500)`,
            '--chip-dark': `var(--color-${(item as any).chip}-400)`
          }"
        />
      </div>
    </template>
  </UDropdownMenu>
</template>
