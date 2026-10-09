-- Tables used by development login, settings, and document access were absent
-- from the generated migrations. IF NOT EXISTS preserves existing local data.
CREATE TABLE IF NOT EXISTS departments (id TEXT PRIMARY KEY NOT NULL, name TEXT NOT NULL UNIQUE, parent_id TEXT, created_at INTEGER NOT NULL);
--> statement-breakpoint
CREATE INDEX IF NOT EXISTS departments_parent_id_idx ON departments(parent_id);
--> statement-breakpoint
CREATE TABLE IF NOT EXISTS user_departments (user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE, department_id TEXT NOT NULL REFERENCES departments(id) ON DELETE CASCADE, PRIMARY KEY(user_id,department_id));
--> statement-breakpoint
CREATE INDEX IF NOT EXISTS user_departments_user_idx ON user_departments(user_id);
--> statement-breakpoint
CREATE INDEX IF NOT EXISTS user_departments_dept_idx ON user_departments(department_id);
--> statement-breakpoint
CREATE TABLE IF NOT EXISTS user_settings (id TEXT PRIMARY KEY NOT NULL, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE, theme TEXT NOT NULL DEFAULT 'system', primary_color TEXT NOT NULL DEFAULT 'blue', neutral_color TEXT NOT NULL DEFAULT 'zinc', language TEXT NOT NULL DEFAULT 'zh-CN', notifications_enabled INTEGER NOT NULL DEFAULT 1, auto_save_chats INTEGER NOT NULL DEFAULT 1, font_size TEXT NOT NULL DEFAULT 'medium', updated_at INTEGER NOT NULL, created_at INTEGER NOT NULL);
--> statement-breakpoint
CREATE UNIQUE INDEX IF NOT EXISTS user_settings_user_id_idx ON user_settings(user_id);
--> statement-breakpoint
CREATE TABLE IF NOT EXISTS files (id TEXT PRIMARY KEY NOT NULL, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE, name TEXT NOT NULL, original_name TEXT NOT NULL, mime_type TEXT NOT NULL, size INTEGER NOT NULL, storage_path TEXT NOT NULL, visibility TEXT NOT NULL DEFAULT 'private', doc_id TEXT, created_at INTEGER NOT NULL);
--> statement-breakpoint
CREATE INDEX IF NOT EXISTS files_user_id_idx ON files(user_id);
--> statement-breakpoint
CREATE INDEX IF NOT EXISTS files_visibility_idx ON files(visibility);
--> statement-breakpoint
CREATE UNIQUE INDEX IF NOT EXISTS files_doc_id_idx ON files(doc_id);
--> statement-breakpoint
CREATE TABLE IF NOT EXISTS file_permissions (id TEXT PRIMARY KEY NOT NULL, file_id TEXT NOT NULL REFERENCES files(id) ON DELETE CASCADE, grant_type TEXT NOT NULL, grant_id TEXT, created_at INTEGER NOT NULL);
--> statement-breakpoint
CREATE INDEX IF NOT EXISTS file_permissions_file_idx ON file_permissions(file_id);
--> statement-breakpoint
CREATE INDEX IF NOT EXISTS file_permissions_grant_idx ON file_permissions(grant_type,grant_id);
--> statement-breakpoint
CREATE TABLE IF NOT EXISTS audit_logs (id TEXT PRIMARY KEY NOT NULL, user_id TEXT, action TEXT NOT NULL, resource_type TEXT NOT NULL, resource_id TEXT, detail TEXT, ip TEXT, user_agent TEXT, created_at INTEGER NOT NULL);
--> statement-breakpoint
CREATE INDEX IF NOT EXISTS audit_logs_user_id_idx ON audit_logs(user_id);
--> statement-breakpoint
CREATE INDEX IF NOT EXISTS audit_logs_action_idx ON audit_logs(action);
--> statement-breakpoint
CREATE INDEX IF NOT EXISTS audit_logs_created_at_idx ON audit_logs(created_at);
