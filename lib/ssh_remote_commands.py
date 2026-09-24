"""Built-in SSH commands shared by execution and the Web approval description."""

SSH_TEST_COMMAND = "echo 'SSH connection successful' && hostname && uname -a"
SSH_APT_UPDATE_COMMAND = "apt update"
SSH_APT_CHECK_COMMAND = "apt list --upgradable 2>/dev/null | grep -v 'Listing'"
SSH_APT_UPGRADE_COMMAND = "DEBIAN_FRONTEND=noninteractive apt upgrade -y"

SSH_COMMAND_TIMEOUT_SECONDS = 180
SSH_APT_UPDATE_TIMEOUT_SECONDS = 180
SSH_APT_CHECK_TIMEOUT_SECONDS = 30
SSH_APT_UPGRADE_TIMEOUT_SECONDS = 600
