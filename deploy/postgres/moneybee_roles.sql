-- Run with psql variables supplied by the approved secret mechanism:
--   -v runtime_password='...' -v migrator_password='...'
-- Never store passwords in this repository.
\set ON_ERROR_STOP on

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'moneybee_admin') THEN
    CREATE ROLE moneybee_admin LOGIN SUPERUSER;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'moneybee_migrator') THEN
    CREATE ROLE moneybee_migrator LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'moneybee_runtime') THEN
    CREATE ROLE moneybee_runtime LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
  END IF;
END $$;

-- The bootstrap identity remains the separately protected administrative
-- login created by the PostgreSQL image. It is never passed to an app image.
ALTER ROLE moneybee_admin LOGIN SUPERUSER;
ALTER ROLE moneybee_migrator LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
ALTER ROLE moneybee_runtime LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;

ALTER ROLE moneybee_migrator PASSWORD :'migrator_password';
ALTER ROLE moneybee_runtime PASSWORD :'runtime_password';

REVOKE ALL ON DATABASE moneybee FROM PUBLIC;
GRANT CONNECT ON DATABASE moneybee TO moneybee_migrator, moneybee_runtime;
REVOKE CREATE, TEMPORARY ON DATABASE moneybee FROM PUBLIC, moneybee_runtime;
GRANT TEMPORARY ON DATABASE moneybee TO moneybee_migrator;

-- Ownership, not grants, is what lets Alembic ALTER existing objects. The
-- bootstrap administrator runs this idempotent transfer before the runtime
-- identity is put into service. Only application objects in public move.
ALTER SCHEMA public OWNER TO moneybee_migrator;
SELECT format('ALTER TABLE %I.%I OWNER TO moneybee_migrator', n.nspname, c.relname)
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public'
  AND c.relkind IN ('r', 'p', 'v', 'm', 'f')
  AND pg_get_userbyid(c.relowner) <> 'moneybee_migrator'
ORDER BY c.oid
\gexec

SELECT format('ALTER SEQUENCE %I.%I OWNER TO moneybee_migrator', n.nspname, c.relname)
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public'
  AND c.relkind = 'S'
  AND pg_get_userbyid(c.relowner) <> 'moneybee_migrator'
ORDER BY c.oid
\gexec

SELECT format(
  'ALTER FUNCTION %I.%I(%s) OWNER TO moneybee_migrator',
  n.nspname,
  p.proname,
  pg_get_function_identity_arguments(p.oid)
)
FROM pg_proc p
JOIN pg_namespace n ON n.oid = p.pronamespace
WHERE n.nspname = 'public'
  AND pg_get_userbyid(p.proowner) <> 'moneybee_migrator'
ORDER BY p.oid
\gexec

SELECT format('ALTER TYPE %I.%I OWNER TO moneybee_migrator', n.nspname, t.typname)
FROM pg_type t
JOIN pg_namespace n ON n.oid = t.typnamespace
WHERE n.nspname = 'public'
  AND t.typtype IN ('e', 'd')
  AND pg_get_userbyid(t.typowner) <> 'moneybee_migrator'
ORDER BY t.oid
\gexec

REVOKE ALL ON SCHEMA public FROM PUBLIC, moneybee_runtime;
GRANT USAGE, CREATE ON SCHEMA public TO moneybee_migrator;
GRANT USAGE ON SCHEMA public TO moneybee_runtime;
REVOKE CREATE ON SCHEMA public FROM PUBLIC, moneybee_runtime;
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM moneybee_runtime;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM moneybee_runtime;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public FROM moneybee_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO moneybee_runtime;
GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO moneybee_runtime;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO moneybee_runtime;

ALTER DEFAULT PRIVILEGES FOR ROLE moneybee_migrator IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO moneybee_runtime;
ALTER DEFAULT PRIVILEGES FOR ROLE moneybee_migrator IN SCHEMA public
  GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO moneybee_runtime;
ALTER DEFAULT PRIVILEGES FOR ROLE moneybee_migrator IN SCHEMA public
  GRANT EXECUTE ON FUNCTIONS TO moneybee_runtime;
