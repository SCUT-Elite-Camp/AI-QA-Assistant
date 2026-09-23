<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { $fetch } from 'ofetch'
import { useColorMode } from '@vueuse/core'
import { useCsrf } from '../composables/useCsrf'
import { useUserSession } from '../composables/useUserSession'
import Navbar from '../components/Navbar.vue'

interface Settings {
  theme: 'light' | 'dark' | 'system'
  primaryColor: string
  neutralColor: string
  language: 'zh-CN' | 'en-US'
  notificationsEnabled: boolean
  autoSaveChats: boolean
  fontSize: 'small' | 'medium' | 'large'
}

const toast = useToast()
const { csrf, headerName } = useCsrf()
const { loggedIn, fetchSession } = useUserSession()
const colorMode = useColorMode()
const appConfig = useAppConfig()

const saving = ref(false)
const loading = ref(true)
const devLoggingIn = ref(false)

onMounted(() => {
  loadSettings()
  fetchSession()
})

async function devLogin() {
  devLoggingIn.value = true
  try {
    await $fetch('/api/auth/dev-login', {
      method: 'POST',
      headers: { [headerName]: csrf() },
      body: {},
    })
    await fetchSession()
    await loadSettings()
    toast.add({ title: '开发登录成功', color: 'success', icon: 'i-lucide-check' })
  } catch (err: any) {
    const msg = err?.response?.status === 403
      ? '开发登录未启用，请在 .env 中设置 ALLOW_DEV_LOGIN=true'
      : '开发登录失败'
    toast.add({ title: msg, color: 'error', icon: 'i-lucide-x' })
  } finally {
    devLoggingIn.value = false
  }
}

const settings = ref<Settings>({
  theme: 'system',
  primaryColor: 'blue',
  neutralColor: 'zinc',
  language: 'zh-CN',
  notificationsEnabled: true,
  autoSaveChats: true,
  fontSize: 'medium',
})

const colors = ['red', 'orange', 'amber', 'yellow', 'lime', 'green', 'emerald', 'teal', 'cyan', 'sky', 'blue', 'indigo', 'violet', 'purple', 'fuchsia', 'pink', 'rose']
const neutrals = ['slate', 'gray', 'zinc', 'neutral', 'stone']

const themeOptions = [
  { label: '跟随系统', value: 'system', icon: 'i-lucide-monitor' },
  { label: '浅色', value: 'light', icon: 'i-lucide-sun' },
  { label: '深色', value: 'dark', icon: 'i-lucide-moon' },
]

const languageOptions = [
  { label: '简体中文', value: 'zh-CN' },
  { label: 'English', value: 'en-US' },
]

const fontSizeOptions = [
  { label: '小', value: 'small' },
  { label: '中', value: 'medium' },
  { label: '大', value: 'large' },
]

async function loadSettings() {
  try {
    const data = await $fetch<Settings>('/api/settings')
    settings.value = { ...settings.value, ...data }
  } catch {
    // 使用默认值
  } finally {
    loading.value = false
  }
}

function applyTheme() {
  const s = settings.value
  if (s.theme !== 'system') {
    colorMode.value = settings.value.theme
  }
  appConfig.ui.colors.primary = s.primaryColor
  appConfig.ui.colors.neutral = s.neutralColor
}

async function saveSettings() {
  if (!loggedIn.value) {
    toast.add({ title: '请先登录', description: '登录后才能保存设置', color: 'error', icon: 'i-lucide-x' })
    return
  }

  saving.value = true
  try {
    await $fetch('/api/settings', {
      method: 'POST',
      headers: { [headerName]: csrf() },
      body: JSON.parse(JSON.stringify(settings.value)),
    })
    applyTheme()
    toast.add({ title: '设置已保存', color: 'success', icon: 'i-lucide-check' })
  } catch (err: any) {
    const status = err?.response?.status
    const message = status === 401 ? '未登录，无法保存设置' : status === 403 ? 'CSRF 校验失败，请刷新页面后重试' : '保存失败，请稍后重试'
    toast.add({ title: message, color: 'error', icon: 'i-lucide-x' })
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <UDashboardPanel
    id="settings"
    class="min-h-0"
    :ui="{ body: 'p-0 sm:p-0' }"
  >
    <template #header>
      <Navbar />
    </template>

    <template #body>
      <UContainer class="flex-1 py-8 max-w-2xl">
        <div v-if="loading" class="flex justify-center py-16">
          <UIcon name="i-lucide-loader" class="animate-spin size-6" />
        </div>

        <div v-else class="space-y-8">
          <div>
            <h1 class="text-2xl font-bold text-highlighted">设置</h1>
            <p class="text-dimmed mt-1">自定义您的应用偏好，设置会自动保存到您的账户。</p>
          </div>

          <!-- 外观 -->
          <UCard>
            <template #header>
              <div class="flex items-center gap-2">
                <UIcon name="i-lucide-palette" class="size-5" />
                <span class="font-semibold">外观</span>
              </div>
            </template>

            <div class="space-y-6">
              <!-- 主题模式 -->
              <UFormField label="主题模式">
                <div class="flex gap-2 mt-2">
                  <UButton
                    v-for="opt in themeOptions"
                    :key="opt.value"
                    :label="opt.label"
                    :icon="opt.icon"
                    :variant="settings.theme === opt.value ? 'solid' : 'outline'"
                    :color="settings.theme === opt.value ? 'primary' : 'neutral'"
                    size="sm"
                    @click="settings.theme = opt.value as Settings['theme']"
                  />
                </div>
              </UFormField>

              <!-- 主色调 -->
              <UFormField label="主色调">
                <div class="flex flex-wrap gap-1.5 mt-2">
                  <button
                    v-for="c in colors"
                    :key="c"
                    class="size-7 rounded-full border-2 transition-all cursor-pointer"
                    :class="settings.primaryColor === c ? 'border-white ring-2 ring-offset-1 ring-offset-bg' : 'border-transparent'"
                    :style="{ backgroundColor: `var(--color-${c}-500)` }"
                    :aria-label="c"
                    @click="settings.primaryColor = c"
                  />
                </div>
              </UFormField>

              <!-- 中性色 -->
              <UFormField label="中性色">
                <div class="flex flex-wrap gap-1.5 mt-2">
                  <button
                    v-for="n in neutrals"
                    :key="n"
                    class="size-7 rounded-full border-2 transition-all cursor-pointer"
                    :class="settings.neutralColor === n ? 'border-white ring-2 ring-offset-1 ring-offset-bg' : 'border-transparent'"
                    :style="{ backgroundColor: n === 'neutral' ? '#737373' : `var(--color-${n}-500)` }"
                    :aria-label="n"
                    @click="settings.neutralColor = n"
                  />
                </div>
              </UFormField>

              <!-- 字号 -->
              <UFormField label="字号">
                <USelect
                  v-model="settings.fontSize"
                  :items="fontSizeOptions"
                  class="w-40 mt-2"
                />
              </UFormField>
            </div>
          </UCard>

          <!-- 语言 -->
          <UCard>
            <template #header>
              <div class="flex items-center gap-2">
                <UIcon name="i-lucide-globe" class="size-5" />
                <span class="font-semibold">语言与区域</span>
              </div>
            </template>

            <div class="space-y-4">
              <UFormField label="界面语言">
                <USelect
                  v-model="settings.language"
                  :items="languageOptions"
                  class="w-48 mt-2"
                />
              </UFormField>
            </div>
          </UCard>

          <!-- 通知 -->
          <UCard>
            <template #header>
              <div class="flex items-center gap-2">
                <UIcon name="i-lucide-bell" class="size-5" />
                <span class="font-semibold">通知</span>
              </div>
            </template>

            <div class="space-y-4">
              <div class="flex items-center justify-between py-1">
                <div>
                  <div class="font-medium">启用通知</div>
                  <div class="text-sm text-dimmed">接收 AI 回复完成和应用更新通知。</div>
                </div>
                <UToggle v-model="settings.notificationsEnabled" />
              </div>

              <div class="flex items-center justify-between py-1">
                <div>
                  <div class="font-medium">自动保存对话</div>
                  <div class="text-sm text-dimmed">自动保存所有聊天记录，离开页面不丢失。</div>
                </div>
                <UToggle v-model="settings.autoSaveChats" />
              </div>
            </div>
          </UCard>

          <UAlert
            v-if="!loading && !loggedIn && !devLoggingIn"
            color="warning"
            icon="i-lucide-alert-circle"
            title="未登录"
            description="当前为预览模式，登录后才能保存设置。"
            :actions="[{ label: '开发登录', size: 'xs', color: 'warning', variant: 'outline', icon: 'i-lucide-log-in', loading: devLoggingIn, onClick: devLogin }]"
          />

          <!-- 保存按钮 -->
          <div class="flex justify-end pt-2">
            <UButton
              label="保存设置"
              icon="i-lucide-save"
              :loading="saving"
              :disabled="!loggedIn"
              @click="saveSettings"
            />
          </div>
        </div>
      </UContainer>
    </template>
  </UDashboardPanel>
</template>
