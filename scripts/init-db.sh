#!/bin/bash
# Initialize databases for StreamLink application
# This script creates the keycloak database and user for Keycloak IDP

set -e

# Get password from environment variable, fallback to default if not set
KC_PASSWORD="${KC_DB_PASSWORD:-keycloak123}"

echo "Creating keycloak user and database..."

# Create keycloak user
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    -- Create keycloak user for Keycloak IDP
    CREATE USER keycloak WITH PASSWORD '$KC_PASSWORD';
    
    -- Create keycloak database
    CREATE DATABASE keycloak OWNER keycloak;
    
    -- Grant all privileges to keycloak user on keycloak database
    GRANT ALL PRIVILEGES ON DATABASE keycloak TO keycloak;
EOSQL

echo "Keycloak database and user created successfully"
