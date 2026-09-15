CREATE TABLE `demo_budget` (
	`id` text PRIMARY KEY NOT NULL,
	`spent` real DEFAULT 0 NOT NULL,
	`reserved` real DEFAULT 0 NOT NULL
);
--> statement-breakpoint
CREATE TABLE `demo_sessions` (
	`id` text PRIMARY KEY NOT NULL,
	`payload` text NOT NULL,
	`busy` integer DEFAULT 0 NOT NULL
);
