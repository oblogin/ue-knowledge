import sys
import os
import json
import argparse
from pathlib import Path

# Add the project root to sys.path to find server.py
# Assuming this script is at skills/ue-analyze-gemini/scripts/ue_interface.py
project_root = Path(__file__).resolve().parent.parent.parent.parent
sys.path.append(str(project_root))

try:
    from server import KnowledgeDB, VALID_SUBSYSTEMS, VALID_CATEGORIES, VALID_KINDS
except ImportError:
    # If run from a different context, try modifying path differently
    # This fallback is for when running directly from the project root
    sys.path.append(str(Path.cwd()))
    try:
        from server import KnowledgeDB, VALID_SUBSYSTEMS, VALID_CATEGORIES, VALID_KINDS
    except ImportError as e:
        print(json.dumps({"error": f"Could not import server.py: {e}"}))
        sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description="Interface for UE Knowledge Base")
    parser.add_argument("command", help="Command to execute (status, search, save_class, etc.)")
    parser.add_argument("--args", help="JSON string of arguments for the command", default="{}")
    
    args = parser.parse_args()
    command = args.command
    try:
        command_args = json.loads(args.args)
    except json.JSONDecodeError:
        print(json.dumps({"error": "Invalid JSON arguments"}))
        return

    db = KnowledgeDB()
    
    try:
        result = None
        if command == "status":
            result = db.analysis_status(**command_args)
        elif command == "search":
            # Map search arguments to db.search or db.search_all
            if command_args.get("tables"):
                 result = db.search_all(**command_args)
            else:
                 rows, total = db.search(**command_args)
                 result = {"results": rows, "total": total}
        elif command == "save_class":
            result = db.save_class(**command_args)
        elif command == "save_function":
            result = db.save_function(**command_args)
        elif command == "save_property":
            result = db.save_property(**command_args)
        elif command == "save_entry": # mapping to db.save
            result = db.save(**command_args)
        elif command == "log_analysis":
            result = db.log_analysis(**command_args)
        elif command == "get_class":
            result = db.get_class(**command_args)
        elif command == "query_hierarchy":
            result = db.query_hierarchy(**command_args)
        else:
            result = {"error": f"Unknown command: {command}"}
        
        print(json.dumps(result, indent=2, default=str))

    except Exception as e:
        print(json.dumps({"error": str(e)}))
    finally:
        db.close()

if __name__ == "__main__":
    main()
