#!/usr/bin/env bash
# Rancher Desktop（macOS）为 dockerd 写入 dns + registry-mirrors，缓解 Hub/镜像站拉取失败。
# dns 用于避免公司路由 DNS（如 192.168.x.1）在容器/构建拉镜像时出现 i/o timeout。
# 使用前请在 Rancher Desktop → Preferences → Container Engine 中选择 dockerd (moby)。
# 执行后请完全退出并重新打开 Rancher Desktop，再运行 docker compose pull。

set -euo pipefail
RD_DOCKER_DIR="${HOME}/Library/Application Support/rancher-desktop/lima/_config/docker"
DAEMON="${RD_DOCKER_DIR}/daemon.json"

mkdir -p "${RD_DOCKER_DIR}"

if [[ -f "${DAEMON}" ]]; then
  echo "已存在 ${DAEMON}，请手动合并 dns 与 registry-mirrors（参考项目内 docker/daemon.json.example），勿直接覆盖。"
  echo "当前内容："
  cat "${DAEMON}"
  exit 1
fi

cat > "${DAEMON}" << 'EOF'
{
  "dns": ["223.5.5.5", "119.29.29.29", "8.8.8.8"],
  "registry-mirrors": [
    "https://docker.m.daocloud.io",
    "https://docker.xuanyuan.me",
    "https://docker.1ms.run",
    "https://hub.rat.dev"
  ]
}
EOF

echo "已写入: ${DAEMON}"
cat "${DAEMON}"
echo ""
echo "下一步：退出并重启 Rancher Desktop，然后执行: docker pull postgres:14"
