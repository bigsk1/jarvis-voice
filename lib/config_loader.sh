#!/bin/bash
# Configuration loader for Jarvis Voice Assistant (Bash)

# Get the project root directory (assumes this file is in lib/)
get_project_root() {
    echo "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
}

# Load environment file
load_config() {
    local mode="${1:-cloud}"
    local project_root="$(get_project_root)"
    local config_file="$project_root/config/${mode}.env"
    
    if [ ! -f "$config_file" ]; then
        echo "❌ Config file not found: $config_file" >&2
        return 1
    fi
    
    # Export variables from config file
    set -a  # automatically export all variables
    source "$config_file"
    set +a
    
    return 0
}

# Get config value with optional default
get_config() {
    local key="$1"
    local default="${2:-}"
    echo "${!key:-$default}"
}

