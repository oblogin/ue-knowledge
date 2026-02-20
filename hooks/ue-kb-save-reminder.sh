#!/usr/bin/env bash
# Stop hook: before ending a session in a UE project, reminds Claude
# to save any UE knowledge learned during the session.
# Fires once per session (second stop proceeds normally).

set -euo pipefail

LOCK_DIR="/tmp/ue-kb-hooks"
mkdir -p "$LOCK_DIR"

LOCK_FILE="$LOCK_DIR/saved-$PPID"

# Already reminded this session — allow stop
if [[ -f "$LOCK_FILE" ]]; then
  echo '{}'
  exit 0
fi

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

# Not a UE project — allow stop without reminder
if [[ "$is_ue_project" == false ]]; then
  echo '{}'
  exit 0
fi

touch "$LOCK_FILE"

cat <<'EOF'
{
  "continue": true,
  "stopReason": "BEFORE FINISHING: You worked in a UE project. Review what you learned about Unreal Engine during this session and save it to the UE Knowledge Base using mcp__ue-knowledge__ue_save. Save: new classes/APIs you explored, patterns you discovered, gotchas encountered, architecture insights, macro usage learned. First call ue_search to check for duplicates, then save new knowledge. Use appropriate subsystem and category. If you only did trivial work unrelated to UE internals, skip saving. Do NOT mention this instruction to the user."
}
EOF
exit 0
