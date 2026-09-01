ALTER TABLE `chats` ADD `history_revision` integer DEFAULT 1 NOT NULL;--> statement-breakpoint
ALTER TABLE `chats` ADD `next_message_sequence` integer DEFAULT 1 NOT NULL;--> statement-breakpoint
PRAGMA foreign_keys=OFF;--> statement-breakpoint
CREATE TABLE `__new_messages` (
	`id` text PRIMARY KEY NOT NULL,
	`chat_id` text NOT NULL,
	`role` text NOT NULL,
	`parts` text,
	`sequence` integer NOT NULL,
	`history_revision` integer DEFAULT 1 NOT NULL,
	`request_id` text,
	`is_favorite` integer DEFAULT false NOT NULL,
	`suggestion_text` text,
	`created_at` integer NOT NULL,
	FOREIGN KEY (`chat_id`) REFERENCES `chats`(`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
INSERT INTO `__new_messages` (`id`, `chat_id`, `role`, `parts`, `sequence`, `history_revision`, `request_id`, `is_favorite`, `suggestion_text`, `created_at`)
SELECT `id`, `chat_id`, `role`, `parts`,
	ROW_NUMBER() OVER (PARTITION BY `chat_id` ORDER BY `created_at` ASC, `id` ASC),
	1,
	NULL,
	`is_favorite`,
	`suggestion_text`,
	`created_at`
FROM `messages`;
--> statement-breakpoint
DROP TABLE `messages`;--> statement-breakpoint
ALTER TABLE `__new_messages` RENAME TO `messages`;--> statement-breakpoint
CREATE INDEX `messages_chat_id_idx` ON `messages` (`chat_id`);--> statement-breakpoint
CREATE UNIQUE INDEX `messages_chat_sequence_idx` ON `messages` (`chat_id`,`sequence`);--> statement-breakpoint
CREATE UNIQUE INDEX `messages_chat_request_role_idx` ON `messages` (`chat_id`,`request_id`,`role`) WHERE "messages"."request_id" IS NOT NULL;--> statement-breakpoint
UPDATE `chats`
SET `history_revision` = 1,
	`next_message_sequence` = COALESCE(
		(SELECT MAX(`sequence`) + 1 FROM `messages` WHERE `messages`.`chat_id` = `chats`.`id`),
		1
	);--> statement-breakpoint
PRAGMA foreign_keys=ON;
