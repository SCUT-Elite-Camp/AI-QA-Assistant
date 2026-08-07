import { defineAsyncComponent } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { $fetch } from 'ofetch'
import { useChats } from './useChats'
import { useCsrf } from './useCsrf'

const ModalRename = defineAsyncComponent(() => import('../components/ModalRename.vue'))
const ModalConfirm = defineAsyncComponent(() => import('../components/ModalConfirm.vue'))

export function useChatActions() {
  const route = useRoute()
  const router = useRouter()
  const toast = useToast()
  const overlay = useOverlay()
  const { csrf, headerName } = useCsrf()
  const { updateChat, removeChat, fetchChats } = useChats()

  const renameModal = overlay.create(ModalRename)
  const deleteModal = overlay.create(ModalConfirm, {
    props: {
      title: 'Delete chat',
      description: 'Are you sure you want to delete this chat? This action cannot be undone.',
      color: 'error'
    }
  })

  async function renameChat(id: string, currentTitle?: string | null): Promise<string | null> {
    const instance = renameModal.open({ title: currentTitle ?? '' })
    const result = await instance.result

    if (!result || result === currentTitle) return null

    try {
      await $fetch(`/api/chats/title/${id}`, {
        method: 'PATCH',
        headers: { [headerName]: csrf() },
        body: { title: result }
      })

      updateChat(id, { label: result })

      return result
    } catch {
      toast.add({
        description: 'Failed to rename chat',
        icon: 'i-lucide-alert-circle',
        color: 'error'
      })

      return null
    }
  }

  async function deleteChat(id: string): Promise<boolean> {
    const instance = deleteModal.open()
    const result = await instance.result

    if (!result) return false

    try {
      await $fetch(`/api/chats/${id}`, {
        method: 'DELETE',
        headers: { [headerName]: csrf() }
      })

      toast.add({
        title: 'Chat deleted',
        description: 'Your chat has been deleted',
        icon: 'i-lucide-trash'
      })

      removeChat(id)

      if ((route.params as { id?: string }).id === id) {
        router.push('/')
      }

      return true
    } catch {
      toast.add({
        description: 'Failed to delete chat',
        icon: 'i-lucide-alert-circle',
        color: 'error'
      })

      return false
    }
  }

  async function createTopicForChat(chatId: string) {
    try {
      const topic: any = await $fetch('/api/topics', {
        method: 'POST',
        headers: { [headerName]: csrf() },
        body: { chatId }
      })
      const isGenerating = topic.status === 'generating'
      toast.add({
        title: isGenerating ? 'Generating Topic Space...' : 'Topic Space Created Successfully',
        description: isGenerating
          ? 'AI is synthesizing conversation into topic cognition...'
          : `Topic: ${topic.title}`,
        color: isGenerating ? 'info' : 'success'
      })
      await fetchChats()
      router.push(`/chat/${chatId}`)
      return topic
    } catch (err: any) {
      toast.add({
        title: 'Failed to create Topic Space',
        description: err.message || 'Error creating topic',
        color: 'error'
      })
      return null
    }
  }

  async function addChatToTopic(chatId: string, topicId: string | null) {
    try {
      const updated: any = await $fetch(`/api/chats/topic/${chatId}`, {
        method: 'PATCH',
        headers: { [headerName]: csrf() },
        body: { topicId }
      })
      toast.add({
        title: topicId ? 'Added to Topic' : 'Removed from Topic',
        description: topicId ? 'Chat has been added to the topic' : 'Chat is now standalone',
        color: 'success'
      })
      return updated
    } catch (err: any) {
      toast.add({
        title: 'Failed to update topic',
        description: err.message || 'Error updating topic',
        color: 'error'
      })
      return null
    }
  }

  return {
    renameChat,
    deleteChat,
    createTopicForChat,
    addChatToTopic
  }
}

