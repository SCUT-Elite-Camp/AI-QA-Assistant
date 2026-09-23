CREATE TABLE IF NOT EXISTS `message_feedbacks` (
	`id` text PRIMARY KEY NOT NULL,
	`chat_id` text NOT NULL,
	`message_id` text NOT NULL,
	`is_favorite` integer DEFAULT false NOT NULL,
	`suggestion_text` text,
	`created_at` integer NOT NULL,
	FOREIGN KEY (`chat_id`) REFERENCES `chats`(`id`) ON UPDATE no action ON DELETE cascade,
	FOREIGN KEY (`message_id`) REFERENCES `messages`(`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE INDEX IF NOT EXISTS `msg_feedbacks_chat_id_idx` ON `message_feedbacks` (`chat_id`);--> statement-breakpoint
CREATE INDEX IF NOT EXISTS `msg_feedbacks_msg_id_idx` ON `message_feedbacks` (`message_id`);--> statement-breakpoint
CREATE TABLE IF NOT EXISTS `topic_documents` (
	`id` text PRIMARY KEY NOT NULL,
	`topic_id` text NOT NULL,
	`doc_id` text NOT NULL,
	`title` text NOT NULL,
	`source_url` text,
	`snippet` text,
	`recall_count` integer DEFAULT 1 NOT NULL,
	`last_recalled_at` integer NOT NULL,
	`score` integer,
	`is_removed` integer DEFAULT false NOT NULL,
	`created_at` integer NOT NULL,
	FOREIGN KEY (`topic_id`) REFERENCES `topics`(`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE INDEX IF NOT EXISTS `topic_docs_topic_id_idx` ON `topic_documents` (`topic_id`);--> statement-breakpoint
CREATE UNIQUE INDEX IF NOT EXISTS `topic_doc_idx` ON `topic_documents` (`topic_id`,`doc_id`);--> statement-breakpoint
CREATE TABLE IF NOT EXISTS `topics` (
	`id` text PRIMARY KEY NOT NULL,
	`title` text NOT NULL,
	`main_chat_id` text NOT NULL,
	`soul_content` text DEFAULT '' NOT NULL,
	`description` text,
	`weight_mode` text DEFAULT 'auto' NOT NULL,
	`tags` text,
	`status` text DEFAULT 'ready' NOT NULL,
	`consecutive_no_new_docs_count` integer DEFAULT 0 NOT NULL,
	`created_at` integer NOT NULL
);
--> statement-breakpoint
ALTER TABLE `chats` ADD `topic_id` text REFERENCES topics(id);--> statement-breakpoint
ALTER TABLE `chats` ADD `is_branch` integer DEFAULT false NOT NULL;--> statement-breakpoint
ALTER TABLE `chats` ADD `parent_chat_id` text;--> statement-breakpoint
ALTER TABLE `chats` ADD `parent_message_id` text;--> statement-breakpoint
CREATE INDEX IF NOT EXISTS `chats_topic_id_idx` ON `chats` (`topic_id`);--> statement-breakpoint
ALTER TABLE `messages` ADD `is_favorite` integer DEFAULT false NOT NULL;--> statement-breakpoint
ALTER TABLE `messages` ADD `suggestion_text` text;
