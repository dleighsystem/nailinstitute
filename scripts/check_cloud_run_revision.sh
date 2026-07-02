#!/usr/bin/env bash
# Verify Cloud Run service readiness, traffic, and optional revision identity.
set -euo pipefail

PROJECT=""
REGION=""
SERVICE=""
EXPECT_TRAFFIC="100"
EXPECT_REVISION=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project)
      PROJECT="$2"; shift 2 ;;
    --region)
      REGION="$2"; shift 2 ;;
    --service)
      SERVICE="$2"; shift 2 ;;
    --expect-traffic)
      EXPECT_TRAFFIC="$2"; shift 2 ;;
    --expect-revision)
      EXPECT_REVISION="$2"; shift 2 ;;
    -h|--help)
      sed -n '1,80p' "$0"; exit 0 ;;
    *)
      echo "unknown argument: $1" >&2; exit 4 ;;
  esac
done

if [[ -z "$PROJECT" || -z "$REGION" || -z "$SERVICE" ]]; then
  echo "--project, --region, and --service are required" >&2
  exit 4
fi

SERVICE_JSON="$(gcloud run services describe "$SERVICE" \
  --platform=managed \
  --region="$REGION" \
  --project="$PROJECT" \
  --format=json)"

SERVICE_JSON="$SERVICE_JSON" python3 - "$EXPECT_TRAFFIC" "$EXPECT_REVISION" <<'PY'
import json
import os
import sys

expect_traffic = int(sys.argv[1])
expect_revision = sys.argv[2]
service = json.loads(os.environ["SERVICE_JSON"])
status = service.get("status") or {}
metadata = service.get("metadata") or {}
conditions = {item.get("type"): item for item in status.get("conditions", [])}
ready = conditions.get("Ready", {}).get("status") == "True"
if not ready:
    print("Cloud Run service is not Ready", file=sys.stderr)
    sys.exit(2)

traffic = status.get("traffic") or []
if not traffic:
    print("Cloud Run service has no traffic allocation", file=sys.stderr)
    sys.exit(2)

serving = [item for item in traffic if int(item.get("percent") or 0) > 0]
total_percent = sum(int(item.get("percent") or 0) for item in serving)
if total_percent != expect_traffic:
    print(f"traffic percent {total_percent} != expected {expect_traffic}", file=sys.stderr)
    sys.exit(2)

revision_names = [item.get("revisionName") for item in serving if item.get("revisionName")]
latest_ready = status.get("latestReadyRevisionName")
latest_created = status.get("latestCreatedRevisionName")
if expect_revision and expect_revision not in revision_names:
    print(f"expected revision {expect_revision} is not serving traffic: {revision_names}", file=sys.stderr)
    sys.exit(2)

if not revision_names and latest_ready:
    revision_names = [latest_ready]

print(json.dumps({
    "ok": True,
    "service": metadata.get("name"),
    "url": status.get("url"),
    "latest_ready_revision": latest_ready,
    "latest_created_revision": latest_created,
    "serving_revisions": revision_names,
    "traffic_percent": total_percent,
}, indent=2, sort_keys=True))
PY
