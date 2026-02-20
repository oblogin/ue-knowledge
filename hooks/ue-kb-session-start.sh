#!/usr/bin/env bash
# UserPromptSubmit hook: on first prompt in a UE project, reminds Claude
# to search the UE Knowledge Base for relevant context.
# Detects UE projects by .uproject file or Engine/Source in additional dirs.
# Fires once per session (lock file keyed by PPID).

set -euo pipefail

LOCK_DIR="/tmp/ue-kb-hooks"
mkdir -p "$LOCK_DIR"

LOCK_FILE="$LOCK_DIR/context-loaded-$PPID"

# Already fired this session — skip
if [[ -f "$LOCK_FILE" ]]; then
  echo '{}'
  exit 0
fi

# Detect if this is a UE project
is_ue_project=false

# Check for .uproject in current dir or parent dirs (up to 3 levels)
dir="$PWD"
for _ in 1 2 3; do
  if ls "$dir"/*.uproject 1>/dev/null 2>&1; then
    is_ue_project=true
    break
  fi
  parent="$(dirname "$dir")"
  [[ "$parent" == "$dir" ]] && break
  dir="$parent"
done

# Check if UE Engine source is in additional directories (via env or common paths)
if [[ "$is_ue_project" == false ]]; then
  for ue_path in "$HOME/UnrealEngine" "/c/UE_5.7" "/c/UE_5.5" "/c/UE_5.4"; do
    if [[ -d "$ue_path/Engine/Source" ]] && [[ "$PWD" == *"Unreal"* || "$PWD" == *"UE_"* ]]; then
      is_ue_project=true
      break
    fi
  done
fi

# Not a UE project — skip
if [[ "$is_ue_project" == false ]]; then
  echo '{}'
  exit 0
fi

touch "$LOCK_FILE"

cat <<'EOF'
{
  "hookSpecificOutput": {
    "hookEventName": "UserPromptSubmit",
    "additionalContext": "UE PROJECT DETECTED: You have access to the UE Knowledge Base (mcp__ue-knowledge__ue_search, mcp__ue-knowledge__ue_get, etc.). BEFORE working with any UE class, subsystem, or pattern — call ue_search to check if you already have recorded knowledge about it. This saves time and prevents re-learning. Do this silently."
  }
}
EOF
exit 0
