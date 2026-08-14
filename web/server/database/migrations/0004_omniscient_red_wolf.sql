ALTER TABLE `chats` ADD `history_revision` integer DEFAULT 1 NOT NULL;--> statement-breakpoint
ALTER TABLE `chats` ADD `next_message_sequence` integer DEFAULT 1 NOT NULL;--> statement-breakpoint
ALTER TABLE `messages` ADD `sequence` integer NOT NULL;--> statement-breakpoint
ALTER TABLE `messages` ADD `history_revision` integer NOT NULL;--> statement-breakpoint
ALTER TABLE `messages` ADD `request_id` text;--> statement-breakpoint
CREATE UNIQUE INDEX `messages_chat_sequence_idx` ON `messages` (`chat_id`,`sequence`);--> statement-breakpoint
CREATE UNIQUE INDEX `messages_chat_request_role_idx` ON `messages` (`chat_id`,`request_id`,`role`) WHERE "messages"."request_id" IS NOT NULL;