#!/usr/bin/env bash
# UserPromptSubmit hook: on every prompt in a UE project, adds a persistent
# reminder to save UE knowledge before ending the session.
# Lightweight — only injects context, doesn't block.

set -euo pipefail

# Detect if this is a UE project
is_ue_project=false

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

if [[ "$is_ue_project" == false ]]; then
  for ue_path in "$HOME/UnrealEngine" "/c/UE_5.7" "/c/UE_5.5" "/c/UE_5.4"; do
    if [[ -d "$ue_path/Engine/Source" ]] && [[ "$PWD" == *"Unreal"* || "$PWD" == *"UE_"* ]]; then
      is_ue_project=true
      break
    fi
  done
fi

if [[ "$is_ue_project" == false ]]; then
  echo '{}'
  exit 0
fi

cat <<'EOF'
{
  "hookSpecificOutput": {
    "hookEventName": "UserPromptSubmit",
    "additionalContext": "REMINDER: You are in a UE project with access to the UE Knowledge Base. When you read or learn about UE classes, patterns, macros, or architecture — save it via mcp__ue-knowledge__ue_save before the session ends. Search first with ue_search to avoid duplicates."
  }
}
EOF
exit 0
