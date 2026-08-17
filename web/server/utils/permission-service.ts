import crypto from 'node:crypto'
import path from 'node:path'
import { useDrizzle, tables, eq, and, or, inArray } from './drizzle'

export type FileGrant = {
  grantType: 'user' | 'department' | 'public'
  grantId: string | null
}

type Db = ReturnType<typeof useDrizzle>

/**
 * 计算文件对应的 Milvus doc_id。
 * 与 data-pipeline 的 `Document.generate_doc_id` 保持一致：MD5(文件绝对路径)。
 */
export function computeDocId(storagePath: string): string {
  const absPath = path.resolve(storagePath)
  return crypto.createHash('md5').update(absPath).digest('hex')
}

/**
 * 获取用户所属部门 ID 列表。
 */
export async function getUserDepartmentIds(db: Db, userId: string): Promise<string[]> {
  const rows = await db
    .select({ departmentId: tables.userDepartments.departmentId })
    .from(tables.userDepartments)
    .where(eq(tables.userDepartments.userId, userId))
  return rows.map(r => r.departmentId)
}

/**
 * 获取用户通过授权记录（public / 显式用户 / 部门）可访问的文件 ID 列表。
 */
export async function getGrantedFileIds(db: Db, userId: string): Promise<string[]> {
  const deptIds = await getUserDepartmentIds(db, userId)

  const conditions = [
    eq(tables.filePermissions.grantType, 'public'),
    and(
      eq(tables.filePermissions.grantType, 'user'),
      eq(tables.filePermissions.grantId, userId),
    ),
  ]
  if (deptIds.length > 0) {
    conditions.push(
      and(
        eq(tables.filePermissions.grantType, 'department'),
        inArray(tables.filePermissions.grantId, deptIds),
      ),
    )
  }

  const rows = await db
    .select({ fileId: tables.filePermissions.fileId })
    .from(tables.filePermissions)
    .where(or(...conditions))

  return rows.map(r => r.fileId)
}

/**
 * 获取某个文件的权限授权记录。
 */
export async function getFileGrants(db: Db, fileId: string) {
  return db
    .select()
    .from(tables.filePermissions)
    .where(eq(tables.filePermissions.fileId, fileId))
}

/**
 * 整体替换某个文件的权限授权记录（先删后插，保证幂等）。
 */
export async function replaceFileGrants(
  db: Db,
  fileId: string,
  grants: FileGrant[],
): Promise<void> {
  await db.delete(tables.filePermissions).where(eq(tables.filePermissions.fileId, fileId))

  if (grants.length > 0) {
    await db.insert(tables.filePermissions).values(
      grants.map(g => ({
        fileId,
        grantType: g.grantType,
        grantId: g.grantId,
      })),
    )
  }
}

/**
 * 判断用户是否有权限访问某个文件。
 * 规则与 Agent 层 PermissionService 保持一致：
 *   owner / shared / public / 显式用户授权 / 部门授权。
 */
export async function canAccessFile(db: Db, userId: string | undefined, fileId: string): Promise<boolean> {
  const [file] = await db.select().from(tables.files).where(eq(tables.files.id, fileId))
  if (!file) return false

  if (file.userId === userId) return true
  if (file.visibility === 'shared') return true
  if (!userId) return false

  const grants = await getFileGrants(db, fileId)
  for (const g of grants) {
    if (g.grantType === 'public') return true
    if (g.grantType === 'user' && g.grantId === userId) return true
    if (g.grantType === 'department' && g.grantId) {
      const deptIds = await getUserDepartmentIds(db, userId)
      if (deptIds.includes(g.grantId)) return true
    }
  }

  return false
}
