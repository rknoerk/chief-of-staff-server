#!/bin/bash
# Sync local MD files to Chief of Staff server
# Usage: ./sync-context.sh

SERVER_URL="https://chief-of-staff-server.vercel.app"
API_KEY="cos-2026-mobile"
CONTEXT_DIR="$HOME/chief-of-staff"

echo "Syncing context files to $SERVER_URL"

# Build JSON payload with all MD files
FILES_JSON="{"

for file in "$CONTEXT_DIR"/*.md; do
    if [ -f "$file" ]; then
        filename=$(basename "$file")
        # Read file content and escape for JSON
        content=$(cat "$file" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')

        if [ "$FILES_JSON" != "{" ]; then
            FILES_JSON="$FILES_JSON,"
        fi
        FILES_JSON="$FILES_JSON\"$filename\":$content"
        echo "  - $filename"
    fi
done

FILES_JSON="$FILES_JSON}"

# Send to server
PAYLOAD="{\"files\":$FILES_JSON,\"syncedAt\":$(date +%s)000}"

RESPONSE=$(curl -s -X POST "${SERVER_URL}/context?key=${API_KEY}" \
    -H "Content-Type: application/json" \
    -d "$PAYLOAD")

echo ""
echo "Response: $RESPONSE"
