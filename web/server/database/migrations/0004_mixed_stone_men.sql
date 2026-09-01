CREATE TABLE `departments` (
	`id` text PRIMARY KEY NOT NULL,
	`name` text NOT NULL,
	`parent_id` text,
	`created_at` integer NOT NULL
);
--> statement-breakpoint
CREATE UNIQUE INDEX `departments_name_unique` ON `departments` (`name`);--> statement-breakpoint
CREATE INDEX `departments_parent_id_idx` ON `departments` (`parent_id`);--> statement-breakpoint
CREATE TABLE `file_permissions` (
	`id` text PRIMARY KEY NOT NULL,
	`file_id` text NOT NULL,
	`grant_type` text NOT NULL,
	`grant_id` text,
	`created_at` integer NOT NULL,
	FOREIGN KEY (`file_id`) REFERENCES `files`(`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE INDEX `file_permissions_file_idx` ON `file_permissions` (`file_id`);--> statement-breakpoint
CREATE INDEX `file_permissions_grant_idx` ON `file_permissions` (`grant_type`,`grant_id`);--> statement-breakpoint
CREATE TABLE `user_departments` (
	`user_id` text NOT NULL,
	`department_id` text NOT NULL,
	PRIMARY KEY(`user_id`, `department_id`),
	FOREIGN KEY (`user_id`) REFERENCES `users`(`id`) ON UPDATE no action ON DELETE cascade,
	FOREIGN KEY (`department_id`) REFERENCES `departments`(`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE INDEX `user_departments_user_idx` ON `user_departments` (`user_id`);--> statement-breakpoint
CREATE INDEX `user_departments_dept_idx` ON `user_departments` (`department_id`);--> statement-breakpoint
ALTER TABLE `files` ADD `doc_id` text;--> statement-breakpoint
CREATE UNIQUE INDEX `files_doc_id_idx` ON `files` (`doc_id`);--> statement-breakpoint
ALTER TABLE `users` ADD `role` text DEFAULT 'user' NOT NULL;--> statement-breakpoint
ALTER TABLE `users` ADD `sso_id` text;--> statement-breakpoint
CREATE UNIQUE INDEX `users_sso_id_idx` ON `users` (`sso_id`);