ALTER TABLE `chats`
ADD COLUMN `weight_mode` text NOT NULL DEFAULT 'fast';
--> statement-breakpoint
UPDATE `chats`
SET `weight_mode` = COALESCE((
  SELECT CASE `topics`.`weight_mode`
    WHEN 'wider' THEN 'fast'
    WHEN 'deeper' THEN 'thinking'
    WHEN 'auto' THEN 'auto'
    WHEN 'thinking' THEN 'thinking'
    WHEN 'fast' THEN 'fast'
    ELSE 'fast'
  END
  FROM `topics`
  WHERE `topics`.`id` = `chats`.`topic_id`
), `weight_mode`)
WHERE `topic_id` IS NOT NULL;
--> statement-breakpoint
ALTER TABLE `topics` DROP COLUMN `weight_mode`;
