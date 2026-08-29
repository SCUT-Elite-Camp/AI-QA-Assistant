import { isToday, isYesterday, subMonths } from 'date-fns'
import { computed, ref } from 'vue'
import { createSharedComposable } from '@vueuse/core'
import { $fetch } from 'ofetch'
import type { Chat as ChatData } from '~/server/utils/drizzle'

interface Chat {
  id: string
  label: string
  to: string
  icon: string
  createdAt: string
  topicId?: string | null
}

export const useChats = createSharedComposable(() => {
  const chats = ref<Chat[]>([])

  const fetchChats = async () => {
    chats.value = await $fetch('/api/chats').then((data: ChatData[]) => data.map(chat => ({
      id: chat.id,
      label: chat.title || 'Untitled',
      to: `/chat/${chat.id}`,
      icon: 'i-lucide-message-circle',
      createdAt: String(chat.createdAt),
      topicId: (chat as any).topicId ?? null
    }) as Chat)).catch(error => {
      console.error(error)
      return []
    })
  }

  const updateChat = (id: string, partial: Partial<Chat>) => {
    chats.value = chats.value.map(c => c.id === id ? { ...c, ...partial } : c)
  }

  const removeChat = (id: string) => {
    chats.value = chats.value.filter(c => c.id !== id)
  }

  const groups = computed(() => {
    if (!chats.value?.length) return []
    return [
      {
        id: 'all-chats',
        label: '',
        items: chats.value
      }
    ]
  })

  return {
    groups,
    chats,
    fetchChats,
    updateChat,
    removeChat
  }
})
