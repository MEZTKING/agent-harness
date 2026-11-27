---
name: Saving data with SQLite
when: Storing an app's data in a SQLite database, or changing its tables.
tags: [database, sql, data]
---
- One small module owns the database: opening it, creating tables, and every query. The rest of the app calls its functions.
- Always use parameters (`?` or `:name`) for values; never build SQL by joining strings with user input.
- Create tables with `CREATE TABLE IF NOT EXISTS`, a primary key, `NOT NULL` where a value must be there, and foreign keys switched on (`PRAGMA foreign_keys = ON`).
- Keep a schema version (`PRAGMA user_version`) and change tables with small numbered steps that run once each.
- Do related writes inside one transaction so a crash never leaves half a change.
- Add an index for a column you search or sort by often.
- Store times as ISO text in UTC (`2026-01-31T12:00:00Z`) and money as whole pennies (integers), not floating point.
- Tests use a database in `tmp_path` (or `:memory:`), never the real one.
