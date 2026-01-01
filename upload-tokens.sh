#!/bin/bash
# Upload local Gmail tokens to cloud server
# Usage: ./upload-tokens.sh https://your-app.fly.dev [api-key]

SERVER_URL="${1:-http://localhost:8080}"
API_KEY="${2:-}"

echo "Uploading Gmail tokens to $SERVER_URL"

# Build key param
KEY_PARAM=""
if [ -n "$API_KEY" ]; then
    KEY_PARAM="?key=$API_KEY"
fi

# Upload tokens for each account
for token_file in ~/.config/gmail-mcp/token_*.json; do
    if [ -f "$token_file" ]; then
        # Extract email from filename
        filename=$(basename "$token_file")
        email=$(echo "$filename" | sed 's/token_//' | sed 's/.json//' | sed 's/_at_/@/' | sed 's/_/./g')

        echo "Uploading token for: $email"

        token_content=$(cat "$token_file")

        curl -s -X POST "${SERVER_URL}/gmail/token${KEY_PARAM}" \
            -H "Content-Type: application/json" \
            -d "{\"email\": \"$email\", \"token\": $token_content}"

        echo ""
    fi
done

echo "Done. Check status:"
curl -s "${SERVER_URL}/gmail/status${KEY_PARAM}" | python3 -m json.tool
