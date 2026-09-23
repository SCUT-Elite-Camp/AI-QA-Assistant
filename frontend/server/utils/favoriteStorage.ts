import fs from 'fs'
import path from 'path'
import { logger } from './logger'

function getFavoritesDir(): string {
  let cwd = process.cwd()
  if (cwd.endsWith('web') || cwd.endsWith('web/')) {
    cwd = path.resolve(cwd, '..')
  }
  const favDir = path.join(cwd, 'data-persistence', 'data', 'favorites')
  if (!fs.existsSync(favDir)) {
    fs.mkdirSync(favDir, { recursive: true })
  }
  return favDir
}

export interface FavoriteEntry {
  chatId: string
  chatTitle: string
  messageId: string
  messageRole: string
  messageText: string
  favoritedAt: string
  suggestionText?: string
}

export interface FavoriteChatRecord {
  chatId: string
  chatTitle: string
  firstFavoritedAt: string
  lastUpdatedAt: string
  messages: FavoriteEntry[]
}

/**
 * Persist a newly favorited message to disk.
 * Creates/updates data-persistence/data/favorites/<chatId>.json
 */
export function saveFavoriteToDisk(entry: FavoriteEntry): void {
  try {
    const favDir = getFavoritesDir()
    const filePath = path.join(favDir, `${entry.chatId}.json`)

    let record: FavoriteChatRecord

    if (fs.existsSync(filePath)) {
      record = JSON.parse(fs.readFileSync(filePath, 'utf-8'))
      // Remove existing entry for same messageId (update scenario)
      record.messages = record.messages.filter(m => m.messageId !== entry.messageId)
      record.messages.push(entry)
      record.lastUpdatedAt = new Date().toISOString()
    } else {
      record = {
        chatId: entry.chatId,
        chatTitle: entry.chatTitle,
        firstFavoritedAt: entry.favoritedAt,
        lastUpdatedAt: entry.favoritedAt,
        messages: [entry]
      }
    }

    fs.writeFileSync(filePath, JSON.stringify(record, null, 2), 'utf-8')
    logger.info(`[FavoriteStorage] Saved favorite message ${entry.messageId} for chat ${entry.chatId}`)
  } catch (err) {
    logger.error(`[FavoriteStorage] Failed to save favorite:`, err)
  }
}

/**
 * Remove a favorited message from disk (when un-favorited).
 * Deletes the chat file if no favorites remain.
 */
export function removeFavoriteFromDisk(chatId: string, messageId: string): void {
  try {
    const favDir = getFavoritesDir()
    const filePath = path.join(favDir, `${chatId}.json`)
    if (!fs.existsSync(filePath)) return

    const record: FavoriteChatRecord = JSON.parse(fs.readFileSync(filePath, 'utf-8'))
    record.messages = record.messages.filter(m => m.messageId !== messageId)

    if (record.messages.length === 0) {
      fs.unlinkSync(filePath)
      logger.info(`[FavoriteStorage] Removed favorite file for chat ${chatId} (no more favorites)`)
    } else {
      record.lastUpdatedAt = new Date().toISOString()
      fs.writeFileSync(filePath, JSON.stringify(record, null, 2), 'utf-8')
      logger.info(`[FavoriteStorage] Removed message ${messageId} from favorites of chat ${chatId}`)
    }
  } catch (err) {
    logger.error(`[FavoriteStorage] Failed to remove favorite:`, err)
  }
}

/**
 * Load all favorite chat records from disk.
 * Returns sorted by lastUpdatedAt descending.
 */
export function loadAllFavoritesFromDisk(): FavoriteChatRecord[] {
  try {
    const favDir = getFavoritesDir()
    const files = fs.readdirSync(favDir).filter(f => f.endsWith('.json'))
    const records: FavoriteChatRecord[] = []

    for (const file of files) {
      try {
        const raw = fs.readFileSync(path.join(favDir, file), 'utf-8')
        records.push(JSON.parse(raw))
      } catch (e) {
        // skip malformed files
      }
    }

    return records.sort((a, b) =>
      new Date(b.lastUpdatedAt).getTime() - new Date(a.lastUpdatedAt).getTime()
    )
  } catch (err) {
    logger.error(`[FavoriteStorage] Failed to load favorites from disk:`, err)
    return []
  }
}

/**
 * Load a single chat's favorite record from disk.
 */
export function loadChatFavoritesFromDisk(chatId: string): FavoriteChatRecord | null {
  try {
    const favDir = getFavoritesDir()
    const filePath = path.join(favDir, `${chatId}.json`)
    if (!fs.existsSync(filePath)) return null
    return JSON.parse(fs.readFileSync(filePath, 'utf-8'))
  } catch (err) {
    logger.error(`[FavoriteStorage] Failed to load favorites for chat ${chatId}:`, err)
    return null
  }
}
