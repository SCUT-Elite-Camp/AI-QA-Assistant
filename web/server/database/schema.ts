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

export const topics = sqliteTable('topics', {
  id: text('id').primaryKey().$defaultFn(() => crypto.randomUUID()),
  title: text('title').notNull(),
  mainChatId: text('main_chat_id').notNull(),
  soulContent: text('soul_content').notNull().default(''),
  description: text('description'),
  weightMode: text('weight_mode', { enum: ['deeper', 'auto', 'wider'] }).notNull().default('auto'),
  tags: text('tags', { mode: 'json' }),
  status: text('status', { enum: ['generating', 'ready'] }).notNull().default('ready'),
  consecutiveNoNewDocsCount: integer('consecutive_no_new_docs_count').notNull().default(0),
  ...timestamps
})

export const topicsRelations = relations(topics, ({ many }) => ({
  chats: many(chats),
  documents: many(topicDocuments)
}))

export const chats = sqliteTable('chats', {
  id: text('id').primaryKey().$defaultFn(() => crypto.randomUUID()),
  title: text('title'),
  userId: text('user_id').notNull(),
  visibility: text('visibility', { enum: ['public', 'private'] }).notNull().default('private'),
  topicId: text('topic_id').references(() => topics.id, { onDelete: 'set null' }),
  isBranch: integer('is_branch', { mode: 'boolean' }).notNull().default(false),
  parentChatId: text('parent_chat_id'),
  parentMessageId: text('parent_message_id'),
  ...timestamps
}, table => [
  index('chats_user_id_idx').on(table.userId),
  index('chats_topic_id_idx').on(table.topicId)
])

export const chatsRelations = relations(chats, ({ one, many }) => ({
  user: one(users, {
    fields: [chats.userId],
    references: [users.id]
  }),
  topic: one(topics, {
    fields: [chats.topicId],
    references: [topics.id]
  }),
  messages: many(messages)
}))

export const topicDocuments = sqliteTable('topic_documents', {
  id: text('id').primaryKey().$defaultFn(() => crypto.randomUUID()),
  topicId: text('topic_id').notNull().references(() => topics.id, { onDelete: 'cascade' }),
  docId: text('doc_id').notNull(),
  title: text('title').notNull(),
  sourceUrl: text('source_url'),
  snippet: text('snippet'),
  recallCount: integer('recall_count').notNull().default(1),
  lastRecalledAt: integer('last_recalled_at', { mode: 'timestamp' }).notNull().$defaultFn(() => new Date()),
  score: integer('score'),
  isRemoved: integer('is_removed', { mode: 'boolean' }).notNull().default(false),
  isUserUploaded: integer('is_user_uploaded', { mode: 'boolean' }).notNull().default(false),
  ...timestamps
}, table => [
  index('topic_docs_topic_id_idx').on(table.topicId),
  uniqueIndex('topic_doc_idx').on(table.topicId, table.docId)
])

export const topicDocumentsRelations = relations(topicDocuments, ({ one }) => ({
  topic: one(topics, {
    fields: [topicDocuments.topicId],
    references: [topics.id]
  })
}))

export const messages = sqliteTable('messages', {
  id: text('id').primaryKey().$defaultFn(() => crypto.randomUUID()),
  chatId: text('chat_id').notNull().references(() => chats.id, { onDelete: 'cascade' }),
  role: text('role', { enum: ['user', 'assistant', 'system'] }).notNull(),
  parts: text('parts', { mode: 'json' }),
  isFavorite: integer('is_favorite', { mode: 'boolean' }).notNull().default(false),
  suggestionText: text('suggestion_text'),
  ...timestamps
}, table => [
  index('messages_chat_id_idx').on(table.chatId)
])

export const messagesRelations = relations(messages, ({ one, many }) => ({
  chat: one(chats, {
    fields: [messages.chatId],
    references: [chats.id]
  }),
  feedbacks: many(messageFeedbacks)
}))

export const messageFeedbacks = sqliteTable('message_feedbacks', {
  id: text('id').primaryKey().$defaultFn(() => crypto.randomUUID()),
  chatId: text('chat_id').notNull().references(() => chats.id, { onDelete: 'cascade' }),
  messageId: text('message_id').notNull().references(() => messages.id, { onDelete: 'cascade' }),
  isFavorite: integer('is_favorite', { mode: 'boolean' }).notNull().default(false),
  suggestionText: text('suggestion_text'),
  ...timestamps
}, table => [
  index('msg_feedbacks_chat_id_idx').on(table.chatId),
  index('msg_feedbacks_msg_id_idx').on(table.messageId)
])

export const messageFeedbacksRelations = relations(messageFeedbacks, ({ one }) => ({
  chat: one(chats, {
    fields: [messageFeedbacks.chatId],
    references: [chats.id]
  }),
  message: one(messages, {
    fields: [messageFeedbacks.messageId],
    references: [messages.id]
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

