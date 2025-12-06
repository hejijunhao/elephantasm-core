-- Database Flush Script (Raw SQL)
--
-- Deletes all user data while preserving:
-- - User accounts (auth.users, public.users)
-- - RLS policies
-- - Database schema and configurations
--
-- Usage (via psql):
--   psql $DATABASE_URL -f scripts/database/flush_database.sql
--
-- Usage (via Supabase SQL Editor):
--   Copy and paste this file content

BEGIN;

-- Display counts before deletion
SELECT 'BEFORE DELETION:' as status;
SELECT 'knowledge_audit_log' as table_name, COUNT(*) as record_count FROM knowledge_audit_log
UNION ALL
SELECT 'knowledge', COUNT(*) FROM knowledge
UNION ALL
SELECT 'memories_events', COUNT(*) FROM memories_events
UNION ALL
SELECT 'memories', COUNT(*) FROM memories
UNION ALL
SELECT 'events', COUNT(*) FROM events
UNION ALL
SELECT 'synthesis_configs', COUNT(*) FROM synthesis_configs
UNION ALL
SELECT 'animas', COUNT(*) FROM animas
UNION ALL
SELECT 'users (preserved)', COUNT(*) FROM users;

-- Delete in order (respects foreign key constraints)
DELETE FROM knowledge_audit_log;
DELETE FROM knowledge;
DELETE FROM memories_events;
DELETE FROM memories;
DELETE FROM events;
DELETE FROM synthesis_configs;
DELETE FROM animas;

-- Display counts after deletion
SELECT 'AFTER DELETION:' as status;
SELECT 'knowledge_audit_log' as table_name, COUNT(*) as record_count FROM knowledge_audit_log
UNION ALL
SELECT 'knowledge', COUNT(*) FROM knowledge
UNION ALL
SELECT 'memories_events', COUNT(*) FROM memories_events
UNION ALL
SELECT 'memories', COUNT(*) FROM memories
UNION ALL
SELECT 'events', COUNT(*) FROM events
UNION ALL
SELECT 'synthesis_configs', COUNT(*) FROM synthesis_configs
UNION ALL
SELECT 'animas', COUNT(*) FROM animas
UNION ALL
SELECT 'users (preserved)', COUNT(*) FROM users;

COMMIT;

-- Notes:
-- 1. synthesis_configs will auto-recreate on next access (get_or_create_default)
-- 2. Users can create new animas from fresh state
-- 3. All RLS policies remain active and enforced
