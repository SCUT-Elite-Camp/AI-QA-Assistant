import { promises as fs } from 'node:fs'
import path from 'node:path'
import crypto from 'node:crypto'

const UPLOAD_DIR = path.resolve('.data', 'uploads')

/** 確保上傳目錄存在 */
async function ensureUploadDir(): Promise<string> {
  await fs.mkdir(UPLOAD_DIR, { recursive: true })
  return UPLOAD_DIR
}

/** 生成唯一的存儲文件路徑 */
function generateStoragePath(originalName: string): string {
  const ext = path.extname(originalName)
  const hash = crypto.randomUUID()
  return path.join(UPLOAD_DIR, `${hash}${ext}`)
}

/** 保存上傳文件到磁盤，返回存儲路徑 */
export async function saveFile(buffer: Buffer, originalName: string): Promise<string> {
  await ensureUploadDir()
  const storagePath = generateStoragePath(originalName)
  await fs.writeFile(storagePath, buffer)
  return storagePath
}

/** 讀取文件內容 */
export async function readFile(storagePath: string): Promise<Buffer> {
  // 安全檢查：確保路徑在 UPLOAD_DIR 內
  const resolved = path.resolve(storagePath)
  if (!resolved.startsWith(path.resolve(UPLOAD_DIR))) {
    throw new Error('Access denied: file path outside upload directory')
  }
  return fs.readFile(resolved)
}

/** 刪除文件 */
export async function deleteFile(storagePath: string): Promise<void> {
  const resolved = path.resolve(storagePath)
  if (!resolved.startsWith(path.resolve(UPLOAD_DIR))) {
    throw new Error('Access denied: file path outside upload directory')
  }
  await fs.unlink(resolved).catch(() => {
    // 文件可能不存在，忽略
  })
}

/** 獲取文件的 MIME type 推斷 */
export function guessMimeType(filename: string): string {
  const ext = path.extname(filename).toLowerCase()
  const mimeMap: Record<string, string> = {
    '.pdf': 'application/pdf',
    '.doc': 'application/msword',
    '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    '.xls': 'application/vnd.ms-excel',
    '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    '.ppt': 'application/vnd.ms-powerpoint',
    '.pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    '.txt': 'text/plain',
    '.csv': 'text/csv',
    '.json': 'application/json',
    '.xml': 'application/xml',
    '.html': 'text/html',
    '.md': 'text/markdown',
    '.png': 'image/png',
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.gif': 'image/gif',
    '.svg': 'image/svg+xml',
    '.webp': 'image/webp',
    '.zip': 'application/zip',
    '.gz': 'application/gzip',
    '.tar': 'application/x-tar',
  }
  return mimeMap[ext] || 'application/octet-stream'
}
