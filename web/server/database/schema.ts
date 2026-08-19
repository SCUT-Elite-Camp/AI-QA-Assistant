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

export const knowledgeBases = sqliteTable('knowledge_bases', {
  id: text('id').primaryKey().$defaultFn(() => crypto.randomUUID()),
  name: text('name').notNull().default('My Library'),
  scopeType: text('scope_type', { enum: ['personal', 'enterprise'] }).notNull(),
  ownerUserId: text('owner_user_id'),
  workspaceId: text('workspace_id'),
  createdAt: integer('created_at', { mode: 'timestamp' }).notNull().$defaultFn(() => new Date()),
  updatedAt: integer('updated_at', { mode: 'timestamp' }).notNull().$defaultFn(() => new Date()),
  deletedAt: integer('deleted_at', { mode: 'timestamp' })
}, table => [
  index('knowledge_bases_owner_idx').on(table.ownerUserId, table.scopeType),
])

export const libraryDocuments = sqliteTable('library_documents', {
  id: text('id').primaryKey().$defaultFn(() => crypto.randomUUID()),
  knowledgeBaseId: text('knowledge_base_id').notNull().references(() => knowledgeBases.id),
  ownerUserId: text('owner_user_id').notNull(),
  workspaceId: text('workspace_id'),
  sourceScope: text('source_scope', { enum: ['personal', 'enterprise'] }).notNull(),
  sourceType: text('source_type').notNull().default('upload'),
  filename: text('filename').notNull(),
  displayName: text('display_name').notNull(),
  mimeType: text('mime_type').notNull(),
  docType: text('doc_type').notNull(),
  activeVersionId: text('active_version_id'),
  createdAt: integer('created_at', { mode: 'timestamp' }).notNull().$defaultFn(() => new Date()),
  updatedAt: integer('updated_at', { mode: 'timestamp' }).notNull().$defaultFn(() => new Date()),
  deletedAt: integer('deleted_at', { mode: 'timestamp' })
}, table => [
  index('library_documents_owner_idx').on(table.ownerUserId, table.deletedAt),
  index('library_documents_kb_idx').on(table.knowledgeBaseId, table.deletedAt)
])

export const documentVersions = sqliteTable('document_versions', {
  id: text('id').primaryKey(),
  documentId: text('document_id').notNull().references(() => libraryDocuments.id),
  contentHash: text('content_hash').notNull(),
  storageRef: text('storage_ref').notNull(),
  fileSize: integer('file_size').notNull(),
  status: text('status', { enum: ['UPLOADED', 'PARSING', 'CHUNKING', 'EMBEDDING', 'INDEXING', 'READY', 'FAILED', 'REINDEXING'] }).notNull(),
  errorCode: text('error_code').notNull().default(''),
  errorMessage: text('error_message').notNull().default(''),
  createdAt: integer('created_at', { mode: 'timestamp' }).notNull().$defaultFn(() => new Date()),
  updatedAt: integer('updated_at', { mode: 'timestamp' }).notNull().$defaultFn(() => new Date()),
  indexedAt: integer('indexed_at', { mode: 'timestamp' })
}, table => [
  index('document_versions_document_idx').on(table.documentId, table.createdAt),
  uniqueIndex('document_versions_identity_idx').on(table.documentId, table.contentHash)
])

export const knowledgeBasesRelations = relations(knowledgeBases, ({ many }) => ({
  documents: many(libraryDocuments)
}))

export const libraryDocumentsRelations = relations(libraryDocuments, ({ one, many }) => ({
  knowledgeBase: one(knowledgeBases, { fields: [libraryDocuments.knowledgeBaseId], references: [knowledgeBases.id] }),
  versions: many(documentVersions)
}))

export const documentVersionsRelations = relations(documentVersions, ({ one }) => ({
  document: one(libraryDocuments, { fields: [documentVersions.documentId], references: [libraryDocuments.id] })
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
  documents: many(topicDocuments),
  members: many(topicMembers),
  attachments: many(attachments)
}))

export const topicMembers = sqliteTable('topic_members', {
  topicId: text('topic_id').notNull().references(() => topics.id, { onDelete: 'cascade' }),
  userId: text('user_id').notNull(),
  role: text('role', { enum: ['owner', 'editor', 'viewer'] }).notNull(),
  ...timestamps
}, table => [
  primaryKey({ columns: [table.topicId, table.userId] }),
  index('topic_members_user_idx').on(table.userId)
])

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
  feedbacks: many(messageFeedbacks),
  attachments: many(messageAttachments)
}))

export const attachmentBatches = sqliteTable('attachment_batches', {
  id: text('id').primaryKey(),
  ownerId: text('owner_id').notNull(),
  scope: text('scope', { enum: ['draft', 'chat', 'topic'] }).notNull(),
  chatId: text('chat_id').references(() => chats.id, { onDelete: 'cascade' }),
  topicId: text('topic_id').references(() => topics.id, { onDelete: 'cascade' }),
  fileCount: integer('file_count').notNull().default(0),
  totalBytes: integer('total_bytes').notNull().default(0),
  expiresAt: integer('expires_at', { mode: 'timestamp' }),
  ...timestamps
}, table => [index('attachment_batches_owner_idx').on(table.ownerId)])

export const attachments = sqliteTable('attachments', {
  id: text('id').primaryKey(),
  batchId: text('batch_id').notNull().references(() => attachmentBatches.id, { onDelete: 'cascade' }),
  ownerId: text('owner_id').notNull(),
  scope: text('scope', { enum: ['draft', 'chat', 'topic'] }).notNull(),
  chatId: text('chat_id').references(() => chats.id, { onDelete: 'set null' }),
  topicId: text('topic_id').references(() => topics.id, { onDelete: 'cascade' }),
  filename: text('filename').notNull(),
  mimeType: text('mime_type').notNull(),
  sizeBytes: integer('size_bytes').notNull(),
  sha256: text('sha256').notNull(),
  status: text('status', { enum: ['uploading', 'scanning', 'parsing', 'ready', 'needs_review', 'failed', 'quarantined', 'expired', 'deleted'] }).notNull(),
  visionStatus: text('vision_status', { enum: ['not_requested', 'queued', 'running', 'ready', 'failed'] }).notNull().default('not_requested'),
  evidenceVersion: integer('evidence_version').notNull().default(1),
  errorCode: text('error_code').notNull().default(''),
  expiresAt: integer('expires_at', { mode: 'timestamp' }),
  deletedAt: integer('deleted_at', { mode: 'timestamp' }),
  ...timestamps
}, table => [
  index('attachments_owner_idx').on(table.ownerId),
  index('attachments_topic_idx').on(table.topicId),
  index('attachments_expiry_idx').on(table.expiresAt)
])

export const messageAttachments = sqliteTable('message_attachments', {
  messageId: text('message_id').notNull().references(() => messages.id, { onDelete: 'cascade' }),
  attachmentId: text('attachment_id').notNull().references(() => attachments.id, { onDelete: 'cascade' }),
  evidenceVersion: integer('evidence_version').notNull(),
  ...timestamps
}, table => [
  primaryKey({ columns: [table.messageId, table.attachmentId] }),
  index('message_attachments_attachment_idx').on(table.attachmentId)
])

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

