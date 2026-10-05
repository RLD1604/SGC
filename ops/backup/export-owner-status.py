"""Publish non-secret backup metadata for the read-only owner dashboard."""
import json,subprocess
from pathlib import Path
from datetime import datetime,timezone

target=Path('/opt/sgc-codex-20260925/runtime-status')
target.mkdir(mode=0o755,exist_ok=True)
output={'status':'unavailable'}
try:
    source=json.loads(Path('/var/lib/sgc-backup-drive/last-success.json').read_text())
    run_id=Path('/var/backups/sgc/latest').resolve().name
    verified=datetime.fromisoformat(source['verifiedAtUtc'].replace('Z','+00:00'))
    status=source['status']
    if source['runId']!=run_id:status='pending'
    elif (datetime.now(timezone.utc)-verified).total_seconds()>30*3600:status='stale'
    output={key:source.get(key) for key in ('runId','verifiedAtUtc','files')}
    timers=all(subprocess.run(['systemctl','is-active','--quiet',name],check=False).returncode==0 for name in ('sgc-backup.timer','sgc-backup-drive.timer'))
    output['status']=status if timers else 'schedule_error'
    output['source']='drive'
    output['timersActive']=timers
except (OSError,ValueError,KeyError):pass
temp=target/'backup.json.tmp'
temp.write_text(json.dumps(output))
temp.chmod(0o644)
temp.replace(target/'backup.json')
print('OWNER_BACKUP_STATUS_EXPORTED')
