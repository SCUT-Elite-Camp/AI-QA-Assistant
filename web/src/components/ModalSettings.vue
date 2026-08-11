<script setup lang="ts">
import { ref } from 'vue'
import { useColorMode } from '@vueuse/core'

defineProps<{
  open: boolean
}>()

const emit = defineEmits<{
  'update:open': [value: boolean]
}>()

const colorMode = useColorMode()
const appConfig = useAppConfig()

const colors = ['emerald', 'teal', 'cyan', 'sky', 'blue', 'indigo', 'violet', 'purple', 'fuchsia', 'pink', 'rose', 'orange', 'amber', 'yellow', 'lime', 'green']
const neutrals = ['slate', 'gray', 'zinc', 'neutral', 'stone']

// RAG Local settings state stored in localStorage
const topK = ref<number>(Number(localStorage.getItem('sys_top_k') || 5))
const retrievalMode = ref<'hybrid' | 'vector' | 'bm25'>((localStorage.getItem('sys_retrieval_mode') as any) || 'hybrid')
const temperature = ref<number>(Number(localStorage.getItem('sys_temperature') || 0.1))
const maxTokens = ref<number>(Number(localStorage.getItem('sys_max_tokens') || 2000))

function saveSettings() {
  localStorage.setItem('sys_top_k', String(topK.value))
  localStorage.setItem('sys_retrieval_mode', retrievalMode.value)
  localStorage.setItem('sys_temperature', String(temperature.value))
  localStorage.setItem('sys_max_tokens', String(maxTokens.value))

  const toast = useToast()
  toast.add({
    title: '系统设置保存成功',
    description: '主题与 RAG 参数已更新。',
    color: 'success'
  })
  emit('update:open', false)
}
</script>

<template>
  <UModal
    :open="open"
    prevent-close
    :ui="{ width: 'sm:max-w-xl' }"
    @update:open="emit('update:open', $event)"
  >
    <template #content>
      <div class="p-6 bg-zinc-950 text-zinc-100 rounded-3xl space-y-6 max-h-[85vh] overflow-y-auto border border-zinc-800 shadow-2xl">
        <!-- Header -->
        <div class="flex items-center justify-between pb-4 border-b border-zinc-800">
          <div class="flex items-center gap-3">
            <div class="p-2.5 rounded-xl bg-sky-500/10 border border-sky-500/20 text-sky-400">
              <UIcon name="i-lucide-settings" class="w-6 h-6" />
            </div>
            <div>
              <h2 class="text-xl font-bold text-zinc-100 tracking-tight">系统设置 (System Settings)</h2>
              <p class="text-xs text-zinc-400">自定义界面主题与 RAG 模型全局检索参数</p>
            </div>
          </div>
          <UButton
            color="neutral"
            variant="ghost"
            icon="i-lucide-x"
            size="sm"
            class="rounded-xl text-zinc-400 hover:text-white"
            @click="emit('update:open', false)"
          />
        </div>

        <!-- Section 1: Appearance & Theme -->
        <div class="space-y-4">
          <h3 class="text-xs font-semibold text-zinc-400 uppercase tracking-wider flex items-center gap-1.5">
            <UIcon name="i-lucide-palette" class="w-4 h-4 text-emerald-400" />
            界面与主题 (Theme & Appearance)
          </h3>

          <!-- Primary Color -->
          <div class="space-y-2 bg-zinc-900/60 p-3.5 rounded-2xl border border-zinc-800">
            <label class="text-xs font-medium text-zinc-300">主题主色调 (Primary Color)</label>
            <div class="flex flex-wrap gap-2 pt-1">
              <button
                v-for="color in colors"
                :key="color"
                type="button"
                :title="color"
                :class="[
                  'w-7 h-7 rounded-full transition-transform flex items-center justify-center cursor-pointer',
                  appConfig.ui.colors.primary === color ? 'ring-2 ring-white scale-110' : 'opacity-80 hover:opacity-100 hover:scale-105'
                ]"
                :style="{ backgroundColor: `var(--color-${color}-500, ${color})` }"
                @click="appConfig.ui.colors.primary = color"
              >
                <UIcon v-if="appConfig.ui.colors.primary === color" name="i-lucide-check" class="w-4 h-4 text-white drop-shadow" />
              </button>
            </div>
          </div>

          <!-- Neutral Tone & Appearance Mode -->
          <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div class="space-y-2 bg-zinc-900/60 p-3.5 rounded-2xl border border-zinc-800">
              <label class="text-xs font-medium text-zinc-300">中性灰调 (Neutral Tone)</label>
              <div class="flex flex-wrap gap-1.5 pt-1">
                <button
                  v-for="nColor in neutrals"
                  :key="nColor"
                  type="button"
                  :class="[
                    'px-2.5 py-1 text-xs rounded-lg border transition-all capitalize cursor-pointer',
                    appConfig.ui.colors.neutral === nColor
                      ? 'bg-emerald-500/20 border-emerald-500/50 text-emerald-300 font-semibold'
                      : 'bg-zinc-950 border-zinc-800 text-zinc-400 hover:text-zinc-200'
                  ]"
                  @click="appConfig.ui.colors.neutral = nColor"
                >
                  {{ nColor }}
                </button>
              </div>
            </div>

            <div class="space-y-2 bg-zinc-900/60 p-3.5 rounded-2xl border border-zinc-800">
              <label class="text-xs font-medium text-zinc-300">深浅外观 (Appearance)</label>
              <div class="flex gap-2 pt-1">
                <UButton
                  size="xs"
                  :color="colorMode.value === 'dark' ? 'primary' : 'neutral'"
                  :variant="colorMode.value === 'dark' ? 'solid' : 'outline'"
                  icon="i-lucide-moon"
                  label="Dark"
                  class="flex-1 justify-center rounded-lg cursor-pointer"
                  @click="colorMode.value = 'dark'"
                />
                <UButton
                  size="xs"
                  :color="colorMode.value === 'light' ? 'primary' : 'neutral'"
                  :variant="colorMode.value === 'light' ? 'solid' : 'outline'"
                  icon="i-lucide-sun"
                  label="Light"
                  class="flex-1 justify-center rounded-lg cursor-pointer"
                  @click="colorMode.value = 'light'"
                />
              </div>
            </div>
          </div>
        </div>

        <!-- Section 2: Model & RAG Settings -->
        <div class="space-y-4 pt-2 border-t border-zinc-800/80">
          <h3 class="text-xs font-semibold text-zinc-400 uppercase tracking-wider flex items-center gap-1.5">
            <UIcon name="i-lucide-sliders" class="w-4 h-4 text-sky-400" />
            RAG 检索与模型参数 (Retrieval & Model Parameters)
          </h3>

          <div class="space-y-4 bg-zinc-900/60 p-4 rounded-2xl border border-zinc-800">
            <!-- Retrieval Mode -->
            <div class="space-y-1.5">
              <div class="flex items-center justify-between text-xs">
                <span class="font-medium text-zinc-300">默认检索模式 (Retrieval Mode)</span>
                <span class="text-zinc-500 font-mono capitalize">{{ retrievalMode }}</span>
              </div>
              <div class="grid grid-cols-3 gap-2 pt-1">
                <button
                  type="button"
                  :class="[
                    'p-2 rounded-xl text-xs font-medium border text-center transition-all cursor-pointer',
                    retrievalMode === 'hybrid'
                      ? 'bg-emerald-500/20 border-emerald-500/50 text-emerald-300'
                      : 'bg-zinc-950 border-zinc-800 text-zinc-400 hover:text-zinc-200'
                  ]"
                  @click="retrievalMode = 'hybrid'"
                >
                  <div class="font-bold">Hybrid</div>
                  <div class="text-[10px] opacity-75">向量 + 关键词</div>
                </button>
                <button
                  type="button"
                  :class="[
                    'p-2 rounded-xl text-xs font-medium border text-center transition-all cursor-pointer',
                    retrievalMode === 'vector'
                      ? 'bg-emerald-500/20 border-emerald-500/50 text-emerald-300'
                      : 'bg-zinc-950 border-zinc-800 text-zinc-400 hover:text-zinc-200'
                  ]"
                  @click="retrievalMode = 'vector'"
                >
                  <div class="font-bold">Vector</div>
                  <div class="text-[10px] opacity-75">Milvus 向量</div>
                </button>
                <button
                  type="button"
                  :class="[
                    'p-2 rounded-xl text-xs font-medium border text-center transition-all cursor-pointer',
                    retrievalMode === 'bm25'
                      ? 'bg-emerald-500/20 border-emerald-500/50 text-emerald-300'
                      : 'bg-zinc-950 border-zinc-800 text-zinc-400 hover:text-zinc-200'
                  ]"
                  @click="retrievalMode = 'bm25'"
                >
                  <div class="font-bold">BM25</div>
                  <div class="text-[10px] opacity-75">关键词匹配</div>
                </button>
              </div>
            </div>

            <!-- Top K -->
            <div class="space-y-1.5 pt-2 border-t border-zinc-800/60">
              <div class="flex items-center justify-between text-xs">
                <span class="font-medium text-zinc-300">Top-K 检索数量 (Document Chunks)</span>
                <span class="font-mono text-emerald-400 font-bold">{{ topK }}</span>
              </div>
              <input
                v-model.number="topK"
                type="range"
                min="1"
                max="20"
                step="1"
                class="w-full accent-emerald-500 bg-zinc-950 rounded-lg h-2 cursor-pointer"
              />
            </div>

            <!-- Temperature -->
            <div class="space-y-1.5 pt-2 border-t border-zinc-800/60">
              <div class="flex items-center justify-between text-xs">
                <span class="font-medium text-zinc-300">Temperature (随机发散度)</span>
                <span class="font-mono text-purple-400 font-bold">{{ temperature }}</span>
              </div>
              <input
                v-model.number="temperature"
                type="range"
                min="0.0"
                max="1.0"
                step="0.05"
                class="w-full accent-purple-500 bg-zinc-950 rounded-lg h-2 cursor-pointer"
              />
            </div>

            <!-- Max Tokens -->
            <div class="space-y-1.5 pt-2 border-t border-zinc-800/60">
              <div class="flex items-center justify-between text-xs">
                <span class="font-medium text-zinc-300">Max Output Tokens</span>
                <span class="font-mono text-sky-400 font-bold">{{ maxTokens }}</span>
              </div>
              <input
                v-model.number="maxTokens"
                type="range"
                min="500"
                max="4000"
                step="100"
                class="w-full accent-sky-500 bg-zinc-950 rounded-lg h-2 cursor-pointer"
              />
            </div>
          </div>
        </div>

        <!-- Footer Actions -->
        <div class="pt-4 flex items-center justify-end gap-3 border-t border-zinc-800">
          <UButton
            color="neutral"
            variant="ghost"
            label="取消"
            class="rounded-xl"
            @click="emit('update:open', false)"
          />
          <UButton
            color="primary"
            label="保存设置"
            icon="i-lucide-check"
            class="rounded-xl font-medium"
            @click="saveSettings"
          />
        </div>
      </div>
    </template>
  </UModal>
</template>
