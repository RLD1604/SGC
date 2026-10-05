#!/usr/bin/env bash
set -Eeuo pipefail
# Only the disposable diagnostics table has a 90-day retention policy.
docker exec sgc-codex-database psql -X -U condominio -d condominio -v ON_ERROR_STOP=1 -c "DELETE FROM diagnostic_events WHERE occurred_at<now()-interval '90 days';"
