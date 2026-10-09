ALTER TABLE memory_snapshots ADD COLUMN evidence_provenance text;
--> statement-breakpoint
ALTER TABLE memory_facts ADD COLUMN evidence_provenance text;
--> statement-breakpoint
ALTER TABLE topics ADD COLUMN evidence_provenance text;
--> statement-breakpoint
ALTER TABLE chats ADD COLUMN evidence_provenance text;
