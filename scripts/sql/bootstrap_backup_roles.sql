-- Idempotent bootstrap of the minimal A5a roles (subset of target.md section 10.1).
-- NOT run automatically. Run once by the user as the bootstrap superuser:
--   docker compose -f docker-compose.local.yml exec -T postgres sh -c \
--     'psql -U "$POSTGRES_USER" -d postgres -v ON_ERROR_STOP=1' < scripts/sql/bootstrap_backup_roles.sql
-- Roles have LOGIN but NO password: they work only over the container's local unix socket
-- (trust auth in the official image) and cannot log in over the published TCP port 5432.
-- Cluster-level changes: 2 roles, 1 database (nexus_test, if missing), CONNECT privilege change.

SELECT 'CREATE ROLE nexus_ro LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION'
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'nexus_ro') \gexec

SELECT 'CREATE ROLE nexus_test_owner LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION'
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'nexus_test_owner') \gexec

-- Scratch DB owned by the test role (created only if missing).
SELECT 'CREATE DATABASE nexus_test OWNER nexus_test_owner'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'nexus_test') \gexec
-- If nexus_test already exists under another owner, hand it over (the DB holds no live data).
ALTER DATABASE nexus_test OWNER TO nexus_test_owner;

-- Role settings (server-side half of B5).
ALTER ROLE nexus_ro SET statement_timeout = '30min';
ALTER ROLE nexus_ro SET default_transaction_read_only = on;

-- nexus_test_owner must not reach live data: revoke the implicit PUBLIC CONNECT on nexus,
-- then grant it explicitly to the roles that need it. Superusers are unaffected.
REVOKE CONNECT ON DATABASE nexus FROM PUBLIC;
GRANT CONNECT ON DATABASE nexus TO nexus_ro;
REVOKE ALL ON DATABASE nexus FROM nexus_test_owner;

-- Grants inside nexus.
\connect nexus
SELECT current_user AS owner_role \gset
GRANT USAGE ON SCHEMA public TO nexus_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO nexus_ro;
GRANT SELECT ON ALL SEQUENCES IN SCHEMA public TO nexus_ro;
ALTER DEFAULT PRIVILEGES FOR ROLE :"owner_role" IN SCHEMA public GRANT SELECT ON TABLES TO nexus_ro;
ALTER DEFAULT PRIVILEGES FOR ROLE :"owner_role" IN SCHEMA public GRANT SELECT ON SEQUENCES TO nexus_ro;
