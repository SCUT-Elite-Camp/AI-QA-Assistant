<script setup lang="ts">
import { ref, computed } from 'vue'
import { useColorMode } from '@vueuse/core'
import { useUserSession } from '../composables/useUserSession'

defineProps<{
  open: boolean
}>()

const emit = defineEmits<{
  'update:open': [value: boolean]
}>()

const activeTab = ref<'general' | 'personalization' | 'documents' | 'account'>('general')

const colorMode = useColorMode()
const appConfig = useAppConfig()
const { user, clearSession, loggedIn } = useUserSession()

const colors = ['emerald', 'teal', 'cyan', 'sky', 'blue', 'indigo', 'violet', 'purple', 'fuchsia', 'pink', 'rose', 'orange', 'amber', 'yellow', 'lime', 'green']
const neutrals = ['slate', 'gray', 'zinc', 'neutral', 'stone']

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
  { label: 'Direct', value: 'Direct', icon: 'i-lucide-target' }
]

const styleToneMenuItems = computed(() => [
  styleToneOptions.map(opt => ({
    label: opt.label,
    icon: opt.icon,
    onSelect: () => { styleTone.value = opt.value }
  }))
])

const appearanceLabel = computed(() => {
  if (colorMode.preference === 'system') return 'System'
  return colorMode.value === 'dark' ? 'Dark' : 'Light'
})

const appearanceItems = computed(() => [
  [
    {
      label: 'System',
      icon: 'i-lucide-monitor',
      onSelect: () => { colorMode.preference = 'system' }
    },
    {
      label: 'Dark',
      icon: 'i-lucide-moon',
      onSelect: () => { colorMode.preference = 'dark'; colorMode.value = 'dark' }
    },
    {
      label: 'Light',
      icon: 'i-lucide-sun',
      onSelect: () => { colorMode.preference = 'light'; colorMode.value = 'light' }
    }
  ]
])

function saveSettings() {
  localStorage.setItem('sys_style_tone', styleTone.value)
  localStorage.setItem('sys_custom_instructions', customInstructions.value)
  localStorage.setItem('sys_user_nickname', userNickname.value)
  localStorage.setItem('sys_user_occupation', userOccupation.value)
  localStorage.setItem('sys_user_details', userDetails.value)

  const toast = useToast()
  toast.add({
    title: 'Settings Saved',
    description: 'System preferences have been updated successfully.',
    color: 'success'
  })
  emit('update:open', false)
}

function resetDefaults() {
  colorMode.preference = 'dark'
  colorMode.value = 'dark'
  appConfig.ui.colors.primary = 'emerald'
  appConfig.ui.colors.neutral = 'slate'
  styleTone.value = 'Default'
  customInstructions.value = ''
  userNickname.value = ''
  userOccupation.value = ''
  userDetails.value = ''
  saveSettings()
}

const tabs = [
  { id: 'general', label: 'General', icon: 'i-lucide-sliders-horizontal' },
  { id: 'personalization', label: 'Personalization', icon: 'i-lucide-palette' },
  { id: 'documents', label: 'Documents', icon: 'i-lucide-file-text' },
  { id: 'account', label: 'Account', icon: 'i-lucide-user' }
]
</script>

<template>
  <UModal
    :open="open"
    prevent-close
    :ui="{
      content: 'sm:max-w-4xl w-full rounded-3xl p-0 overflow-hidden shadow-2xl border border-zinc-800 bg-zinc-950',
      width: 'sm:max-w-4xl'
    }"
    @update:open="emit('update:open', $event)"
  >
    <template #content>
      <div class="bg-zinc-950 text-zinc-100 rounded-3xl overflow-hidden flex flex-col md:flex-row min-h-[540px] max-h-[85vh] w-full">
        
        <!-- Left Sidebar Navigation -->
        <div class="w-full md:w-56 bg-zinc-900/60 border-b md:border-b-0 md:border-r border-zinc-800/80 p-4 flex flex-col justify-between shrink-0">
          <div class="space-y-4">
            <div class="flex items-center gap-2.5 px-2 py-1">
              <div class="p-2 rounded-xl bg-emerald-500/10 border border-emerald-500/20 text-emerald-400">
                <UIcon name="i-lucide-settings" class="w-5 h-5" />
              </div>
              <div>
                <h2 class="text-base font-bold text-zinc-100 leading-none">Settings</h2>
                <p class="text-[11px] text-zinc-400 mt-1">System Preferences</p>
              </div>
            </div>

            <nav class="space-y-1 pt-2">
              <button
                v-for="tab in tabs"
                :key="tab.id"
                type="button"
                :class="[
                  'w-full flex items-center gap-2.5 px-3 py-2.5 rounded-xl text-xs font-medium transition-all cursor-pointer text-left',
                  activeTab === tab.id
                    ? 'bg-emerald-500/15 border-l-2 border-emerald-400 text-emerald-300 font-semibold shadow-xs'
                    : 'text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/50'
                ]"
                @click="activeTab = tab.id as any"
              >
                <UIcon :name="tab.icon" class="w-4 h-4 shrink-0" :class="activeTab === tab.id ? 'text-emerald-400' : 'text-zinc-500'" />
                <span class="flex-1 text-xs font-medium">{{ tab.label }}</span>
              </button>
            </nav>
          </div>

          <!-- App Version Footer -->
          <div class="pt-4 px-2 border-t border-zinc-800/60 hidden md:block">
            <div class="text-[11px] text-zinc-500 flex items-center justify-between">
              <span>AI QA Assistant</span>
              <span class="font-mono text-emerald-500/80 font-bold">v2.0</span>
            </div>
          </div>
        </div>

        <!-- Right Main Content Panel -->
        <div class="flex-1 flex flex-col min-w-0 bg-zinc-950">
          
          <!-- Header Bar -->
          <div class="flex items-center justify-between px-6 py-4 border-b border-zinc-800/80 shrink-0">
            <div>
              <h3 class="text-base font-bold text-zinc-100">
                {{ tabs.find(t => t.id === activeTab)?.label }} Settings
              </h3>
              <p class="text-xs text-zinc-400">
                Configure your {{ tabs.find(t => t.id === activeTab)?.label.toLowerCase() }} options
              </p>
            </div>
            <UButton
              color="neutral"
              variant="ghost"
              icon="i-lucide-x"
              size="sm"
              class="rounded-xl text-zinc-400 hover:text-white cursor-pointer"
              @click="emit('update:open', false)"
            />
          </div>

          <!-- Scrollable Tab Content Area -->
          <div class="flex-1 p-6 overflow-y-auto space-y-6">
            
            <!-- Tab 1: General (Minimalist Appearance Dropdown Row) -->
            <div v-if="activeTab === 'general'" class="space-y-4 animate-in fade-in duration-200">
              <div class="flex items-center justify-between py-3.5 px-4 bg-zinc-900/60 rounded-2xl border border-zinc-800/80">
                <span class="text-sm font-medium text-zinc-200">Appearance</span>
                
                <UDropdownMenu :items="appearanceItems" :content="{ align: 'end' }">
                  <UButton
                    color="neutral"
                    variant="ghost"
                    size="sm"
                    trailing-icon="i-lucide-chevron-down"
                    class="text-xs font-medium text-zinc-300 hover:text-white px-3 py-1.5 rounded-xl bg-zinc-800/60 hover:bg-zinc-800 border border-zinc-700/50 cursor-pointer"
                  >
                    {{ appearanceLabel }}
                  </UButton>
                </UDropdownMenu>
              </div>
            </div>

            <!-- Tab 2: Personalization -->
            <div v-else-if="activeTab === 'personalization'" class="space-y-6 animate-in fade-in duration-200">
              
              <!-- 1. Base Style & Tone (Minimalist Dropdown Row - 8 Options) -->
              <div class="space-y-3">
                <div class="flex items-center justify-between p-4 bg-zinc-900/60 rounded-2xl border border-zinc-800/80">
                  <div>
                    <div class="text-sm font-semibold text-zinc-100">Base Style & Tone</div>
                    <div class="text-xs text-zinc-400 mt-0.5">
                      Set the tone and style of AI responses. This won't affect core capabilities.
                    </div>
                  </div>
                  
                  <UDropdownMenu :items="styleToneMenuItems" :content="{ align: 'end' }">
                    <UButton
                      color="neutral"
                      variant="ghost"
                      size="sm"
                      trailing-icon="i-lucide-chevron-down"
                      class="text-xs font-medium text-zinc-200 hover:text-white px-3 py-1.5 rounded-xl bg-zinc-800/60 hover:bg-zinc-800 border border-zinc-700/50 cursor-pointer shrink-0 ml-4"
                    >
                      {{ styleTone }}
                    </UButton>
                  </UDropdownMenu>
                </div>
              </div>

              <!-- 2. Custom Instructions -->
              <div class="space-y-2">
                <div class="text-sm font-semibold text-zinc-100">Custom Instructions</div>
                <div class="text-xs text-zinc-400">
                  What would you like the AI to know or follow when responding?
                </div>
                <textarea
                  v-model="customInstructions"
                  rows="3"
                  placeholder="Before answering all questions, please first search the web to gather sufficient information, and then provide your response."
                  class="w-full bg-zinc-900/80 border border-zinc-800 rounded-2xl p-3.5 text-xs text-zinc-100 placeholder-zinc-500 focus:outline-none focus:ring-1 focus:ring-emerald-500 resize-none font-mono"
                />
              </div>

              <!-- 3. About You -->
              <div class="space-y-4 pt-4 border-t border-zinc-800/80">
                <div>
                  <div class="text-sm font-semibold text-zinc-100">About You</div>
                  <div class="text-xs text-zinc-400 mt-0.5">
                    Share details about yourself so AI can personalize answers.
                  </div>
                </div>

                <!-- Nickname -->
                <div class="space-y-1.5">
                  <label class="text-xs font-medium text-zinc-300">Nickname</label>
                  <input
                    v-model="userNickname"
                    type="text"
                    placeholder="What should AI call you?"
                    class="w-full bg-zinc-900/80 border border-zinc-800 rounded-xl px-3.5 py-2.5 text-xs text-zinc-100 placeholder-zinc-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
                  />
                </div>

                <!-- Occupation -->
                <div class="space-y-1.5">
                  <label class="text-xs font-medium text-zinc-300">Occupation</label>
                  <input
                    v-model="userOccupation"
                    type="text"
                    placeholder="e.g. Software Engineer, Excel Guide, Student"
                    class="w-full bg-zinc-900/80 border border-zinc-800 rounded-xl px-3.5 py-2.5 text-xs text-zinc-100 placeholder-zinc-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
                  />
                </div>

                <!-- Details / Preferences -->
                <div class="space-y-1.5">
                  <label class="text-xs font-medium text-zinc-300">Your Details</label>
                  <textarea
                    v-model="userDetails"
                    rows="2"
                    placeholder="Interests, values, or preferences for AI to remember..."
                    class="w-full bg-zinc-900/80 border border-zinc-800 rounded-2xl p-3.5 text-xs text-zinc-100 placeholder-zinc-500 focus:outline-none focus:ring-1 focus:ring-emerald-500 resize-none"
                  />
                </div>
              </div>

            </div>

            <!-- Tab 3: Documents -->
            <div v-else-if="activeTab === 'documents'" class="space-y-6 animate-in fade-in duration-200">
              
              <div class="space-y-4">
                <h4 class="text-xs font-semibold text-zinc-400 uppercase tracking-wider flex items-center gap-1.5">
                  <UIcon name="i-lucide-database" class="w-4 h-4 text-emerald-400" />
                  Document & Vector Store Overview
                </h4>

                <!-- Minimalist Grid: Total Docs, Total Chunks, Embedding Model -->
                <div class="grid grid-cols-1 sm:grid-cols-3 gap-3">
                  <div class="bg-zinc-900/60 p-4 rounded-2xl border border-zinc-800/80 space-y-1">
                    <div class="text-xs text-zinc-400">Total Documents</div>
                    <div class="text-lg font-bold text-emerald-400 font-mono">
                      49 Documents
                    </div>
                  </div>

                  <div class="bg-zinc-900/60 p-4 rounded-2xl border border-zinc-800/80 space-y-1">
                    <div class="text-xs text-zinc-400">Total Chunks</div>
                    <div class="text-lg font-bold text-sky-400 font-mono">
                      88,520 Chunks
                    </div>
                  </div>

                  <div class="bg-zinc-900/60 p-4 rounded-2xl border border-zinc-800/80 space-y-1">
                    <div class="text-xs text-zinc-400">Embedding Model</div>
                    <div class="text-xs font-bold text-zinc-200 font-mono truncate pt-1">
                      BAAI/bge-small-en-v1.5
                    </div>
                  </div>
                </div>
              </div>

              <!-- Manage Documents Action Box & Button -->
              <div class="p-4 rounded-2xl bg-zinc-900/40 border border-zinc-800 flex items-center justify-between">
                <div>
                  <div class="text-sm font-semibold text-zinc-200">Manage Ingested Documents</div>
                  <div class="text-xs text-zinc-400 mt-0.5">View and manage all document knowledge pools and reference files</div>
                </div>
                <UButton
                  to="/documents"
                  color="primary"
                  variant="solid"
                  size="sm"
                  label="Manage Documents"
                  icon="i-lucide-folder-open"
                  class="rounded-xl cursor-pointer font-medium px-4 py-2 shrink-0 ml-4"
                  @click="emit('update:open', false)"
                />
              </div>

            </div>

            <!-- Tab 4: Account -->
            <div v-else-if="activeTab === 'account'" class="space-y-6 animate-in fade-in duration-200">
              
              <!-- User Profile Information -->
              <div class="space-y-3">
                <h4 class="text-xs font-semibold text-zinc-400 uppercase tracking-wider flex items-center gap-1.5">
                  <UIcon name="i-lucide-user-check" class="w-4 h-4 text-emerald-400" />
                  Account Profile
                </h4>

                <div v-if="loggedIn && user" class="bg-zinc-900/60 p-4 rounded-2xl border border-zinc-800/80 flex items-center justify-between">
                  <div class="flex items-center gap-3">
                    <img
                      v-if="user.avatar"
                      :src="user.avatar"
                      :alt="user.name"
                      class="w-12 h-12 rounded-full border border-zinc-700"
                    />
                    <div v-else class="w-12 h-12 rounded-full bg-emerald-500/20 text-emerald-400 font-bold flex items-center justify-center text-lg">
                      {{ user.name?.[0] || 'U' }}
                    </div>
                    <div>
                      <div class="text-sm font-bold text-zinc-100">{{ user.name || user.username }}</div>
                      <div class="text-xs text-zinc-400">{{ user.email || 'GitHub Authenticated User' }}</div>
                    </div>
                  </div>
                  <span class="px-2.5 py-1 text-[11px] font-semibold text-emerald-400 bg-emerald-400/10 rounded-full border border-emerald-400/20">
                    Logged In
                  </span>
                </div>

                <div v-else class="bg-zinc-900/60 p-4 rounded-2xl border border-zinc-800/80 text-xs text-zinc-400">
                  Currently running in Local Guest Mode.
                </div>
              </div>

              <!-- AI API Config Info -->
              <div class="space-y-3">
                <h4 class="text-xs font-semibold text-zinc-400 uppercase tracking-wider flex items-center gap-1.5">
                  <UIcon name="i-lucide-cpu" class="w-4 h-4 text-sky-400" />
                  AI Backend Configuration
                </h4>

                <div class="bg-zinc-900/60 p-4 rounded-2xl border border-zinc-800/80 space-y-2.5 text-xs text-zinc-300">
                  <div class="flex items-center justify-between">
                    <span class="text-zinc-400">LLM Provider</span>
                    <span class="font-mono font-bold text-zinc-200">LongCat API (OpenAI Compatible)</span>
                  </div>
                  <div class="flex items-center justify-between pt-2 border-t border-zinc-800/60">
                    <span class="text-zinc-400">Base URL</span>
                    <span class="font-mono text-emerald-400">https://api.longcat.chat/openai/v1</span>
                  </div>
                  <div class="flex items-center justify-between pt-2 border-t border-zinc-800/60">
                    <span class="text-zinc-400">Active Model</span>
                    <span class="font-mono font-bold text-sky-400">LongCat-2.0</span>
                  </div>
                </div>
              </div>

              <!-- Logout Button -->
              <div v-if="loggedIn" class="pt-2">
                <UButton
                  color="error"
                  variant="subtle"
                  icon="i-lucide-log-out"
                  label="Log out"
                  class="w-full justify-center rounded-xl cursor-pointer"
                  @click="clearSession(); emit('update:open', false);"
                />
              </div>

            </div>

          </div>

          <!-- Bottom Actions Bar -->
          <div class="p-4 px-6 border-t border-zinc-800/80 flex items-center justify-between bg-zinc-900/40 shrink-0">
            <UButton
              color="neutral"
              variant="ghost"
              size="xs"
              icon="i-lucide-rotate-ccw"
              label="Reset to Defaults"
              class="rounded-xl text-zinc-400 hover:text-zinc-200 cursor-pointer"
              @click="resetDefaults"
            />
            <div class="flex items-center gap-2">
              <UButton
                color="neutral"
                variant="ghost"
                label="Cancel"
                class="rounded-xl cursor-pointer"
                @click="emit('update:open', false)"
              />
              <UButton
                color="primary"
                label="Save Settings"
                icon="i-lucide-check"
                class="rounded-xl font-medium cursor-pointer"
                @click="saveSettings"
              />
            </div>
          </div>

        </div>

      </div>
    </template>
  </UModal>
</template>
