\set ON_ERROR_STOP on

SELECT current_database() = 'moneybee' AS correct_database \gset
\if :correct_database
\else
  \echo 'Wrong database'
  \quit 3
\endif

SELECT current_user = 'moneybee_runtime' AS expected_runtime_role,
       NOT rolsuper AS not_superuser,
       NOT rolcreatedb AS cannot_create_database,
       NOT rolcreaterole AS cannot_create_role,
       NOT rolreplication AS cannot_replicate,
       NOT rolbypassrls AS cannot_bypass_rls
FROM pg_roles WHERE rolname = current_user;

SELECT bool_and(has_table_privilege(current_user, format('%I.%I', schemaname, tablename),
                                    'SELECT,INSERT,UPDATE,DELETE')) AS table_dml_granted
FROM pg_tables WHERE schemaname = 'public';
SELECT bool_and(has_sequence_privilege(current_user, format('%I.%I', sequence_schema, sequence_name),
                                       'USAGE,SELECT,UPDATE')) AS sequence_access_granted
FROM information_schema.sequences WHERE sequence_schema = 'public';
