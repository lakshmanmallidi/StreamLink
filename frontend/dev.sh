#!/bin/bash
# StreamLink Frontend Development Server

set -e

FRONTEND_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Check Node.js
if ! command -v node &> /dev/null; then
    echo "Error: Node.js is required"
    exit 1
fi

# Install dependencies if needed
if [ ! -d "$FRONTEND_DIR/node_modules" ]; then
    cd "$FRONTEND_DIR"
    npm install
fi

# Set environment variables for development (allow override)
# If VITE_API_URL is already set, keep it; else default to backend dev on localhost:3000
if [ -z "$VITE_API_URL" ]; then
    export VITE_API_URL="http://localhost:3000"
fi

# Optional: warn if backend seems unreachable
BACKEND_CHECK_URL="${VITE_API_URL%/}/health"
if command -v curl >/dev/null 2>&1; then
    if ! curl -sf "$BACKEND_CHECK_URL" >/dev/null; then
        echo "Warning: Backend not reachable at $VITE_API_URL (checked $BACKEND_CHECK_URL)"
        echo "Tip: export VITE_API_URL=\"http://<backend-host>:<port>\" before running this script."
    fi
fi

# Run development server
echo "Starting frontend on http://localhost:3001"
echo "API URL: $VITE_API_URL"

cd "$FRONTEND_DIR"
npm run dev
