<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { $fetch } from 'ofetch'
import { useColorMode } from '@vueuse/core'
import { useUserSession } from '../composables/useUserSession'

const props = defineProps<{
  open: boolean
}>()

const emit = defineEmits<{
  'update:open': [value: boolean]
}>()

const activeTab = ref<'general' | 'model' | 'personalization' | 'account'>('general')

const colorMode = useColorMode()
const appConfig = useAppConfig()
const { user, clearSession, loggedIn } = useUserSession()
const toast = useToast()

// LLM API Config State
const testingLLM = ref(false)
const savingLLM = ref(false)
const showApiKey = ref(false)

const testResult = ref<{
  tested: boolean
  success: boolean
  latency_ms: number
  reply?: string
  error?: string
}>({
  tested: false,
  success: false,
  latency_ms: 0,
})

const llmConfig = ref({
  llm_api_base: '',
  llm_model: 'gemini-3.5-flash',
  llm_api_key: '',
  llm_api_key_masked: '',
  has_api_key: false,
  llm_http_proxy: '',
})

const presets = [
  {
    name: 'Gemini',
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
    name: 'Claude',
    icon: 'i-lucide-brain',
    base: 'https://api.anthropic.com/v1',
    model: 'claude-3-5-sonnet-20241022',
    proxy: 'http://127.0.0.1:7897',
  },
  {
    name: 'DeepSeek',
    icon: 'i-lucide-cpu',
    base: 'https://api.deepseek.com/v1',
    model: 'deepseek-chat',
    proxy: '',
  },
]

function applyPreset(p: typeof presets[0]) {
  llmConfig.value.llm_api_base = p.base
  llmConfig.value.llm_model = p.model
  if (p.proxy) {
    llmConfig.value.llm_http_proxy = p.proxy
  }
}

async function loadLLMConfig() {
  try {
    const data = await $fetch<any>('/api/settings/llm')
    if (data && !('error' in data && data.error && !data.llm_api_base)) {
      llmConfig.value = {
        llm_api_base: data.llm_api_base || '',
        llm_model: data.llm_model || 'gemini-3.5-flash',
        llm_api_key: '',
        llm_api_key_masked: data.llm_api_key_masked || '',
        has_api_key: !!data.has_api_key,
        llm_http_proxy: data.llm_http_proxy || '',
      }
    }
  } catch {
    // ignore
  }
}

async function testLLMConnection() {
  if (!llmConfig.value.llm_api_base) {
    toast.add({ title: 'Please enter an API Base URL', color: 'error' })
    return
  }
  testingLLM.value = true
  testResult.value = { tested: false, success: false, latency_ms: 0 }

  try {
    const res: any = await $fetch('/api/settings/llm/test', {
      method: 'POST',
      body: {
        llm_api_base: llmConfig.value.llm_api_base,
        llm_api_key: llmConfig.value.llm_api_key || undefined,
        llm_model: llmConfig.value.llm_model,
        llm_http_proxy: llmConfig.value.llm_http_proxy || undefined,
      },
    })

    testResult.value = {
      tested: true,
      success: res.success,
      latency_ms: res.latency_ms || 0,
      reply: res.reply,
      error: res.error,
    }

    if (res.success) {
      toast.add({
        title: 'Connection Successful',
        description: `Response verified in ${res.latency_ms}ms`,
        color: 'success',
      })
    } else {
      toast.add({
        title: 'Connection Failed',
        description: res.error || 'Unable to connect to model endpoint',
        color: 'error',
      })
    }
  } catch (err: any) {
    const msg = err?.data?.statusMessage || err?.message || 'Request failed'
    testResult.value = {
      tested: true,
      success: false,
      latency_ms: 0,
      error: msg,
    }
    toast.add({ title: 'Connection Failed', description: msg, color: 'error' })
  } finally {
    testingLLM.value = false
  }
}

// Personalization settings stored in localStorage
const styleTone = ref<string>(localStorage.getItem('sys_style_tone') || 'Default')
const customInstructions = ref<string>(localStorage.getItem('sys_custom_instructions') || '')
const userNickname = ref<string>(localStorage.getItem('sys_user_nickname') || '')
const userOccupation = ref<string>(localStorage.getItem('sys_user_occupation') || '')
const userDetails = ref<string>(localStorage.getItem('sys_user_details') || '')

// 8 Style & Tone Options
const styleToneOptions = [
  { label: 'Default', value: 'Default', icon: 'i-lucide-sparkles' },
  { label: 'Creative', value: 'Creative', icon: 'i-lucide-wand-2' },
  { label: 'Concise', value: 'Concise', icon: 'i-lucide-zap' },
  { label: 'Professional', value: 'Professional', icon: 'i-lucide-briefcase' },
  { label: 'Friendly', value: 'Friendly', icon: 'i-lucide-smile' },
  { label: 'Academic', value: 'Academic', icon: 'i-lucide-graduation-cap' },
  { label: 'Humorous', value: 'Humorous', icon: 'i-lucide-laugh' },
  { label: 'Direct', value: 'Direct', icon: 'i-lucide-target' },
]

const styleToneMenuItems = computed(() => [
  styleToneOptions.map(opt => ({
    label: opt.label,
    icon: opt.icon,
    onSelect: () => { styleTone.value = opt.value },
  })),
])

const themeModes = [
  { label: 'System', value: 'system', icon: 'i-lucide-monitor' },
  { label: 'Light', value: 'light', icon: 'i-lucide-sun' },
  { label: 'Dark', value: 'dark', icon: 'i-lucide-moon' },
]

function setThemeMode(val: 'system' | 'light' | 'dark') {
  colorMode.preference = val
  if (val !== 'system') {
    colorMode.value = val
  }
}

async function saveSettings() {
  savingLLM.value = true
  try {
    // 1. Save Personalization in localStorage
    localStorage.setItem('sys_style_tone', styleTone.value)
    localStorage.setItem('sys_custom_instructions', customInstructions.value)
    localStorage.setItem('sys_user_nickname', userNickname.value)
    localStorage.setItem('sys_user_occupation', userOccupation.value)
    localStorage.setItem('sys_user_details', userDetails.value)

    // 2. Save API Config to backend .env if base URL is provided
    if (llmConfig.value.llm_api_base) {
      await $fetch('/api/settings/llm/save', {
        method: 'POST',
        body: {
          llm_api_base: llmConfig.value.llm_api_base,
          llm_api_key: llmConfig.value.llm_api_key || undefined,
          llm_model: llmConfig.value.llm_model,
          llm_http_proxy: llmConfig.value.llm_http_proxy,
        },
      })
    }

    toast.add({
      title: 'Settings Saved',
      description: 'System preferences and configurations have been saved.',
      color: 'success',
    })
    emit('update:open', false)
  } catch (err: any) {
    toast.add({
      title: 'Save Failed',
      description: err?.data?.statusMessage || err?.message || 'An error occurred while saving settings.',
      color: 'error',
    })
  } finally {
    savingLLM.value = false
  }
}

function resetDefaults() {
  colorMode.preference = 'system'
  styleTone.value = 'Default'
  customInstructions.value = ''
  userNickname.value = ''
  userOccupation.value = ''
  userDetails.value = ''
  saveSettings()
}

watch(() => props.open, (isOpen) => {
  if (isOpen) {
    loadLLMConfig()
  }
})

onMounted(() => {
  loadLLMConfig()
})

const tabs = [
  { id: 'general', label: 'General', icon: 'i-lucide-sliders-horizontal' },
  { id: 'model', label: 'Model & API', icon: 'i-lucide-cpu' },
  { id: 'personalization', label: 'Personalization', icon: 'i-lucide-sparkles' },
  { id: 'account', label: 'Account', icon: 'i-lucide-user' },
]
</script>

<template>
  <UModal
    :open="open"
    prevent-close
    :ui="{
      content: 'sm:max-w-4xl w-full rounded-3xl p-0 overflow-hidden shadow-2xl border border-zinc-200/80 dark:border-zinc-800/80 bg-white dark:bg-zinc-900 text-zinc-800 dark:text-zinc-100',
      width: 'sm:max-w-4xl'
    }"
    @update:open="emit('update:open', $event)"
  >
    <template #content>
      <div class="flex flex-col md:flex-row min-h-[560px] max-h-[85vh] w-full select-none font-sans">
        
        <!-- Left Sidebar Navigation -->
        <div class="w-full md:w-60 bg-zinc-50 dark:bg-zinc-950/60 border-b md:border-b-0 md:border-r border-zinc-200/70 dark:border-zinc-800/70 p-5 flex flex-col justify-between shrink-0">
          <div class="space-y-5">
            <!-- Brand Header -->
            <div class="flex items-center gap-3 px-1.5 py-1">
              <div class="w-9 h-9 rounded-xl bg-zinc-900 dark:bg-white text-white dark:text-zinc-950 flex items-center justify-center font-medium shadow-xs">
                <UIcon name="i-lucide-settings" class="w-5 h-5" />
              </div>
              <div class="min-w-0">
                <h2 class="text-base font-bold text-zinc-900 dark:text-zinc-100 leading-tight">Settings</h2>
                <p class="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5">Preferences</p>
              </div>
            </div>

            <!-- Navigation Tabs -->
            <nav class="space-y-1.5 pt-1">
              <button
                v-for="tab in tabs"
                :key="tab.id"
                type="button"
                :class="[
                  'w-full flex items-center gap-3 px-3.5 py-2.5 rounded-xl text-sm font-medium transition-all cursor-pointer text-left',
                  activeTab === tab.id
                    ? 'bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900 shadow-xs font-semibold'
                    : 'text-zinc-600 dark:text-zinc-400 hover:text-zinc-950 dark:hover:text-zinc-100 hover:bg-zinc-200/60 dark:hover:bg-zinc-800/60'
                ]"
                @click="activeTab = tab.id as any"
              >
                <UIcon :name="tab.icon" class="w-4.5 h-4.5 shrink-0" />
                <span class="truncate">{{ tab.label }}</span>
              </button>
            </nav>
          </div>

          <!-- App Version Footer -->
          <div class="pt-3.5 px-2 border-t border-zinc-200/60 dark:border-zinc-800/60 hidden md:block">
            <div class="text-xs text-zinc-500 dark:text-zinc-400 flex items-center justify-between">
              <span>AI QA Assistant</span>
              <span class="font-mono font-medium text-zinc-600 dark:text-zinc-300">v2.0</span>
            </div>
          </div>
        </div>

        <!-- Right Main Content Panel -->
        <div class="flex-1 flex flex-col min-w-0 bg-transparent">
          
          <!-- Header Bar -->
          <div class="flex items-center justify-between px-7 py-4.5 border-b border-zinc-200/70 dark:border-zinc-800/70 shrink-0">
            <div>
              <h3 class="text-lg font-bold tracking-tight text-zinc-900 dark:text-zinc-100">
                {{ tabs.find(t => t.id === activeTab)?.label }}
              </h3>
              <p class="text-xs sm:text-sm text-zinc-500 dark:text-zinc-400 mt-0.5">
                Manage your {{ tabs.find(t => t.id === activeTab)?.label.toLowerCase() }} preferences
              </p>
            </div>
            <button
              type="button"
              class="w-9 h-9 rounded-xl flex items-center justify-center text-zinc-400 hover:text-zinc-800 dark:hover:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors cursor-pointer"
              @click="emit('update:open', false)"
            >
              <UIcon name="i-lucide-x" class="w-5 h-5" />
            </button>
          </div>

          <!-- Scrollable Tab Content Area -->
          <div class="flex-1 p-7 overflow-y-auto space-y-6 text-zinc-800 dark:text-zinc-200">
            
            <!-- Tab 1: General -->
            <div v-if="activeTab === 'general'" class="space-y-5">
              <!-- Appearance -->
              <div class="p-5 bg-zinc-50 dark:bg-zinc-800/40 rounded-2xl border border-zinc-200/80 dark:border-zinc-800 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                <div>
                  <div class="text-sm sm:text-base font-semibold text-zinc-900 dark:text-zinc-100">Appearance</div>
                  <div class="text-xs sm:text-sm text-zinc-500 dark:text-zinc-400 mt-1">
                    Customize the interface visual theme mode
                  </div>
                </div>

                <!-- Segmented Control -->
                <div class="inline-flex p-1.5 bg-zinc-200/70 dark:bg-zinc-800 rounded-xl gap-1.5 self-start sm:self-auto border border-zinc-300/40 dark:border-zinc-700/40">
                  <button
                    v-for="mode in themeModes"
                    :key="mode.value"
                    type="button"
                    :class="[
                      'flex items-center gap-2 px-3.5 py-2 rounded-lg text-xs sm:text-sm font-medium transition-all cursor-pointer',
                      colorMode.preference === mode.value
                        ? 'bg-white dark:bg-zinc-700 text-zinc-950 dark:text-white shadow-xs font-semibold'
                        : 'text-zinc-600 dark:text-zinc-400 hover:text-zinc-950 dark:hover:text-zinc-100'
                    ]"
                    @click="setThemeMode(mode.value as any)"
                  >
                    <UIcon :name="mode.icon" class="w-4 h-4" />
                    <span>{{ mode.label }}</span>
                  </button>
                </div>
              </div>
            </div>

            <!-- Tab 2: Model & API -->
            <div v-else-if="activeTab === 'model'" class="space-y-5">
              <!-- Quick Presets -->
              <div class="p-4 px-5 bg-zinc-50 dark:bg-zinc-800/40 rounded-2xl border border-zinc-200/80 dark:border-zinc-800 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                <span class="text-xs sm:text-sm font-semibold text-zinc-700 dark:text-zinc-300">Quick Presets</span>
                <div class="flex flex-wrap gap-2">
                  <button
                    v-for="p in presets"
                    :key="p.name"
                    type="button"
                    class="px-3 py-1.5 rounded-xl text-xs sm:text-sm font-medium bg-white dark:bg-zinc-800 text-zinc-700 dark:text-zinc-200 hover:text-zinc-950 dark:hover:text-white border border-zinc-200 dark:border-zinc-700 shadow-2xs hover:shadow-xs transition-all cursor-pointer flex items-center gap-2"
                    @click="applyPreset(p)"
                  >
                    <UIcon :name="p.icon" class="w-4 h-4 text-zinc-500 dark:text-zinc-400" />
                    <span>{{ p.name }}</span>
                  </button>
                </div>
              </div>

              <!-- Base URL -->
              <div class="space-y-2">
                <label class="text-xs sm:text-sm font-semibold text-zinc-700 dark:text-zinc-300">API Base URL</label>
                <input
                  v-model="llmConfig.llm_api_base"
                  type="text"
                  placeholder="https://generativelanguage.googleapis.com/v1beta/openai/"
                  class="w-full bg-zinc-50 dark:bg-zinc-800/40 border border-zinc-200 dark:border-zinc-700 rounded-xl px-4 py-2.5 text-xs sm:text-sm text-zinc-900 dark:text-zinc-100 placeholder-zinc-400 dark:placeholder-zinc-500 font-mono focus:outline-none focus:ring-2 focus:ring-zinc-400 dark:focus:ring-zinc-500"
                />
              </div>

              <!-- API Key with inline Test Button -->
              <div class="space-y-2">
                <div class="flex items-center justify-between">
                  <label class="text-xs sm:text-sm font-semibold text-zinc-700 dark:text-zinc-300">API Key</label>
                  <span v-if="llmConfig.has_api_key" class="text-xs text-zinc-500 dark:text-zinc-400 font-mono">
                    Configured: {{ llmConfig.llm_api_key_masked }}
                  </span>
                </div>
                <div class="flex gap-2.5">
                  <div class="relative flex-1">
                    <input
                      v-model="llmConfig.llm_api_key"
                      :type="showApiKey ? 'text' : 'password'"
                      :placeholder="llmConfig.has_api_key ? 'Leave empty to keep existing key' : 'Enter API Key...'"
                      class="w-full bg-zinc-50 dark:bg-zinc-800/40 border border-zinc-200 dark:border-zinc-700 rounded-xl px-4 py-2.5 text-xs sm:text-sm text-zinc-900 dark:text-zinc-100 placeholder-zinc-400 dark:placeholder-zinc-500 font-mono focus:outline-none focus:ring-2 focus:ring-zinc-400 dark:focus:ring-zinc-500 pr-10"
                    />
                    <button
                      type="button"
                      class="absolute inset-y-0 right-0 px-3 flex items-center text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200 cursor-pointer"
                      @click="showApiKey = !showApiKey"
                    >
                      <UIcon :name="showApiKey ? 'i-lucide-eye-off' : 'i-lucide-eye'" class="w-4.5 h-4.5" />
                    </button>
                  </div>
                  <button
                    type="button"
                    :disabled="testingLLM"
                    class="px-4 py-2.5 rounded-xl text-xs sm:text-sm font-semibold bg-zinc-900 dark:bg-zinc-800 text-white dark:text-zinc-100 hover:bg-zinc-800 dark:hover:bg-zinc-700 transition-colors cursor-pointer flex items-center gap-2 shrink-0 disabled:opacity-50"
                    @click="testLLMConnection"
                  >
                    <UIcon :name="testingLLM ? 'i-lucide-loader-2' : 'i-lucide-zap'" class="w-4 h-4 text-zinc-400" :class="{ 'animate-spin': testingLLM }" />
                    <span>{{ testingLLM ? 'Testing...' : 'Test Connection' }}</span>
                  </button>
                </div>
              </div>

              <!-- Model Name -->
              <div class="space-y-2">
                <label class="text-xs sm:text-sm font-semibold text-zinc-700 dark:text-zinc-300">Model Name</label>
                <input
                  v-model="llmConfig.llm_model"
                  type="text"
                  placeholder="gemini-3.6-flash"
                  class="w-full bg-zinc-50 dark:bg-zinc-800/40 border border-zinc-200 dark:border-zinc-700 rounded-xl px-4 py-2.5 text-xs sm:text-sm text-zinc-900 dark:text-zinc-100 placeholder-zinc-400 dark:placeholder-zinc-500 font-mono focus:outline-none focus:ring-2 focus:ring-zinc-400 dark:focus:ring-zinc-500"
                />
              </div>

              <!-- Proxy -->
              <div class="space-y-2">
                <label class="text-xs sm:text-sm font-semibold text-zinc-700 dark:text-zinc-300">HTTP Proxy (Optional)</label>
                <input
                  v-model="llmConfig.llm_http_proxy"
                  type="text"
                  placeholder="http://127.0.0.1:7897"
                  class="w-full bg-zinc-50 dark:bg-zinc-800/40 border border-zinc-200 dark:border-zinc-700 rounded-xl px-4 py-2.5 text-xs sm:text-sm text-zinc-900 dark:text-zinc-100 placeholder-zinc-400 dark:placeholder-zinc-500 font-mono focus:outline-none focus:ring-2 focus:ring-zinc-400 dark:focus:ring-zinc-500"
                />
              </div>

              <!-- Test Result Status -->
              <div
                v-if="testResult.tested"
                class="p-3.5 rounded-xl border text-xs sm:text-sm transition-all flex items-center justify-between"
                :class="testResult.success
                  ? 'bg-emerald-500/10 border-emerald-500/20 text-emerald-600 dark:text-emerald-400'
                  : 'bg-rose-500/10 border-rose-500/20 text-rose-600 dark:text-rose-400'"
              >
                <div class="flex items-center gap-2.5">
                  <UIcon :name="testResult.success ? 'i-lucide-check-circle' : 'i-lucide-alert-circle'" class="w-4.5 h-4.5 shrink-0" />
                  <span v-if="testResult.success">Connection verified (Latency: {{ testResult.latency_ms }}ms)</span>
                  <span v-else class="truncate max-w-md">{{ testResult.error }}</span>
                </div>
              </div>
            </div>

            <!-- Tab 3: Personalization -->
            <div v-else-if="activeTab === 'personalization'" class="space-y-6">
              <!-- Base Style & Tone -->
              <div class="flex items-center justify-between p-5 bg-zinc-50 dark:bg-zinc-800/40 rounded-2xl border border-zinc-200/80 dark:border-zinc-800">
                <div>
                  <div class="text-sm sm:text-base font-semibold text-zinc-900 dark:text-zinc-100">Response Style & Tone</div>
                  <div class="text-xs sm:text-sm text-zinc-500 dark:text-zinc-400 mt-1">
                    Adjust the conversational demeanor of responses
                  </div>
                </div>
                
                <UDropdownMenu
                  :items="styleToneMenuItems"
                  :content="{ align: 'end', sideOffset: 8 }"
                  :ui="{
                    content: 'min-w-44 p-1.5 rounded-2xl bg-white dark:bg-zinc-900 shadow-xl border border-zinc-200 dark:border-zinc-800 ring-0',
                    group: 'p-0 flex flex-col gap-1',
                    item: 'rounded-xl px-3.5 py-2 text-xs sm:text-sm font-medium cursor-pointer text-zinc-700 dark:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-zinc-800'
                  }"
                >
                  <button
                    type="button"
                    class="text-xs sm:text-sm font-semibold text-zinc-800 dark:text-zinc-200 px-4 py-2 rounded-xl bg-white dark:bg-zinc-800 hover:bg-zinc-100 dark:hover:bg-zinc-700/80 border border-zinc-200 dark:border-zinc-700 shadow-2xs transition-colors cursor-pointer flex items-center gap-2 shrink-0"
                  >
                    <span>{{ styleTone }}</span>
                    <UIcon name="i-lucide-chevron-down" class="w-4 h-4 text-zinc-400" />
                  </button>
                </UDropdownMenu>
              </div>

              <!-- Custom Instructions -->
              <div class="space-y-2">
                <label class="text-xs sm:text-sm font-semibold text-zinc-700 dark:text-zinc-300">Custom System Instructions</label>
                <textarea
                  v-model="customInstructions"
                  rows="3"
                  placeholder="Provide guidance on preferred formats, perspectives, or behavior constraints..."
                  class="w-full bg-zinc-50 dark:bg-zinc-800/40 border border-zinc-200 dark:border-zinc-700 rounded-xl p-3.5 text-xs sm:text-sm text-zinc-900 dark:text-zinc-100 placeholder-zinc-400 dark:placeholder-zinc-500 focus:outline-none focus:ring-2 focus:ring-zinc-400 dark:focus:ring-zinc-500 resize-none font-mono"
                />
              </div>

              <!-- About You -->
              <div class="space-y-4 pt-4 border-t border-zinc-200/60 dark:border-zinc-800/60">
                <div class="text-sm sm:text-base font-semibold text-zinc-900 dark:text-zinc-100">About You</div>

                <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <div class="space-y-2">
                    <label class="text-xs sm:text-sm font-medium text-zinc-600 dark:text-zinc-400">Preferred Name</label>
                    <input
                      v-model="userNickname"
                      type="text"
                      placeholder="How should AI address you?"
                      class="w-full bg-zinc-50 dark:bg-zinc-800/40 border border-zinc-200 dark:border-zinc-700 rounded-xl px-4 py-2.5 text-xs sm:text-sm text-zinc-900 dark:text-zinc-100 placeholder-zinc-400 dark:placeholder-zinc-500 focus:outline-none focus:ring-2 focus:ring-zinc-400 dark:focus:ring-zinc-500"
                    />
                  </div>

                  <div class="space-y-2">
                    <label class="text-xs sm:text-sm font-medium text-zinc-600 dark:text-zinc-400">Role / Profession</label>
                    <input
                      v-model="userOccupation"
                      type="text"
                      placeholder="e.g. Researcher, Engineer, Student"
                      class="w-full bg-zinc-50 dark:bg-zinc-800/40 border border-zinc-200 dark:border-zinc-700 rounded-xl px-4 py-2.5 text-xs sm:text-sm text-zinc-900 dark:text-zinc-100 placeholder-zinc-400 dark:placeholder-zinc-500 focus:outline-none focus:ring-2 focus:ring-zinc-400 dark:focus:ring-zinc-500"
                    />
                  </div>
                </div>

                <div class="space-y-2">
                  <label class="text-xs sm:text-sm font-medium text-zinc-600 dark:text-zinc-400">Preferences & Background</label>
                  <textarea
                    v-model="userDetails"
                    rows="2"
                    placeholder="Specific background or preferences helpful for contextualizing answers..."
                    class="w-full bg-zinc-50 dark:bg-zinc-800/40 border border-zinc-200 dark:border-zinc-700 rounded-xl p-3.5 text-xs sm:text-sm text-zinc-900 dark:text-zinc-100 placeholder-zinc-400 dark:placeholder-zinc-500 focus:outline-none focus:ring-2 focus:ring-zinc-400 dark:focus:ring-zinc-500 resize-none"
                  />
                </div>
              </div>
            </div>

            <!-- Tab 4: Account -->
            <div v-else-if="activeTab === 'account'" class="space-y-5">
              <div class="p-5 bg-zinc-50 dark:bg-zinc-800/40 rounded-2xl border border-zinc-200/80 dark:border-zinc-800 flex items-center justify-between">
                <div class="flex items-center gap-3.5">
                  <img
                    v-if="loggedIn && user?.avatar"
                    :src="user.avatar"
                    :alt="user.name"
                    class="w-12 h-12 rounded-full border border-zinc-200 dark:border-zinc-700"
                  />
                  <div
                    v-else
                    class="w-12 h-12 rounded-full bg-zinc-200 dark:bg-zinc-800 text-zinc-700 dark:text-zinc-200 font-semibold flex items-center justify-center text-base"
                  >
                    {{ user?.name?.[0] || 'U' }}
                  </div>
                  <div>
                    <div class="text-sm sm:text-base font-semibold text-zinc-900 dark:text-zinc-100">
                      {{ user?.name || user?.username || 'Current Session' }}
                    </div>
                    <div class="text-xs sm:text-sm text-zinc-500 dark:text-zinc-400 mt-0.5">
                      {{ loggedIn ? (user?.email || 'Authenticated User') : 'Local Mode' }}
                    </div>
                  </div>
                </div>

                <span
                  class="px-3 py-1 text-xs font-semibold rounded-full"
                  :class="loggedIn
                    ? 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-500/20'
                    : 'bg-zinc-200/70 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-400'"
                >
                  {{ loggedIn ? 'Active' : 'Local' }}
                </span>
              </div>

              <!-- Logout Button if logged in -->
              <div v-if="loggedIn" class="pt-2">
                <button
                  type="button"
                  class="w-full py-2.5 px-4 rounded-xl text-xs sm:text-sm font-semibold text-rose-600 dark:text-rose-400 hover:bg-rose-500/10 border border-rose-500/20 transition-colors cursor-pointer flex items-center justify-center gap-2"
                  @click="clearSession(); emit('update:open', false);"
                >
                  <UIcon name="i-lucide-log-out" class="w-4.5 h-4.5" />
                  <span>Log out</span>
                </button>
              </div>
            </div>

          </div>

          <!-- Bottom Actions Bar -->
          <div class="p-4 px-7 border-t border-zinc-200/70 dark:border-zinc-800/70 flex items-center justify-between bg-zinc-50/70 dark:bg-zinc-900/70 shrink-0">
            <button
              type="button"
              class="text-xs sm:text-sm font-medium text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-200 transition-colors cursor-pointer flex items-center gap-2"
              @click="resetDefaults"
            >
              <UIcon name="i-lucide-rotate-ccw" class="w-4 h-4" />
              <span>Reset Defaults</span>
            </button>
            <div class="flex items-center gap-2.5">
              <button
                type="button"
                class="px-4 py-2.5 rounded-xl text-xs sm:text-sm font-medium text-zinc-600 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors cursor-pointer"
                @click="emit('update:open', false)"
              >
                Cancel
              </button>
              <button
                type="button"
                :disabled="savingLLM"
                class="px-5 py-2.5 rounded-xl text-xs sm:text-sm font-semibold bg-zinc-900 dark:bg-zinc-100 text-white dark:text-zinc-950 hover:bg-zinc-800 dark:hover:bg-zinc-200 transition-colors cursor-pointer flex items-center gap-2 shadow-xs disabled:opacity-50"
                @click="saveSettings"
              >
                <UIcon :name="savingLLM ? 'i-lucide-loader-2' : 'i-lucide-check'" class="w-4 h-4" :class="{ 'animate-spin': savingLLM }" />
                <span>Save Settings</span>
              </button>
            </div>
          </div>

        </div>

      </div>
    </template>
  </UModal>
</template>
