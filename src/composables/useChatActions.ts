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
  const { updateChat, removeChat } = useChats()

  const renameModal = overlay.create(ModalRename)
  const deleteModal = overlay.create(ModalConfirm, {
    props: {
      title: '删除对话',
      description: '确定要删除该对话？此操作无法撤销。',
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
        description: '重命名对话失败',
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
        title: '对话已删除',
        description: '您的对话已删除',
        icon: 'i-lucide-trash'
      })

      removeChat(id)

      if ((route.params as { id?: string }).id === id) {
        router.push('/')
      }

      return true
    } catch {
      toast.add({
        description: '删除对话失败',
        icon: 'i-lucide-alert-circle',
        color: 'error'
      })

      return false
    }
  }

  return {
    renameChat,
    deleteChat
  }
}
