#!/bin/bash
# Build .skill file for Claude App import
# Usage: ./build.sh

cd "$(dirname "$0")"

# Create skill package
rm -f chief-of-staff.skill
zip -r chief-of-staff.skill chief-of-staff/

echo "Created: chief-of-staff.skill"
echo "Import this file into Claude App → Projects"
