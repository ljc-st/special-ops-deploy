# 特殊作业评分智能体 - 快速部署指南

## 📦 项目已准备就绪

所有代码已完成调整和优化，可以直接部署使用！

## 🎯 核心更新

✅ **接口适配完成** - 支持新版评分接口规范 v3  
✅ **兼容性设计** - 同时支持新旧两种格式  
✅ **Git 仓库初始化** - 4 个提交，清晰的版本历史  
✅ **完整文档** - README、DEPLOY、CHANGELOG、部署检查清单  
✅ **.env 配置** - 已创建并配置好默认值  

## 🚀 立即部署（3 步）

### 本地测试
```bash
# 1. 确认配置
cat .env

# 2. 启动服务
docker compose up -d --build

# 3. 验证
curl http://127.0.0.1:8082/health
```

### 服务器部署
```bash
# 1. 打包项目（在当前目录执行）
cd ..
tar -czf special-ops-deploy.tar.gz special-ops-deploy/

# 2. 上传到服务器（示例）
scp special-ops-deploy.tar.gz user@server:/home/dafen/

# 3. 服务器上解压并部署
ssh user@server
cd /home/dafen
tar -xzf special-ops-deploy.tar.gz
cd special-ops-deploy
cp .env.example .env
docker compose up -d --build
curl http://127.0.0.1:8082/health
```

## 📝 测试命令

```bash
# 健康检查
curl http://127.0.0.1:8082/health

# 评分总览
curl -X POST http://127.0.0.1:8082/v1/chat-messages \
  -H "Authorization: Bearer app-50b15bd5240cf16958ab7f6e7d194e1f" \
  -H "Content-Type: application/json" \
  -d '{"query":"特殊作业评分总览","response_mode":"blocking","user":"test"}'

# 流式对话
curl -N -X POST http://127.0.0.1:8082/v1/chat-messages \
  -H "Authorization: Bearer app-50b15bd5240cf16958ab7f6e7d194e1f" \
  -H "Content-Type: application/json" \
  -d '{"query":"特殊作业评分总览","response_mode":"streaming","user":"test"}'
```

## 📚 文档索引

- **README.md** - 项目概述和快速开始
- **DEPLOY.md** - 详细部署指南（环境要求、配置说明、API 文档）
- **CHANGELOG.md** - 更新日志
- **DEPLOYMENT_CHECKLIST.md** - 部署检查清单（本文件）
- **.env.example** - 环境变量模板

## ⚙️ 配置说明

已在 .env 中配置好默认值，通常只需修改：

```bash
# 如果 Java 后端不在默认网关地址，修改这个
JAVA_BACKEND_URL=http://172.17.0.1:8081

# 如果需要更换大模型 API Key
LLM_API_KEY=sk-7cf9bff6604f4d6ba4d32346be083da4

# 如果需要更换前端鉴权 Key
AUTH_API_KEYS=["app-50b15bd5240cf16958ab7f6e7d194e1f"]
```

## 🔧 常见问题

### 无法连接 Java 后端
```bash
# 获取正确的网关 IP
docker network inspect bridge --format '{{(index .IPAM.Config 0).Gateway}}'
# 更新 .env 中的 JAVA_BACKEND_URL，然后重启
docker compose restart agent-backend
```

### 查看日志
```bash
docker compose logs -f agent-backend
```

### 完全重启
```bash
docker compose down && docker compose up -d --build
```

## ✅ 部署完成标志

- [ ] `curl http://127.0.0.1:8082/health` 返回 `{"status":"ok"}`
- [ ] 对话测试返回正常评分结果
- [ ] 日志无 ERROR 错误
- [ ] 可以通过前端正常访问

## 📞 需要帮助？

参考详细文档：
- 部署问题 → DEPLOY.md
- 功能说明 → README.md  
- 逐步检查 → DEPLOYMENT_CHECKLIST.md

---

**项目状态**: ✅ 已完成，可以部署  
**最后更新**: 2026-09-10  
**Git 提交**: 4 个提交，干净的工作树
