#!/usr/bin/env bash
# One-time hardening + Docker install for a fresh Ubuntu 24.04 LTS VPS. Run as root:
#   curl -fsSL <raw url>/deploy/server-setup.sh | bash     (or copy it over and: bash server-setup.sh)
set -euo pipefail

apt-get update && apt-get -y upgrade
apt-get install -y ca-certificates curl git ufw fail2ban unattended-upgrades

# Automatic security updates
dpkg-reconfigure -f noninteractive unattended-upgrades

# Firewall: SSH + web only (Postgres/Redis are never exposed)
ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 443/udp
ufw --force enable

# 2 GB swap so a small VPS survives image builds and spikes
if ! swapon --show | grep -q /swapfile; then
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

# Docker Engine + compose plugin (official convenience script)
if ! command -v docker >/dev/null; then
  curl -fsSL https://get.docker.com | sh
fi
systemctl enable --now docker

# Non-root deploy user that can run docker
id deploy >/dev/null 2>&1 || adduser --disabled-password --gecos "" deploy
usermod -aG docker deploy
mkdir -p /home/deploy/.ssh && cp ~/.ssh/authorized_keys /home/deploy/.ssh/ 2>/dev/null || true
chown -R deploy:deploy /home/deploy/.ssh

# SSH: keys only, no root login (make sure your key works for 'deploy' BEFORE logging out)
sed -i 's/^#\?PasswordAuthentication .*/PasswordAuthentication no/' /etc/ssh/sshd_config
sed -i 's/^#\?PermitRootLogin .*/PermitRootLogin no/' /etc/ssh/sshd_config
systemctl reload ssh

echo "Done. Log in as: ssh deploy@<server-ip>"
