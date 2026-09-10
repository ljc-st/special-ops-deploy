#!/bin/bash
# 特殊作业评分智能体 - 服务器部署脚本
# 使用方法：在服务器上执行 bash deploy.sh

set -e  # 遇到错误立即停止

echo "=========================================="
echo "特殊作业评分智能体 - 自动部署脚本"
echo "=========================================="
echo ""

# 颜色定义
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# 检查是否在正确的目录
if [ ! -f "docker-compose.yml" ]; then
    echo -e "${RED}错误: 请在 special-ops-deploy 目录下运行此脚本${NC}"
    exit 1
fi

echo -e "${YELLOW}步骤 1/5: 检查环境...${NC}"

# 检查 Docker
if ! command -v docker &> /dev/null; then
    echo -e "${RED}错误: 未安装 Docker${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Docker 已安装: $(docker --version)${NC}"

# 检查 Docker Compose
if ! docker compose version &> /dev/null; then
    echo -e "${RED}错误: 未安装 Docker Compose v2${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Docker Compose 已安装: $(docker compose version)${NC}"

echo ""
echo -e "${YELLOW}步骤 2/5: 配置环境变量...${NC}"

# 检查 .env 文件
if [ ! -f ".env" ]; then
    echo -e "${YELLOW}未找到 .env 文件，从模板创建...${NC}"
    cp .env.example .env
    echo -e "${GREEN}✓ 已创建 .env 文件${NC}"
    echo -e "${YELLOW}提示: 如需修改配置，请编辑 .env 文件后重新运行${NC}"
else
    echo -e "${GREEN}✓ .env 文件已存在${NC}"
fi

# 显示关键配置
echo ""
echo "当前配置："
grep "^JAVA_BACKEND_URL=" .env || echo "JAVA_BACKEND_URL=未设置"
grep "^LLM_MODEL=" .env || echo "LLM_MODEL=未设置"
echo ""

echo -e "${YELLOW}步骤 3/5: 检查 Java 后端连接...${NC}"

# 提取 JAVA_BACKEND_URL
JAVA_URL=$(grep "^JAVA_BACKEND_URL=" .env | cut -d'=' -f2)
if [ -z "$JAVA_URL" ]; then
    echo -e "${YELLOW}警告: JAVA_BACKEND_URL 未配置${NC}"
else
    echo "测试连接: $JAVA_URL"
    # 注意：这里测试的是宿主机的连接，容器内的连接可能不同
    if curl -s --max-time 3 "$JAVA_URL/health" &> /dev/null || \
       curl -s --max-time 3 "$JAVA_URL/systemScore/parks" &> /dev/null; then
        echo -e "${GREEN}✓ Java 后端连接正常${NC}"
    else
        echo -e "${YELLOW}警告: 无法连接到 Java 后端，请检查 JAVA_BACKEND_URL 配置${NC}"
        echo -e "${YELLOW}提示: 容器启动后可能需要调整网关 IP${NC}"
    fi
fi

echo ""
echo -e "${YELLOW}步骤 4/5: 启动服务...${NC}"

# 停止旧容器
if docker compose ps -q &> /dev/null && [ -n "$(docker compose ps -q)" ]; then
    echo "检测到运行中的容器，停止旧服务..."
    docker compose down
fi

# 构建并启动
echo "构建并启动容器（首次启动需要下载镜像，可能需要几分钟）..."
docker compose up -d --build

echo ""
echo -e "${YELLOW}步骤 5/5: 验证部署...${NC}"

# 等待服务启动
echo "等待服务启动..."
for i in {1..30}; do
    if curl -s --max-time 2 http://127.0.0.1:8082/health &> /dev/null; then
        echo -e "${GREEN}✓ 服务启动成功！${NC}"
        break
    fi
    if [ $i -eq 30 ]; then
        echo -e "${RED}错误: 服务启动超时${NC}"
        echo "查看日志："
        docker compose logs --tail=50 agent-backend
        exit 1
    fi
    sleep 2
    echo -n "."
done

echo ""
echo ""
echo -e "${GREEN}=========================================="
echo "部署完成！"
echo "==========================================${NC}"
echo ""
echo "服务信息："
echo "  智能体地址: http://127.0.0.1:8082"
echo "  健康检查: http://127.0.0.1:8082/health"
echo ""
echo "快速测试："
echo '  curl http://127.0.0.1:8082/health'
echo ""
echo '  curl -X POST http://127.0.0.1:8082/v1/chat-messages \'
echo '    -H "Authorization: Bearer app-50b15bd5240cf16958ab7f6e7d194e1f" \'
echo '    -H "Content-Type: application/json" \'
echo "    -d '{\"query\":\"特殊作业评分总览\",\"response_mode\":\"blocking\",\"user\":\"test\"}'"
echo ""
echo "常用命令："
echo "  查看日志: docker compose logs -f agent-backend"
echo "  查看状态: docker compose ps"
echo "  重启服务: docker compose restart agent-backend"
echo "  停止服务: docker compose down"
echo ""
echo -e "${GREEN}祝使用愉快！${NC}"
