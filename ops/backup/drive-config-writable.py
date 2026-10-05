"""Move rclone state to the existing writable service state directory.

Run as root on the VPS via stdin. Never prints credential contents.
"""
from pathlib import Path
import os
import shutil
import re

config=Path('/etc/sgc-backup/drive.conf')
saved=Path('/etc/sgc-backup/drive.conf.pre-two-profiles-20261005')
source=Path('/etc/sgc-backup/rclone.conf')
target=Path('/var/lib/sgc-backup-drive/rclone.conf')
text=config.read_text()
assert source.exists()
assert not saved.exists(), 'Preservation copy already exists; inspect before retrying'
assert not target.exists(), 'Target already exists; inspect before retrying'
match=re.search(r'^RCLONE_CONFIG=.*$',text,re.M)
assert match and '/etc/sgc-backup/rclone.conf' in match.group(0)
with saved.open('xb') as stream: stream.write(config.read_bytes())
os.chmod(saved,0o600)
with target.open('xb') as stream: stream.write(source.read_bytes())
os.chmod(target,0o600)
replacement="RCLONE_CONFIG='/var/lib/sgc-backup-drive/rclone.conf'"
config.write_text(text[:match.start()]+replacement+text[match.end():])
os.chmod(config,0o600)
print('CONFIG_UPDATED: original preserved; writable state config mode 0600')
