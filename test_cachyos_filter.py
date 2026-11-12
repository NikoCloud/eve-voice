"""Checks for the read-only command filter (nothing here is sent to cachyos)."""
from eve import check_cachyos

ALLOW = [
    "uptime", "df -h", "free -h", "du -sh /mnt/models/*", "ls -la /home",
    "ls /mnt/models | wc -l", "du -ah /mnt/models | sort -rh | head -n 6",
    'grep -E "error|failed" /tmp/eve-llm.log', "grep -c 'a b' /tmp/x | sort -n",
    "find /mnt/models -name '*.gguf' -size +1G", "tail -n 20 /tmp/eve-tts.log",
    "sort -rn /tmp/x", "uniq -c /tmp/x", "tree -L 2 /mnt/models", "rocm-smi", "rocm-smi --showmeminfo vram",
    "date", "ps aux", "cat /etc/hostname", "stat /mnt/models", "head -c 4000 '/home/a b/notes.md'",
]
REFUSE = [
    "ls\nrm -rf /tmp/x", "ls\r\nrm x", "ls; rm x", "ls && rm x", "ls > /tmp/x", "cat < /etc/passwd",
    "ls `whoami`", "ls $(whoami)", "ls ${HOME}", "ls $'\\n' rm", "ls || rm x", "ls | rm x", "rm x", "",
    "ls |", 'grep "unclosed /tmp/x',
    "find /tmp -delete", "find /tmp -exec rm {} +", "find /tmp -execdir rm {} +", "find / -fls /tmp/x",
    "find / -fprint /tmp/x", "find / -fprintf /tmp/x %p", "find /tmp -ok rm {} +",
    "sort -o /tmp/x /etc/hostname", "sort -ro /tmp/x /etc/hostname", "sort --output=/tmp/x /etc/hostname",
    "sort --compress-program=sh /tmp/x", "uniq /etc/hostname /tmp/x", "tree -o /tmp/x",
    "tail -f /var/log/x", "tail -F /var/log/x", "tail --follow /var/log/x", "tail -n 5 -f /x",
    "file -C -m /tmp/x", "date -s tomorrow", "date --set=tomorrow",
    "rocm-smi --setpoweroverdrive 300", "rocm-smi --resetclocks", "rocm-smi --setfan 255",
    "df -h | sort -o /tmp/x",
]
bad = 0
for cmd in ALLOW:
    why = check_cachyos(cmd); ok = why is None; bad += not ok
    print("ok  " if ok else "FAIL", "allow ", repr(cmd), "" if ok else why)
for cmd in REFUSE:
    why = check_cachyos(cmd); ok = why is not None; bad += not ok
    print("ok  " if ok else "FAIL", "refuse", repr(cmd))
print("all passed" if not bad else f"{bad} failed")
