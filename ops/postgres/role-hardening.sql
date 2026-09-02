\set ON_ERROR_STOP on

SELECT current_database() = 'moneybee' AS correct_database \gset
\if :correct_database
\else
  \echo 'Refusing to harden roles outside the moneybee database'
  \quit 3
\endif

DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'moneybee_migrator') THEN
    CREATE ROLE moneybee_migrator LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
  END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'moneybee_runtime') THEN
    CREATE ROLE moneybee_runtime LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
  END IF;
END $$;

ALTER ROLE moneybee_migrator NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
ALTER ROLE moneybee_runtime NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
REVOKE ALL ON DATABASE moneybee FROM PUBLIC;
GRANT CONNECT ON DATABASE moneybee TO moneybee_migrator, moneybee_runtime;
REVOKE CREATE, TEMPORARY ON DATABASE moneybee FROM moneybee_runtime;
ALTER SCHEMA public OWNER TO moneybee_migrator;
SELECT format('ALTER TABLE %I.%I OWNER TO moneybee_migrator', schemaname, tablename)
FROM pg_tables WHERE schemaname = 'public' AND tableowner <> 'moneybee_migrator' \gexec
SELECT format('ALTER SEQUENCE %I.%I OWNER TO moneybee_migrator', sequence_schema, sequence_name)
FROM information_schema.sequences WHERE sequence_schema = 'public' \gexec
SELECT format('ALTER FUNCTION %I.%I(%s) OWNER TO moneybee_migrator',
              n.nspname, p.proname, pg_get_function_identity_arguments(p.oid))
FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
WHERE n.nspname = 'public' AND pg_get_userbyid(p.proowner) <> 'moneybee_migrator' \gexec
REVOKE ALL ON SCHEMA public FROM PUBLIC, moneybee_runtime;
GRANT USAGE, CREATE ON SCHEMA public TO moneybee_migrator;
GRANT USAGE ON SCHEMA public TO moneybee_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO moneybee_runtime;
GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO moneybee_runtime;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO moneybee_runtime;
ALTER DEFAULT PRIVILEGES FOR ROLE moneybee_migrator IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO moneybee_runtime;
ALTER DEFAULT PRIVILEGES FOR ROLE moneybee_migrator IN SCHEMA public
  GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO moneybee_runtime;
ALTER DEFAULT PRIVILEGES FOR ROLE moneybee_migrator IN SCHEMA public
  GRANT EXECUTE ON FUNCTIONS TO moneybee_runtime;
