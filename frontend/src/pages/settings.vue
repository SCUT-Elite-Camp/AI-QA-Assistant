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

interface LLMConfig {
  llm_api_base: string
  llm_model: string
  llm_api_key: string
  llm_api_key_masked: string
  has_api_key: boolean
  llm_http_proxy: string
  llm_temperature: number
  llm_max_tokens: number
  llm_timeout: number
}

interface TestResult {
  tested: boolean
  success: boolean
  latency_ms: number
  reply?: string
  model?: string
  error?: string
}

const toast = useToast()
const { csrf, headerName } = useCsrf()
const { loggedIn, fetchSession } = useUserSession()
const colorMode = useColorMode()
const appConfig = useAppConfig()

const saving = ref(false)
const savingLLM = ref(false)
const testingLLM = ref(false)
const loading = ref(true)
const devLoggingIn = ref(false)
const showApiKey = ref(false)
const showAdvancedLLM = ref(false)

const testResult = ref<TestResult>({
  tested: false,
  success: false,
  latency_ms: 0,
})

const llmConfig = ref<LLMConfig>({
  llm_api_base: '',
  llm_model: 'gemini-3.5-flash',
  llm_api_key: '',
  llm_api_key_masked: '',
  has_api_key: false,
  llm_http_proxy: '',
  llm_temperature: 0.1,
  llm_max_tokens: 2000,
  llm_timeout: 60,
})

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

const presets = [
  {
    name: 'Google Gemini',
    icon: 'i-lucide-sparkles',
    base: 'https://generativelanguage.googleapis.com/v1beta/openai/',
    model: 'gemini-3.5-flash',
    proxy: 'http://127.0.0.1:7897',
  },
  {
    name: 'OpenAI',
    icon: 'i-lucide-bot',
    base: 'https://api.openai.com/v1',
    model: 'gpt-4o-mini',
    proxy: 'http://127.0.0.1:7897',
  },
  {
    name: 'DeepSeek',
    icon: 'i-lucide-cpu',
    base: 'https://api.deepseek.com/v1',
    model: 'deepseek-chat',
    proxy: '',
  },
  {
    name: '本地 Ollama',
    icon: 'i-lucide-terminal',
    base: 'http://localhost:11434/v1',
    model: 'qwen2.5:7b',
    proxy: '',
  },
]

function applyPreset(p: typeof presets[0]) {
  llmConfig.value.llm_api_base = p.base
  llmConfig.value.llm_model = p.model
  if (p.proxy) {
    llmConfig.value.llm_http_proxy = p.proxy
  }
  toast.add({
    title: `已应用 ${p.name} 预设模板`,
    description: '请填入对应的 API Key 后点击测试或保存。',
    color: 'info',
    icon: 'i-lucide-info',
  })
}

onMounted(async () => {
  await Promise.all([loadSettings(), loadLLMConfig(), fetchSession()])
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
    await Promise.all([loadSettings(), loadLLMConfig()])
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

async function loadLLMConfig() {
  try {
    const data = await $fetch<LLMConfig>('/api/settings/llm')
    if (data && !('error' in data && data.error && !data.llm_api_base)) {
      llmConfig.value = {
        ...llmConfig.value,
        ...data,
        llm_api_key: '', // 不把明文 key 填充回 input
      }
    }
  } catch {
    // 忽略加载异常
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
    toast.add({ title: '常规设置已保存', color: 'success', icon: 'i-lucide-check' })
  } catch (err: any) {
    const status = err?.response?.status
    const message = status === 401 ? '未登录，无法保存设置' : status === 403 ? 'CSRF 校验失败，请刷新页面后重试' : '保存失败，请稍后重试'
    toast.add({ title: message, color: 'error', icon: 'i-lucide-x' })
  } finally {
    saving.value = false
  }
}

async function testLLMConnection() {
  if (!llmConfig.value.llm_api_base) {
    toast.add({ title: '请先填写 API 接口地址', color: 'error', icon: 'i-lucide-alert-circle' })
    return
  }
  if (!llmConfig.value.llm_model) {
    toast.add({ title: '请先填写模型名称', color: 'error', icon: 'i-lucide-alert-circle' })
    return
  }

  testingLLM.value = true
  testResult.value = {
    tested: false,
    success: false,
    latency_ms: 0,
  }

  try {
    const res: any = await $fetch('/api/settings/llm/test', {
      method: 'POST',
      headers: { [headerName]: csrf() },
      body: {
        llm_api_base: llmConfig.value.llm_api_base,
        llm_api_key: llmConfig.value.llm_api_key || undefined,
        llm_model: llmConfig.value.llm_model,
        llm_http_proxy: llmConfig.value.llm_http_proxy || undefined,
        llm_temperature: llmConfig.value.llm_temperature,
        llm_timeout: llmConfig.value.llm_timeout,
      },
    })

    testResult.value = {
      tested: true,
      success: res.success,
      latency_ms: res.latency_ms || 0,
      reply: res.reply,
      model: res.model || llmConfig.value.llm_model,
      error: res.error,
    }

    if (res.success) {
      toast.add({
        title: '连通性测试成功',
        description: `模型 ${res.model} 响应正常 (耗时 ${res.latency_ms}ms)`,
        color: 'success',
        icon: 'i-lucide-check-circle',
      })
    } else {
      toast.add({
        title: '连通性测试失败',
        description: res.error || '无法与模型建立连接',
        color: 'error',
        icon: 'i-lucide-x-circle',
      })
    }
  } catch (err: any) {
    const errMsg = err?.data?.statusMessage || err?.message || '测试请求失败'
    testResult.value = {
      tested: true,
      success: false,
      latency_ms: 0,
      error: errMsg,
    }
    toast.add({
      title: '连通性测试失败',
      description: errMsg,
      color: 'error',
      icon: 'i-lucide-x-circle',
    })
  } finally {
    testingLLM.value = false
  }
}

async function saveLLMConfig() {
  if (!loggedIn.value) {
    toast.add({ title: '请先登录', description: '登录后才能保存 API 配置', color: 'error', icon: 'i-lucide-x' })
    return
  }
  if (!llmConfig.value.llm_api_base) {
    toast.add({ title: '请先填写 API 接口地址', color: 'error', icon: 'i-lucide-alert-circle' })
    return
  }

  savingLLM.value = true
  try {
    const res: any = await $fetch('/api/settings/llm/save', {
      method: 'POST',
      headers: { [headerName]: csrf() },
      body: {
        llm_api_base: llmConfig.value.llm_api_base,
        llm_api_key: llmConfig.value.llm_api_key || undefined,
        llm_model: llmConfig.value.llm_model,
        llm_http_proxy: llmConfig.value.llm_http_proxy,
        llm_temperature: Number(llmConfig.value.llm_temperature),
        llm_max_tokens: Number(llmConfig.value.llm_max_tokens),
        llm_timeout: Number(llmConfig.value.llm_timeout),
      },
    })

    toast.add({
      title: 'API 配置保存成功',
      description: res?.message || '配置已写入 .env 并在当前服务即时生效。',
      color: 'success',
      icon: 'i-lucide-check',
    })

    // 重新拉取以更新掩码
    await loadLLMConfig()
  } catch (err: any) {
    const errMsg = err?.data?.statusMessage || err?.message || '保存 API 配置失败'
    toast.add({
      title: '保存失败',
      description: errMsg,
      color: 'error',
      icon: 'i-lucide-x',
    })
  } finally {
    savingLLM.value = false
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
      <UContainer class="flex-1 py-8 max-w-3xl">
        <div v-if="loading" class="flex justify-center py-16">
          <UIcon name="i-lucide-loader" class="animate-spin size-6" />
        </div>

        <div v-else class="space-y-8">
          <div>
            <h1 class="text-2xl font-bold text-highlighted">系统设置</h1>
            <p class="text-dimmed mt-1">自定义您的模型 API 配置与应用偏好，配置已启用安全隔离。</p>
          </div>

          <!-- 大模型与 API 配置 -->
          <UCard>
            <template #header>
              <div class="flex items-center justify-between">
                <div class="flex items-center gap-2">
                  <UIcon name="i-lucide-cpu" class="size-5 text-primary" />
                  <span class="font-semibold text-base">大模型与 API 配置 (LLM Settings)</span>
                </div>
                <UBadge
                  :color="llmConfig.has_api_key ? 'success' : 'warning'"
                  variant="subtle"
                  size="sm"
                >
                  {{ llmConfig.has_api_key ? '已配置 API Key' : '未检测到 API Key' }}
                </UBadge>
              </div>
            </template>

            <div class="space-y-6">
              <!-- 快捷模板预设 -->
              <div>
                <div class="text-xs font-medium text-dimmed mb-2">常用提供商预设（点击快速填入）：</div>
                <div class="flex flex-wrap gap-2">
                  <UButton
                    v-for="p in presets"
                    :key="p.name"
                    :icon="p.icon"
                    :label="p.name"
                    variant="outline"
                    color="neutral"
                    size="xs"
                    @click="applyPreset(p)"
                  />
                </div>
              </div>

              <!-- API Base URL -->
              <UFormField label="API 接口地址 (Base URL)" description="支持 OpenAI 兼容格式接口，以 /v1 或 /openai/ 结尾">
                <UInput
                  v-model="llmConfig.llm_api_base"
                  placeholder="例如: https://generativelanguage.googleapis.com/v1beta/openai/"
                  class="w-full mt-1 font-mono text-sm"
                />
              </UFormField>

              <!-- API Key -->
              <UFormField label="API 密钥 (API Key)" description="密钥将保存在本地 .env 中，受 .gitignore 保护">
                <div class="relative mt-1">
                  <UInput
                    v-model="llmConfig.llm_api_key"
                    :type="showApiKey ? 'text' : 'password'"
                    :placeholder="llmConfig.has_api_key ? `已配置: ${llmConfig.llm_api_key_masked} (留空保持不变)` : '请输入 API 密钥...'"
                    class="w-full font-mono text-sm pr-10"
                  />
                  <button
                    type="button"
                    class="absolute inset-y-0 right-0 px-3 flex items-center text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-200 cursor-pointer"
                    @click="showApiKey = !showApiKey"
                  >
                    <UIcon :name="showApiKey ? 'i-lucide-eye-off' : 'i-lucide-eye'" class="size-4" />
                  </button>
                </div>
              </UFormField>

              <!-- 模型名称 -->
              <UFormField label="模型名称 (Model)" description="需要调用的目标大模型型号">
                <UInput
                  v-model="llmConfig.llm_model"
                  placeholder="例如: gemini-3.5-flash, gemini-3-flash-preview, gpt-4o-mini"
                  class="w-full mt-1 font-mono text-sm"
                />
              </UFormField>

              <!-- HTTP 代理 -->
              <UFormField label="HTTP 网络代理 (Proxy)" description="国内环境调用 Google / OpenAI 建议配置本地代理">
                <UInput
                  v-model="llmConfig.llm_http_proxy"
                  placeholder="选填，例如: http://127.0.0.1:7897"
                  class="w-full mt-1 font-mono text-sm"
                />
              </UFormField>

              <!-- 高级参数折叠 -->
              <div class="pt-2 border-t border-zinc-100 dark:border-zinc-800">
                <button
                  type="button"
                  class="flex items-center gap-1.5 text-xs font-medium text-dimmed hover:text-highlighted transition-colors cursor-pointer"
                  @click="showAdvancedLLM = !showAdvancedLLM"
                >
                  <UIcon :name="showAdvancedLLM ? 'i-lucide-chevron-down' : 'i-lucide-chevron-right'" class="size-4" />
                  <span>高级模型参数（温度、最大Token、超时时间）</span>
                </button>

                <div v-if="showAdvancedLLM" class="grid grid-cols-1 sm:grid-cols-3 gap-4 mt-4">
                  <UFormField label="模型温度 (Temperature)">
                    <UInput
                      v-model.number="llmConfig.llm_temperature"
                      type="number"
                      step="0.05"
                      min="0"
                      max="2"
                      class="w-full mt-1"
                    />
                  </UFormField>
                  <UFormField label="最大 Token 数">
                    <UInput
                      v-model.number="llmConfig.llm_max_tokens"
                      type="number"
                      step="100"
                      min="100"
                      max="32000"
                      class="w-full mt-1"
                    />
                  </UFormField>
                  <UFormField label="超时时间 (秒)">
                    <UInput
                      v-model.number="llmConfig.llm_timeout"
                      type="number"
                      step="5"
                      min="5"
                      max="300"
                      class="w-full mt-1"
                    />
                  </UFormField>
                </div>
              </div>

              <!-- 连通性测试结果面板 -->
              <div v-if="testResult.tested" class="mt-4">
                <div
                  class="p-3.5 rounded-lg border text-sm transition-all"
                  :class="testResult.success
                    ? 'bg-emerald-50/50 dark:bg-emerald-950/20 border-emerald-300 dark:border-emerald-800/50 text-emerald-900 dark:text-emerald-200'
                    : 'bg-rose-50/50 dark:bg-rose-950/20 border-rose-300 dark:border-rose-800/50 text-rose-900 dark:text-rose-200'"
                >
                  <div class="flex items-center gap-2 font-medium">
                    <UIcon
                      :name="testResult.success ? 'i-lucide-check-circle-2' : 'i-lucide-alert-triangle'"
                      class="size-5"
                    />
                    <span>{{ testResult.success ? '连通性测试通过' : '连通性测试未通过' }}</span>
                    <span v-if="testResult.latency_ms" class="text-xs opacity-75 font-mono">
                      ({{ testResult.latency_ms }} ms)
                    </span>
                  </div>
                  <div v-if="testResult.reply" class="mt-2 text-xs opacity-90 pl-7">
                    <span class="font-semibold">模型回复：</span>{{ testResult.reply }}
                  </div>
                  <div v-if="testResult.error" class="mt-2 text-xs opacity-90 pl-7 break-all font-mono">
                    <span class="font-semibold">错误信息：</span>{{ testResult.error }}
                  </div>
                </div>
              </div>

              <!-- 防误提交与操作按钮 -->
              <div class="pt-2 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
                <div class="flex items-center gap-1.5 text-xs text-dimmed">
                  <UIcon name="i-lucide-shield-check" class="size-4 text-emerald-500 shrink-0" />
                  <span>配置持久化于本地 <code class="font-mono bg-zinc-100 dark:bg-zinc-800 px-1 py-0.5 rounded">.env</code>，受 <code class="font-mono bg-zinc-100 dark:bg-zinc-800 px-1 py-0.5 rounded">.gitignore</code> 保护防止误提交 GitHub。</span>
                </div>

                <div class="flex items-center gap-2 w-full sm:w-auto justify-end">
                  <UButton
                    label="测试连通性"
                    icon="i-lucide-zap"
                    variant="outline"
                    color="neutral"
                    :loading="testingLLM"
                    @click="testLLMConnection"
                  />
                  <UButton
                    label="保存 API 配置"
                    icon="i-lucide-save"
                    color="primary"
                    :loading="savingLLM"
                    :disabled="!loggedIn"
                    @click="saveLLMConfig"
                  />
                </div>
              </div>
            </div>
          </UCard>

          <!-- 外观 -->
          <UCard>
            <template #header>
              <div class="flex items-center gap-2">
                <UIcon name="i-lucide-palette" class="size-5" />
                <span class="font-semibold">外观与界面偏好</span>
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

          <!-- 语言与通知 -->
          <UCard>
            <template #header>
              <div class="flex items-center gap-2">
                <UIcon name="i-lucide-sliders" class="size-5" />
                <span class="font-semibold">语言与通知偏好</span>
              </div>
            </template>

            <div class="space-y-6">
              <UFormField label="界面语言">
                <USelect
                  v-model="settings.language"
                  :items="languageOptions"
                  class="w-48 mt-2"
                />
              </UFormField>

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
            description="当前为预览模式，登录后才能保存设置与 API 配置。"
            :actions="[{ label: '开发登录', size: 'xs', color: 'warning', variant: 'outline', icon: 'i-lucide-log-in', loading: devLoggingIn, onClick: devLogin }]"
          />

          <!-- 常规设置保存按钮 -->
          <div class="flex justify-end pt-2">
            <UButton
              label="保存常规偏好"
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
