#!/bin/bash
# StreamLink Backend Development Server

set -e

BACKEND_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$BACKEND_DIR/venv"
ROOT_DIR="$(dirname "$BACKEND_DIR")"

# Load environment variables from .env
if [ -f "$ROOT_DIR/.env" ]; then
    export $(cat "$ROOT_DIR/.env" | grep -v '^#' | xargs)
fi

# Check Python version
if command -v python3.11 &> /dev/null; then
    PYTHON_CMD="python3.11"
elif command -v python3.12 &> /dev/null; then
    PYTHON_CMD="python3.12"
elif command -v python3 &> /dev/null; then
    PYTHON_CMD="python3"
else
    echo "Error: Python 3 is required"
    exit 1
fi

# Create virtual environment if it doesn't exist
if [ ! -d "$VENV_DIR" ]; then
    $PYTHON_CMD -m venv "$VENV_DIR"
fi

# Activate virtual environment
source "$VENV_DIR/bin/activate"

# Install dependencies
pip install -q --upgrade pip setuptools wheel
pip install -q -r "$BACKEND_DIR/requirements.txt" 2>&1 || {
    pip install --no-build-isolation -q -r "$BACKEND_DIR/requirements.txt"
}

# Run development server
echo "Starting backend on http://localhost:3000"

cd "$BACKEND_DIR"
python -m uvicorn src.main:create_app \
    --host 0.0.0.0 \
    --port 3000 \
    --reload
