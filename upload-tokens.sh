#!/bin/bash
# Upload local Gmail tokens to Railway server
# Usage: ./upload-tokens.sh https://your-app.railway.app

SERVER_URL="${1:-http://localhost:8080}"

echo "Uploading Gmail tokens to $SERVER_URL"

# Upload tokens for each account
for token_file in ~/.config/gmail-mcp/token_*.json; do
    if [ -f "$token_file" ]; then
        # Extract email from filename
        filename=$(basename "$token_file")
        email=$(echo "$filename" | sed 's/token_//' | sed 's/.json//' | sed 's/_at_/@/' | sed 's/_/./g')

        echo "Uploading token for: $email"

        token_content=$(cat "$token_file")

        curl -s -X POST "$SERVER_URL/gmail/token" \
            -H "Content-Type: application/json" \
            -d "{\"email\": \"$email\", \"token\": $token_content}"

        echo ""
    fi
done

echo "Done. Check status:"
curl -s "$SERVER_URL/gmail/status" | python3 -m json.tool
