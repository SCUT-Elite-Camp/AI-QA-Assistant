CREATE TABLE `topics` (
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
ALTER TABLE `chats` ADD `visibility` text DEFAULT 'private' NOT NULL;
