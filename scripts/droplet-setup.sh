#!/bin/bash
# One-time setup for DigitalOcean droplet
# Run as root: curl -sSL <raw-url> | bash

set -euo pipefail

echo "=== Installing Docker ==="
apt-get update
apt-get install -y docker.io
systemctl enable docker
systemctl start docker

echo "=== Creating deploy user ==="
useradd -m -s /bin/bash -G docker deploy
mkdir -p /home/deploy/.ssh
cp /root/.ssh/authorized_keys /home/deploy/.ssh/authorized_keys
chown -R deploy:deploy /home/deploy/.ssh
chmod 700 /home/deploy/.ssh
chmod 600 /home/deploy/.ssh/authorized_keys

echo "=== Creating Docker volume ==="
docker volume create siege_data

echo "=== Setting up firewall ==="
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

echo "=== Done ==="
echo "Droplet is ready. Add these GitHub secrets:"
echo "  DROPLET_IP          - this server's IP"
echo "  DROPLET_SSH_KEY     - private key matching /home/deploy/.ssh/authorized_keys"
echo "  SIEGE_ANTHROPIC_API_KEY  - your Anthropic API key"
echo "  SIEGE_JWT_SECRET_KEY     - JWT secret for auth"
