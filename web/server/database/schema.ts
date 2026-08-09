import { sqliteTable, text, integer, index, uniqueIndex, primaryKey } from 'drizzle-orm/sqlite-core'
import { relations } from 'drizzle-orm'

const timestamps = {
  createdAt: integer('created_at', { mode: 'timestamp' }).notNull().$defaultFn(() => new Date())
}

export const users = sqliteTable('users', {
  id: text('id').primaryKey().$defaultFn(() => crypto.randomUUID()),
  email: text('email').notNull(),
  name: text('name').notNull(),
  avatar: text('avatar').notNull(),
  username: text('username').notNull(),
  provider: text('provider', { enum: ['github'] }).notNull(),
  providerId: text('provider_id').notNull(),
  ...timestamps
}, table => [
  uniqueIndex('users_provider_id_idx').on(table.provider, table.providerId)
])

export const usersRelations = relations(users, ({ many }) => ({
  chats: many(chats)
}))

export const chats = sqliteTable('chats', {
  id: text('id').primaryKey().$defaultFn(() => crypto.randomUUID()),
  title: text('title'),
  userId: text('user_id').notNull(),
  visibility: text('visibility', { enum: ['public', 'private'] }).notNull().default('private'),
  ...timestamps
}, table => [
  index('chats_user_id_idx').on(table.userId)
])

export const chatsRelations = relations(chats, ({ one, many }) => ({
  user: one(users, {
    fields: [chats.userId],
    references: [users.id]
  }),
  messages: many(messages)
}))

export const messages = sqliteTable('messages', {
  id: text('id').primaryKey().$defaultFn(() => crypto.randomUUID()),
  chatId: text('chat_id').notNull().references(() => chats.id, { onDelete: 'cascade' }),
  role: text('role', { enum: ['user', 'assistant', 'system'] }).notNull(),
  parts: text('parts', { mode: 'json' }),
  ...timestamps
}, table => [
  index('messages_chat_id_idx').on(table.chatId)
])

export const messagesRelations = relations(messages, ({ one }) => ({
  chat: one(chats, {
    fields: [messages.chatId],
    references: [chats.id]
  })
}))

export const votes = sqliteTable('votes', {
  chatId: text('chat_id').notNull().references(() => chats.id, { onDelete: 'cascade' }),
  messageId: text('message_id').notNull().references(() => messages.id, { onDelete: 'cascade' }),
  isUpvoted: integer('is_upvoted', { mode: 'boolean' }).notNull()
}, table => [
  primaryKey({ columns: [table.chatId, table.messageId] })
])

export const votesRelations = relations(votes, ({ one }) => ({
  chat: one(chats, {
    fields: [votes.chatId],
    references: [chats.id]
  }),
  message: one(messages, {
    fields: [votes.messageId],
    references: [messages.id]
  })
}))

// ==================== 用户设置 ====================

export const userSettings = sqliteTable('user_settings', {
  id: text('id').primaryKey().$defaultFn(() => crypto.randomUUID()),
  userId: text('user_id').notNull().references(() => users.id, { onDelete: 'cascade' }),
  theme: text('theme', { enum: ['light', 'dark', 'system'] }).notNull().default('system'),
  primaryColor: text('primary_color').notNull().default('blue'),
  neutralColor: text('neutral_color').notNull().default('zinc'),
  language: text('language', { enum: ['zh-CN', 'en-US'] }).notNull().default('zh-CN'),
  notificationsEnabled: integer('notifications_enabled', { mode: 'boolean' }).notNull().default(true),
  autoSaveChats: integer('auto_save_chats', { mode: 'boolean' }).notNull().default(true),
  fontSize: text('font_size', { enum: ['small', 'medium', 'large'] }).notNull().default('medium'),
  updatedAt: integer('updated_at', { mode: 'timestamp' }).notNull().$defaultFn(() => new Date()),
  ...timestamps
}, table => [
  uniqueIndex('user_settings_user_id_idx').on(table.userId)
])

// ==================== 文件管理 ====================

export const files = sqliteTable('files', {
  id: text('id').primaryKey().$defaultFn(() => crypto.randomUUID()),
  userId: text('user_id').notNull().references(() => users.id, { onDelete: 'cascade' }),
  name: text('name').notNull(),
  originalName: text('original_name').notNull(),
  mimeType: text('mime_type').notNull(),
  size: integer('size').notNull(), // bytes
  storagePath: text('storage_path').notNull(),
  visibility: text('visibility', { enum: ['private', 'shared'] }).notNull().default('private'),
  ...timestamps
}, table => [
  index('files_user_id_idx').on(table.userId),
  index('files_visibility_idx').on(table.visibility)
])

// ==================== 审计日志 ====================

export const auditLogs = sqliteTable('audit_logs', {
  id: text('id').primaryKey().$defaultFn(() => crypto.randomUUID()),
  userId: text('user_id'),
  action: text('action').notNull(), // e.g. 'file.view', 'file.download', 'file.delete'
  resourceType: text('resource_type').notNull(), // e.g. 'file', 'chat'
  resourceId: text('resource_id'),
  detail: text('detail', { mode: 'json' }), // JSON: extra context
  ip: text('ip'),
  userAgent: text('user_agent'),
  ...timestamps
}, table => [
  index('audit_logs_user_id_idx').on(table.userId),
  index('audit_logs_action_idx').on(table.action),
  index('audit_logs_created_at_idx').on(table.createdAt)
])

// ==================== Relations ====================

export const userSettingsRelations = relations(userSettings, ({ one }) => ({
  user: one(users, {
    fields: [userSettings.userId],
    references: [users.id]
  })
}))

export const filesRelations = relations(files, ({ one }) => ({
  user: one(users, {
    fields: [files.userId],
    references: [users.id]
  })
}))

export const auditLogsRelations = relations(auditLogs, ({ one }) => ({
  user: one(users, {
    fields: [auditLogs.userId],
    references: [users.id]
  })
}))
