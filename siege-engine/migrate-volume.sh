#!/usr/bin/env bash
set -euo pipefail

APP="siege-engine"
REGION="iad"
OLD_VOL="vol_vz56okd1k8lnq9xv"
OLD_MACHINE="7846453a22dd38"

echo "=== Step 1: List snapshots for old volume ==="
fly volumes snapshots list "$OLD_VOL" -a "$APP"

echo ""
echo "=== Step 2: Create new volume from most recent snapshot ==="
# Get the most recent snapshot ID
SNAPSHOT_ID=$(fly volumes snapshots list "$OLD_VOL" -a "$APP" --json | jq -r '.[0].id')

if [ -z "$SNAPSHOT_ID" ] || [ "$SNAPSHOT_ID" = "null" ]; then
  echo "ERROR: No snapshots found for volume $OLD_VOL"
  echo "You may need to wait for a snapshot to be created, or create one manually."
  exit 1
fi

echo "Using snapshot: $SNAPSHOT_ID"

# Create a new volume from the snapshot (same size as original)
OLD_SIZE=$(fly volumes show "$OLD_VOL" -a "$APP" --json | jq -r '.size_gb')
echo "Original volume size: ${OLD_SIZE}GB"

NEW_VOL_OUTPUT=$(fly volumes create siege_data \
  --region "$REGION" \
  --size "$OLD_SIZE" \
  --snapshot-id "$SNAPSHOT_ID" \
  -a "$APP" \
  --json)

NEW_VOL_ID=$(echo "$NEW_VOL_OUTPUT" | jq -r '.id')
echo "Created new volume: $NEW_VOL_ID"

echo ""
echo "=== Step 3: Clone old machine to use new volume ==="
# Clone the machine, attaching the new volume
NEW_MACHINE_OUTPUT=$(fly machine clone "$OLD_MACHINE" \
  --attach-volume "$NEW_VOL_ID:/data" \
  --region "$REGION" \
  -a "$APP")

echo "$NEW_MACHINE_OUTPUT"

echo ""
echo "=== Step 4: Verify ==="
echo "New volume:"
fly volumes show "$NEW_VOL_ID" -a "$APP"

echo ""
echo "All machines:"
fly machines list -a "$APP"

echo ""
echo "=== Done ==="
echo "Old machine $OLD_MACHINE is still running (not destroyed)."
echo "Old volume $OLD_VOL is still intact."
echo ""
echo "Once you've verified the new machine works:"
echo "  fly machines stop $OLD_MACHINE -a $APP"
echo "  fly machines destroy $OLD_MACHINE -a $APP"
echo "  fly volumes delete $OLD_VOL -a $APP"
