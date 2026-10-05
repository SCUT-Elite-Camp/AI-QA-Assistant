import { createSharedComposable } from '@vueuse/core'
import { ref, computed } from 'vue'
import { $fetch } from 'ofetch'
import { useCsrf } from './useCsrf'
import { useUserSession } from './useUserSession'

export interface AdminUser {
  id: string
  email: string
  name: string
  username: string
  avatar: string | null
  provider: 'github' | 'sso'
  role: 'admin' | 'user'
  ssoId: string | null
  disabled: boolean
  departmentIds: string[]
  createdAt: string
  updatedAt: string
}

export interface Department {
  id: string
  name: string
  parentId: string | null
  userCount: number
  createdAt: string
}

export interface GrantInput {
  grantType: 'user' | 'department' | 'public'
  grantId: string | null
}

export interface PermissionItem {
  fileId: string
  name: string
  ownerId: string
  visibility: 'private' | 'shared'
  docId: string | null
  grants: Array<{ grantType: string; grantId: string | null }>
}

/**
 * 管理后台 API 封装（用户 / 部门 / 文件权限）。
 * 所有请求自动携带 CSRF 头，接口本身有 requireAdmin 保护。
 */
export const useAdmin = createSharedComposable(() => {
  const { csrf, headerName } = useCsrf()

  // ---------- 用户管理 ----------
  const listUsers = async (): Promise<AdminUser[]> => {
    return $fetch<AdminUser[]>('/api/admin/users')
  }

  const createUser = async (payload: {
    email: string
    name: string
    username: string
    avatar?: string
    role: 'admin' | 'user'
    ssoId?: string
    departmentIds: string[]
  }) => {
    return $fetch('/api/admin/users', {
      method: 'POST',
      headers: { [headerName]: csrf() },
      body: payload,
    })
  }

  const updateUser = async (id: string, payload: Partial<AdminUser> & { departmentIds?: string[] }) => {
    return $fetch(`/api/admin/users/${id}`, {
      method: 'PATCH',
      headers: { [headerName]: csrf() },
      body: payload,
    })
  }

  // ---------- 部门管理 ----------
  const listDepartments = async (): Promise<Department[]> => {
    return $fetch<Department[]>('/api/admin/departments')
  }

  const createDepartment = async (payload: { name: string; parentId?: string | null }) => {
    return $fetch('/api/admin/departments', {
      method: 'POST',
      headers: { [headerName]: csrf() },
      body: payload,
    })
  }

  const updateDepartment = async (id: string, payload: { name?: string; parentId?: string | null }) => {
    return $fetch(`/api/admin/departments/${id}`, {
      method: 'PATCH',
      headers: { [headerName]: csrf() },
      body: payload,
    })
  }

  const deleteDepartment = async (id: string) => {
    return $fetch(`/api/admin/departments/${id}`, {
      method: 'DELETE',
      headers: { [headerName]: csrf() },
    })
  }

  // ---------- 文件权限 ----------
  const listPermissions = async (): Promise<PermissionItem[]> => {
    return $fetch<PermissionItem[]>('/api/admin/permissions')
  }

  /** 权限选择器下拉选项（用户 + 部门），登录用户可用 */
  const fetchPermissionOptions = async (): Promise<{
    users: Array<{ id: string; name: string; username: string }>
    departments: Array<{ id: string; name: string }>
  }> => {
    return $fetch('/api/permission-options')
  }

  const updateFilePermission = async (fileId: string, payload: {
    visibility?: 'private' | 'shared'
    grants?: GrantInput[]
  }) => {
    return $fetch(`/api/files/${fileId}`, {
      method: 'PATCH',
      headers: { [headerName]: csrf() },
      body: payload,
    })
  }

  return {
    listUsers,
    createUser,
    updateUser,
    listDepartments,
    createDepartment,
    updateDepartment,
    deleteDepartment,
    listPermissions,
    updateFilePermission,
    fetchPermissionOptions,
  }
})

/** 管理员访问守卫：刷新 session 后判断当前用户是否为 admin */
export function useAdminAccess() {
  const { user, fetchSession } = useUserSession()
  const checking = ref(true)
  const allowed = computed(() => Boolean(user.value && user.value.role === 'admin'))

  const check = async () => {
    checking.value = true
    await fetchSession()
    checking.value = false
  }

  return { checking, allowed, check }
}
