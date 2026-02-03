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

# Set environment variables for development
export VITE_API_URL="http://localhost:3000"

# Run development server
echo "Starting frontend on http://localhost:3001"
echo "API URL: $VITE_API_URL"

cd "$FRONTEND_DIR"
npm run dev
