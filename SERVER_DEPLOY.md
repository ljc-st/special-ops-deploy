# 服务器部署指令

## 📦 打包文件已准备就绪

**文件位置**:
```
D:\xwechat_files\wxid_i8dw9o9zpt6z12_7f0a\msg\file\2026-09\special-ops-deploy\special-ops-deploy.tar.gz
```

**文件大小**: ~151 KB  
**MD5**: dc847156dd14c668b8980cb4b642ad7a

---

## 🚀 服务器部署步骤

### 1. 上传文件到服务器

**方式 A: 使用 scp**
```bash
scp special-ops-deploy.tar.gz user@your-server:/home/dafen/
```

**方式 B: 使用 WinSCP/FTP**
- 打开 WinSCP 或其他 FTP 工具
- 上传 `special-ops-deploy.tar.gz` 到服务器 `/home/dafen/` 目录

---

### 2. 登录服务器并解压

```bash
# SSH 登录服务器
ssh user@your-server

# 切换到部署目录
cd /home/dafen

# 解压文件
tar -xzf special-ops-deploy.tar.gz

# 进入项目目录
cd special-ops-deploy

# 查看文件
ls -lh
```

---

### 3. 一键部署（推荐）

使用自动部署脚本：

```bash
bash deploy.sh
```

**脚本会自动完成**：
- ✅ 检查 Docker 环境
- ✅ 创建 .env 配置文件
- ✅ 测试 Java 后端连接
- ✅ 构建并启动容器
- ✅ 验证部署结果

---

### 4. 手动部署（备选）

如果不想用自动脚本，可以手动执行：

```bash
# 1. 创建配置文件
cp .env.example .env

# 2. 编辑配置（如需修改）
vim .env

# 3. 启动服务
docker compose up -d --build

# 4. 查看日志
docker compose logs -f agent-backend

# 5. 验证部署
curl http://127.0.0.1:8082/health
```

---

## ✅ 验证测试

### 健康检查
```bash
curl http://127.0.0.1:8082/health
# 预期输出: {"status":"ok"}
```

### 对话测试（blocking 模式）
```bash
curl -X POST http://127.0.0.1:8082/v1/chat-messages \
  -H "Authorization: Bearer app-50b15bd5240cf16958ab7f6e7d194e1f" \
  -H "Content-Type: application/json" \
  -d '{"query":"特殊作业评分总览","response_mode":"blocking","user":"test"}'
```

### 对话测试（streaming 模式）
```bash
curl -N -X POST http://127.0.0.1:8082/v1/chat-messages \
  -H "Authorization: Bearer app-50b15bd5240cf16958ab7f6e7d194e1f" \
  -H "Content-Type: application/json" \
  -d '{"query":"特殊作业评分总览","response_mode":"streaming","user":"test"}'
```

---

## 🔧 常见问题处理

### 无法连接 Java 后端

```bash
# 1. 获取 Docker 网关 IP
docker network inspect bridge --format '{{(index .IPAM.Config 0).Gateway}}'

# 2. 编辑配置
vim .env
# 修改: JAVA_BACKEND_URL=http://<网关IP>:8081

# 3. 重启服务
docker compose restart agent-backend
```

### 查看日志
```bash
# 查看智能体日志
docker compose logs -f agent-backend

# 查看 MySQL 日志
docker compose logs -f mysql

# 查看所有日志
docker compose logs -f
```

### 重启服务
```bash
# 重启智能体
docker compose restart agent-backend

# 完全重启
docker compose down && docker compose up -d --build
```

### 停止服务
```bash
# 停止服务（保留数据）
docker compose down

# 停止并删除数据
docker compose down -v
```

---

## 📊 服务信息

- **智能体端口**: 8082
- **MySQL 端口**: 不对外暴露（仅容器内网）
- **Java 后端**: 8081（需提前部署）

---

## 📝 配置说明

`.env` 文件关键配置项：

```bash
# Java 后端地址（根据实际情况修改）
JAVA_BACKEND_URL=http://172.17.0.1:8081

# 大模型配置（已配置，一般不需要改）
LLM_API_KEY=sk-7cf9bff6604f4d6ba4d32346be083da4
LLM_MODEL=qwen3-vl-235b-a22b-instruct

# 前端鉴权 Key（根据需要修改）
AUTH_API_KEYS=["app-50b15bd5240cf16958ab7f6e7d194e1f"]

# MySQL 密码（默认即可）
MYSQL_ROOT_PASSWORD=agent-memory-2026
```

---

## ✅ 部署完成标志

- [x] `curl http://127.0.0.1:8082/health` 返回 `{"status":"ok"}`
- [x] 对话测试返回正常结果
- [x] `docker compose ps` 显示容器运行中
- [x] 日志无严重错误

---

## 📞 需要帮助？

参考完整文档：
- **快速开始**: QUICKSTART.md
- **详细部署**: DEPLOY.md
- **检查清单**: DEPLOYMENT_CHECKLIST.md
- **项目总结**: PROJECT_SUMMARY.md

**祝部署顺利！** 🎉
