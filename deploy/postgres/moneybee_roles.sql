-- Run with psql variables supplied by the approved secret mechanism:
--   -v runtime_password='...' -v migrator_password='...'
-- Never store passwords in this repository.
\set ON_ERROR_STOP on

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'moneybee_db_admin') THEN
    CREATE ROLE moneybee_db_admin NOLOGIN SUPERUSER;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'moneybee_migrator') THEN
    CREATE ROLE moneybee_migrator LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'moneybee_runtime') THEN
    CREATE ROLE moneybee_runtime LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
  END IF;
END $$;

ALTER ROLE moneybee_migrator PASSWORD :'migrator_password';
ALTER ROLE moneybee_runtime PASSWORD :'runtime_password';

REVOKE ALL ON DATABASE moneybee FROM PUBLIC;
GRANT CONNECT ON DATABASE moneybee TO moneybee_migrator, moneybee_runtime;
GRANT USAGE ON SCHEMA public TO moneybee_runtime;
REVOKE CREATE ON SCHEMA public FROM PUBLIC, moneybee_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO moneybee_runtime;
GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO moneybee_runtime;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO moneybee_runtime;

ALTER DEFAULT PRIVILEGES FOR ROLE moneybee_migrator IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO moneybee_runtime;
ALTER DEFAULT PRIVILEGES FOR ROLE moneybee_migrator IN SCHEMA public
  GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO moneybee_runtime;
ALTER DEFAULT PRIVILEGES FOR ROLE moneybee_migrator IN SCHEMA public
  GRANT EXECUTE ON FUNCTIONS TO moneybee_runtime;
