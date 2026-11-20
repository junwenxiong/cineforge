#!/usr/bin/env bash
# 等工作机手上镜头全部回传（current 为空，且没有它名下 claimed 的租约）再删除运行时
cd "$(dirname "$0")/../.."
film=${FILM:-starcore}
workers=()
while [ "$#" -gt 0 ]; do
  case "$1" in
    --film) [ "$#" -ge 2 ] || exit 2; film=$2; shift 2 ;;
    *) workers+=("$1"); shift ;;
  esac
done
film=$(python3 tools/film/film_config.py --film "$film") || exit 2
[ "${#workers[@]}" = 1 ] || { echo "usage: $0 [--film NAME] WORKER"; exit 2; }
w=${workers[0]}
[[ "$w" =~ ^[a-zA-Z0-9_-]+$ ]] || exit 2
for i in $(seq 1 120); do
  cur=$(curl -s -m 10 "http://127.0.0.1:8765/status?t=$(cat renders/farm/token)" | python3 -c "import json,sys;print(len(json.load(sys.stdin).get('$w',{}).get('current') or []))")
  open=$(grep -l "\"worker\": \"$w\"" renders/*/claim.json 2>/dev/null | xargs -r grep -l '"status": "claimed"' | while read c; do [ -f "$(dirname $c)/job.json" ] || echo $c; done | wc -l)
  if [ "$cur" = "0" ] && [ "$open" = "0" ]; then
    timeout 90 python.exe -X utf8 tools/film/colab_drive.py --film "$film" kill "${film}_$w" 2>&1 | tail -1
    echo "$(date +%H:%M) $w 已排空并删除运行时"; exit 0
  fi
  sleep 20
done
echo "$w 40 分钟未排空"
