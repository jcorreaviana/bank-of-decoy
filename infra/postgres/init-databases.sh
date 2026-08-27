#!/bin/bash
set -e

for db in onboarding account pix_key transaction agent_ops; do
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" <<-EOSQL
    CREATE DATABASE $db;
EOSQL
done
