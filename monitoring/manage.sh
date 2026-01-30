#!/bin/bash
# Jarvis Monitoring Stack Manager

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Helper functions
print_info() {
    echo -e "${BLUE}ℹ ${NC} $1"
}

print_success() {
    echo -e "${GREEN}✓${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

print_error() {
    echo -e "${RED}✗${NC} $1"
}

print_header() {
    echo ""
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BLUE}  $1${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
}

# Functions
check_docker() {
    if ! command -v docker &> /dev/null; then
        print_error "Docker is not installed"
        exit 1
    fi
    
    if ! docker compose version &> /dev/null; then
        print_error "Docker Compose is not installed"
        exit 1
    fi
    
    print_success "Docker and Docker Compose are installed"
}

start_stack() {
    print_header "Starting Jarvis Monitoring Stack"
    
    check_docker
    
    print_info "Starting containers..."
    docker compose up -d
    
    echo ""
    print_info "Waiting for services to be ready..."
    sleep 5
    
    # Check service health
    if docker compose ps | grep -q "Up"; then
        print_success "Services started successfully!"
        echo ""
        show_status
        echo ""
        print_info "Access Grafana at: ${GREEN}http://localhost:3000${NC}"
        print_info "Username: ${YELLOW}admin${NC}"
        print_info "Password: ${YELLOW}jarvis_grafana_2025${NC}"
    else
        print_error "Some services failed to start"
        docker compose ps
    fi
}

stop_stack() {
    print_header "Stopping Jarvis Monitoring Stack"
    
    docker compose down
    print_success "Stack stopped"
}

restart_stack() {
    print_header "Restarting Jarvis Monitoring Stack"
    
    docker compose restart
    print_success "Stack restarted"
}

show_logs() {
    local service="${1:-}"
    
    if [ -z "$service" ]; then
        print_header "Showing All Logs (Ctrl+C to exit)"
        docker compose logs -f --tail=50
    else
        print_header "Showing $service Logs (Ctrl+C to exit)"
        docker compose logs -f --tail=50 "$service"
    fi
}

show_status() {
    print_header "Service Status"
    docker compose ps
    
    echo ""
    print_info "Service URLs:"
    echo "  Grafana:    http://localhost:3000"
    echo "  Prometheus: http://localhost:9090"
    echo "  Loki:       http://localhost:3100"
}

update_stack() {
    print_header "Updating Jarvis Monitoring Stack"
    
    print_info "Pulling latest images..."
    docker compose pull
    
    print_info "Recreating containers..."
    docker compose up -d
    
    print_success "Stack updated"
}

backup_data() {
    print_header "Backing Up Monitoring Data"
    
    local backup_dir="./backups"
    mkdir -p "$backup_dir"
    
    local timestamp=$(date +%Y%m%d_%H%M%S)
    
    print_info "Backing up Grafana data..."
    docker run --rm \
        -v monitoring_grafana-data:/data \
        -v "$PWD/$backup_dir":/backup \
        busybox tar czf "/backup/grafana-$timestamp.tar.gz" /data
    
    print_info "Backing up Loki data..."
    docker run --rm \
        -v monitoring_loki-data:/data \
        -v "$PWD/$backup_dir":/backup \
        busybox tar czf "/backup/loki-$timestamp.tar.gz" /data
    
    print_success "Backups saved to: $backup_dir/"
    ls -lh "$backup_dir"
}

clean_data() {
    print_warning "This will DELETE all monitoring data (logs, dashboards, metrics)"
    read -p "Are you sure? (yes/no): " confirm
    
    if [ "$confirm" = "yes" ]; then
        print_header "Cleaning Monitoring Data"
        
        docker compose down -v
        print_success "All data volumes removed"
    else
        print_info "Cancelled"
    fi
}

show_help() {
    cat << EOF
${BLUE}Jarvis Monitoring Stack Manager${NC}

Usage: $0 <command>

Commands:
  ${GREEN}start${NC}       Start the monitoring stack
  ${GREEN}stop${NC}        Stop the monitoring stack
  ${GREEN}restart${NC}     Restart the monitoring stack
  ${GREEN}status${NC}      Show service status
  ${GREEN}logs${NC}        Show logs (all services)
  ${GREEN}logs <svc>${NC}  Show logs for specific service
  ${GREEN}update${NC}      Update to latest images
  ${GREEN}backup${NC}      Backup Grafana & Loki data
  ${GREEN}clean${NC}       Remove all data (careful!)
  ${GREEN}help${NC}        Show this help message

Services:
  - grafana    : Visualization dashboards
  - loki       : Log storage
  - promtail   : Log shipper
  - prometheus : Metrics storage

Examples:
  $0 start
  $0 logs grafana
  $0 backup

EOF
}

# Main
case "${1:-}" in
    start)
        start_stack
        ;;
    stop)
        stop_stack
        ;;
    restart)
        restart_stack
        ;;
    status)
        show_status
        ;;
    logs)
        show_logs "${2:-}"
        ;;
    update)
        update_stack
        ;;
    backup)
        backup_data
        ;;
    clean)
        clean_data
        ;;
    help|--help|-h)
        show_help
        ;;
    *)
        print_error "Unknown command: ${1:-}"
        echo ""
        show_help
        exit 1
        ;;
esac

