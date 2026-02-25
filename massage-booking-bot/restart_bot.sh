#!/bin/bash

echo "🛑 Stopping bot..."
pkill -f "python.*run.py" || true
sleep 1

echo "🚀 Starting bot..."
cd "$(dirname "$0")"
source .venv/bin/activate
python run.py

