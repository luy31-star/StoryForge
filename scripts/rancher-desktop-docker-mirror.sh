#!/usr/bin/env bash
# Rancher Desktop（macOS）为 dockerd 写入 registry-mirrors，减轻访问 Docker Hub 超时。
# 使用前请在 Rancher Desktop → Preferences → Container Engine 中选择 dockerd (moby)。
# 执行后请完全退出并重新打开 Rancher Desktop，再运行 docker compose pull。

set -euo pipefail
RD_DOCKER_DIR="${HOME}/Library/Application Support/rancher-desktop/lima/_config/docker"
DAEMON="${RD_DOCKER_DIR}/daemon.json"

mkdir -p "${RD_DOCKER_DIR}"

if [[ -f "${DAEMON}" ]]; then
  echo "已存在 ${DAEMON}，请手动合并 registry-mirrors，避免覆盖其它配置。"
  echo "当前内容："
  cat "${DAEMON}"
  exit 1
fi

cat > "${DAEMON}" << 'EOF'
{
  "registry-mirrors": [
    "https://docker.m.daocloud.io",
    "https://docker.xuanyuan.me"
  ]
}
EOF

echo "已写入: ${DAEMON}"
cat "${DAEMON}"
echo ""
echo "下一步：退出并重启 Rancher Desktop，然后执行: docker pull postgres:14"
