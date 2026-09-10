# 特殊作业评分智能体 - 部署检查清单

## 部署前检查

### 1. 环境检查
- [ ] Docker 已安装（版本 20.10+）
- [ ] Docker Compose 已安装（v2+）
- [ ] Java 评分后端运行在 8081 端口
- [ ] 8082 端口未被占用

### 2. 配置检查
- [ ] 已复制 .env.example 为 .env
- [ ] 已配置 JAVA_BACKEND_URL
- [ ] 已配置 LLM_API_KEY（如需更换）
- [ ] 已配置 AUTH_API_KEYS（如需更换）

### 3. 网络检查
```bash
# 检查 Docker 网桥网关 IP
docker network inspect bridge --format '{{(index .IPAM.Config 0).Gateway}}'

# 检查 Java 后端连通性
curl -X POST http://127.0.0.1:8081/systemScore/evaluate/detail \
  -H "Content-Type: application/json" \
  -d '{"modules":["special"]}'
```

## 部署步骤

### 方式一：本地部署（Windows）

```powershell
# 1. 进入项目目录
cd D:\xwechat_files\wxid_i8dw9o9zpt6z12_7f0a\msg\file\2026-09\special-ops-deploy\special-ops-deploy

# 2. 确保 .env 文件已配置
cat .env

# 3. 启动服务
docker compose up -d --build

# 4. 查看日志
docker compose logs -f agent-backend

# 5. 验证部署
curl http://127.0.0.1:8082/health

# 6. 测试对话
curl -X POST http://127.0.0.1:8082/v1/chat-messages `
  -H "Authorization: Bearer app-50b15bd5240cf16958ab7f6e7d194e1f" `
  -H "Content-Type: application/json" `
  -d '{"query":"特殊作业评分总览","response_mode":"blocking","user":"u_10001"}'
```

### 方式二：服务器部署（Linux）

```bash
# 1. 上传项目到服务器
# 方式 A: 使用 git clone（如果已推送到远程仓库）
git clone <仓库地址> /home/dafen/special-ops-deploy
cd /home/dafen/special-ops-deploy

# 方式 B: 使用 scp/sftp 上传
# 在本地执行：
# tar -czf special-ops-deploy.tar.gz special-ops-deploy/
# scp special-ops-deploy.tar.gz user@server:/home/dafen/
# 
# 在服务器执行：
# cd /home/dafen
# tar -xzf special-ops-deploy.tar.gz
# cd special-ops-deploy

# 2. 配置环境变量
cp .env.example .env
vim .env

# 3. 启动服务
docker compose up -d --build

# 4. 查看日志
docker compose logs -f agent-backend

# 5. 验证部署
curl http://127.0.0.1:8082/health

# 6. 测试对话（blocking 模式）
curl -X POST http://127.0.0.1:8082/v1/chat-messages \
  -H "Authorization: Bearer app-50b15bd5240cf16958ab7f6e7d194e1f" \
  -H "Content-Type: application/json" \
  -d '{"query":"特殊作业评分总览","response_mode":"blocking","user":"u_10001"}'

# 7. 测试对话（streaming 模式）
curl -N -X POST http://127.0.0.1:8082/v1/chat-messages \
  -H "Authorization: Bearer app-50b15bd5240cf16958ab7f6e7d194e1f" \
  -H "Content-Type: application/json" \
  -d '{"query":"特殊作业评分总览","response_mode":"streaming","user":"u_10001"}'
```

## 验证测试

### 1. 健康检查
```bash
curl http://127.0.0.1:8082/health
# 预期输出: {"status":"ok"}
```

### 2. 评分总览测试
```bash
curl -X POST http://127.0.0.1:8082/v1/chat-messages \
  -H "Authorization: Bearer app-50b15bd5240cf16958ab7f6e7d194e1f" \
  -H "Content-Type: application/json" \
  -d '{"query":"特殊作业评分总览","response_mode":"blocking","user":"test_user"}'
```

### 3. 单项评估测试
```bash
curl -X POST http://127.0.0.1:8082/v1/chat-messages \
  -H "Authorization: Bearer app-50b15bd5240cf16958ab7f6e7d194e1f" \
  -H "Content-Type: application/json" \
  -d '{"query":"特殊作业报备功能建设情况","response_mode":"blocking","user":"test_user"}'
```

### 4. 扣分分析测试
```bash
curl -X POST http://127.0.0.1:8082/v1/chat-messages \
  -H "Authorization: Bearer app-50b15bd5240cf16958ab7f6e7d194e1f" \
  -H "Content-Type: application/json" \
  -d '{"query":"特殊作业哪些项扣分了","response_mode":"blocking","user":"test_user"}'
```

## 常见问题排查

### 问题1: 容器启动失败
```bash
# 查看日志
docker compose logs agent-backend

# 检查端口占用
netstat -ano | grep 8082  # Windows
lsof -i :8082             # Linux

# 重新构建
docker compose down
docker compose up -d --build
```

### 问题2: 无法连接 Java 后端
```bash
# 检查 Java 后端
curl http://127.0.0.1:8081/systemScore/evaluate/detail \
  -H "Content-Type: application/json" \
  -d '{"modules":["special"]}'

# 获取 Docker 网关 IP
docker network inspect bridge --format '{{(index .IPAM.Config 0).Gateway}}'

# 更新 .env 中的 JAVA_BACKEND_URL
# JAVA_BACKEND_URL=http://<网关IP>:8081

# 重启服务
docker compose restart agent-backend
```

### 问题3: 大模型调用失败
```bash
# 检查配置
grep LLM_ .env

# 测试 API Key
curl https://dashscope.aliyuncs.com/compatible-mode/v1/models \
  -H "Authorization: Bearer $LLM_API_KEY"

# 查看详细日志
docker compose logs -f agent-backend | grep -i error
```

### 问题4: 鉴权失败
```bash
# 检查 AUTH_API_KEYS 配置
grep AUTH_API_KEYS .env

# 确保请求头中的 Bearer token 与配置一致
# Authorization: Bearer app-50b15bd5240cf16958ab7f6e7d194e1f
```

## 监控命令

```bash
# 查看服务状态
docker compose ps

# 查看资源使用
docker stats special-ops-agent special-ops-mysql

# 查看实时日志
docker compose logs -f

# 只看智能体日志
docker compose logs -f agent-backend

# 只看 MySQL 日志
docker compose logs -f mysql

# 进入容器调试
docker compose exec agent-backend bash
docker compose exec mysql mysql -uroot -p
```

## 维护命令

```bash
# 重启服务
docker compose restart agent-backend

# 停止服务
docker compose down

# 停止并删除数据
docker compose down -v

# 查看会话列表
curl http://127.0.0.1:8082/v1/conversations

# 备份数据库
docker compose exec mysql mysqldump -uroot -p agent_memory > backup.sql

# 恢复数据库
docker compose exec -T mysql mysql -uroot -p agent_memory < backup.sql
```

## 部署完成标志

✅ 健康检查返回 `{"status":"ok"}`  
✅ 对话测试返回正常评分结果  
✅ 日志无 ERROR 级别错误  
✅ MySQL 连接正常  
✅ Java 后端连接正常  

## 交付清单

- [x] 代码适配新版接口规范
- [x] Git 仓库初始化完成
- [x] 项目文档完整（README, DEPLOY, CHANGELOG）
- [x] .env 配置文件已创建
- [x] Docker 配置文件已优化
- [x] 部署检查清单已提供
- [x] 测试命令已提供
- [x] 故障排查指南已提供

## 下一步

1. **本地测试**（可选）：
   ```bash
   docker compose up -d --build
   curl http://127.0.0.1:8082/health
   ```

2. **打包上传服务器**：
   ```bash
   tar -czf special-ops-deploy.tar.gz special-ops-deploy/
   # 上传到服务器 /home/dafen/
   ```

3. **服务器部署**：
   ```bash
   cd /home/dafen
   tar -xzf special-ops-deploy.tar.gz
   cd special-ops-deploy
   cp .env.example .env
   vim .env  # 修改配置
   docker compose up -d --build
   ```

4. **验证测试**：参照上述验证测试步骤

需要我帮你执行哪个步骤？
