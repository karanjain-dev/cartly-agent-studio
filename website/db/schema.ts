import {sqliteTable,text,integer,real} from 'drizzle-orm/sqlite-core';
export const sessions=sqliteTable('demo_sessions',{id:text('id').primaryKey(),payload:text('payload').notNull(),busy:integer('busy').notNull().default(0)});
export const budget=sqliteTable('demo_budget',{id:text('id').primaryKey(),spent:real('spent').notNull().default(0),reserved:real('reserved').notNull().default(0)});
