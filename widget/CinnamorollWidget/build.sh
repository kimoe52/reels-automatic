#!/bin/sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
project_root=$(CDPATH= cd -- "$script_dir/../.." && pwd)
style_source="$script_dir/Sources/UnifiedMascotStyle.swift"
app_name="시나모롤 콘텐츠 위젯.app"
app_path="$script_dir/dist/$app_name"
replace_existing=0
stage_dir=""
backup_path=""
restore_old=0

cleanup() {
  if [ "$restore_old" -eq 1 ] && [ -n "$backup_path" ] && [ -e "$backup_path" ] && [ ! -e "$app_path" ]; then
    mv "$backup_path" "$app_path"
  fi
  if [ -n "$stage_dir" ] && [ -d "$stage_dir" ]; then
    rm -rf "$stage_dir"
  fi
}

if [ "${1:-}" = "--verify" ]; then
  if [ -x "$app_path/Contents/MacOS/CinnamorollThreadsWidget" ] \
      && [ -f "$app_path/Contents/Resources/cinnamoroll-widget-mascot.png" ] \
      && /usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$app_path/Contents/Info.plist" >/dev/null \
      && [ -f "$project_root/automation/meta-threads/run_daily.py" ] \
      && [ -f "$project_root/automation/meta-threads/fetch/fetch_posts.py" ]; then
    codesign --verify --deep --strict "$app_path"
    printf 'Verified: %s\n' "$app_path"
    exit 0
  fi
  printf '%s\n' "Widget verification failed; rebuild required" >&2
  exit 1
fi

if [ "${1:-}" = "--replace" ] && [ "$#" -eq 1 ]; then
  replace_existing=1
elif [ "$#" -gt 0 ]; then
  printf '%s\n' "Usage: $0 [--verify | --replace]" >&2
  exit 2
fi

if [ -e "$app_path" ] && [ "$replace_existing" -eq 0 ]; then
  printf 'Refusing to overwrite existing app: %s\n' "$app_path" >&2
  printf '%s\n' "Use --replace to install a rebuilt app." >&2
  exit 1
fi

task_python="/opt/homebrew/bin/python3"
if [ ! -x "$task_python" ]; then
  task_python="/usr/local/bin/python3"
fi
if [ ! -x "$task_python" ]; then
  task_python=$(command -v python3)
fi
task_scratch_root=$("$task_python" "$project_root/production/project_paths.py" --path scratch --create)
mkdir -p "$task_scratch_root/widget-builds"
stage_dir=$(mktemp -d "$task_scratch_root/widget-builds/cinnamoroll-widget-build.XXXXXX")
backup_path="$stage_dir/original.app"
trap cleanup EXIT
trap 'exit 1' HUP INT TERM

staged_app="$stage_dir/$app_name"
contents="$staged_app/Contents"
resources="$contents/Resources"
mkdir -p "$contents/MacOS" "$resources"

swiftc -parse-as-library -O \
  -module-cache-path "$stage_dir/module-cache" \
  -framework AppKit -framework Foundation \
  "$script_dir/Sources/main.swift" \
  "$style_source" \
  -o "$contents/MacOS/CinnamorollThreadsWidget"
cp "$script_dir/Info.plist" "$contents/Info.plist"
plutil -insert ContentProjectRoot -string "$project_root" "$contents/Info.plist"

"$task_python" - "$script_dir/assets/cinnamoroll-unified-v3.png" \
    "$resources/cinnamoroll-widget-mascot.png" "$resources/cinnamoroll-widget-icon.icns" <<'PY'
from PIL import Image
import sys

source = Image.open(sys.argv[1]).convert("RGBA")
alpha = source.getchannel("A")
box = alpha.getbbox()
if box:
    source = source.crop(box)
source.thumbnail((920, 920), Image.Resampling.LANCZOS)
canvas = Image.new("RGBA", (1024, 1024), (0, 0, 0, 0))
canvas.alpha_composite(source, ((1024 - source.width) // 2, (1024 - source.height) // 2))
canvas.save(sys.argv[2], format="PNG")
canvas.save(sys.argv[3], format="ICNS")
PY
/usr/libexec/PlistBuddy -c 'Add :CFBundleIconFile string cinnamoroll-widget-icon' "$contents/Info.plist"

codesign --force --deep --sign - "$staged_app" >/dev/null
codesign --verify --deep --strict "$staged_app"

if [ -e "$app_path" ]; then
  mv "$app_path" "$backup_path"
  restore_old=1
fi
mv "$staged_app" "$app_path"
if ! "$script_dir/build.sh" --verify; then
  rm -rf "$app_path"
  exit 1
fi
restore_old=0
printf '%s\n' "$app_path"
