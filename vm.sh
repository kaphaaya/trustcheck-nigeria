#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# TrustCheck Nigeria — Azure VM Control Script
# Usage:
#   ./vm.sh start    → Start VM + launch containers
#   ./vm.sh stop     → Stop containers + deallocate VM (no cost)
#   ./vm.sh status   → Show VM and container status
#   ./vm.sh logs     → Tail live container logs
# ─────────────────────────────────────────────────────────────────────────────

# ── CONFIG — edit these ──────────────────────────────────────────────────────
RESOURCE_GROUP="trustcheck-rg"
VM_NAME="trustcheck-vm"
VM_USER="azureuser"
# Get your VM's public IP from Azure Portal or: az vm show -d -g $RESOURCE_GROUP -n $VM_NAME --query publicIps -o tsv
VM_IP=""   # e.g. "20.123.45.67" — fill this in
SSH_KEY="~/.ssh/id_rsa"   # path to your SSH private key
PROJECT_DIR="~/trustcheck"   # where docker-compose.yml lives on the VM
# ─────────────────────────────────────────────────────────────────────────────

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

check_deps() {
    if ! command -v az &> /dev/null; then
        echo -e "${RED}Azure CLI not found. Install: https://aka.ms/installazurecliwindows${NC}"
        exit 1
    fi
}

get_vm_ip() {
    echo -e "${YELLOW}Fetching VM public IP...${NC}"
    VM_IP=$(az vm show -d -g "$RESOURCE_GROUP" -n "$VM_NAME" --query publicIps -o tsv 2>/dev/null)
    if [ -z "$VM_IP" ]; then
        echo -e "${RED}Could not retrieve VM IP. Is the VM running?${NC}"
        exit 1
    fi
    echo -e "${GREEN}VM IP: $VM_IP${NC}"
}

ssh_cmd() {
    ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no "$VM_USER@$VM_IP" "$1"
}

case "$1" in

  start)
    check_deps
    echo -e "${YELLOW}▶ Starting Azure VM: $VM_NAME...${NC}"
    az vm start --resource-group "$RESOURCE_GROUP" --name "$VM_NAME"
    echo -e "${GREEN}✅ VM started.${NC}"

    echo -e "${YELLOW}⏳ Waiting 20s for VM to be SSH-ready...${NC}"
    sleep 20

    get_vm_ip

    echo -e "${YELLOW}🐳 Starting Docker containers...${NC}"
    ssh_cmd "cd $PROJECT_DIR && docker compose up -d"

    echo ""
    echo -e "${GREEN}✅ TrustCheck Nigeria is LIVE at: http://$VM_IP${NC}"
    echo -e "${GREEN}   API health: http://$VM_IP/api/health${NC}"
    ;;

  stop)
    check_deps

    # If VM_IP not set, try to fetch it before stopping
    if [ -z "$VM_IP" ]; then
        get_vm_ip 2>/dev/null || true
    fi

    if [ -n "$VM_IP" ]; then
        echo -e "${YELLOW}🐳 Stopping Docker containers gracefully...${NC}"
        ssh_cmd "cd $PROJECT_DIR && docker compose down" 2>/dev/null || true
    fi

    echo -e "${YELLOW}⏹  Deallocating VM (stops billing)...${NC}"
    az vm deallocate --resource-group "$RESOURCE_GROUP" --name "$VM_NAME"
    echo -e "${GREEN}✅ VM deallocated. You are no longer being charged for compute.${NC}"
    echo -e "${YELLOW}   Note: Storage costs continue (minimal — a few cents/month).${NC}"
    ;;

  status)
    check_deps
    echo -e "${YELLOW}── VM Status ──────────────────────────────────${NC}"
    az vm show -d -g "$RESOURCE_GROUP" -n "$VM_NAME" \
        --query "{Name:name, State:powerState, IP:publicIps}" -o table

    # Try to show container status if VM is running
    VM_STATE=$(az vm show -d -g "$RESOURCE_GROUP" -n "$VM_NAME" --query powerState -o tsv 2>/dev/null)
    if [[ "$VM_STATE" == *"running"* ]]; then
        get_vm_ip
        echo -e "${YELLOW}── Container Status ────────────────────────────${NC}"
        ssh_cmd "docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'" 2>/dev/null || true
    fi
    ;;

  logs)
    check_deps
    get_vm_ip
    echo -e "${YELLOW}📋 Tailing container logs (Ctrl+C to stop)...${NC}"
    ssh_cmd "cd $PROJECT_DIR && docker compose logs -f --tail=50"
    ;;

  *)
    echo "Usage: $0 {start|stop|status|logs}"
    echo ""
    echo "  start   → Start VM + Docker containers"
    echo "  stop    → Stop containers + deallocate VM (no Azure compute cost)"
    echo "  status  → Show VM power state and container health"
    echo "  logs    → Stream live container logs"
    exit 1
    ;;
esac
