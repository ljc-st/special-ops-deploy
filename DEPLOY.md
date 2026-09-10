# 特殊作业评分智能体 - 部署指南

## 项目概述

本项目为特殊作业评分智能体的 Docker 容器化部署包，提供 Dify 兼容的对话接口。

- **智能体后端**: FastAPI + LangGraph，调用大模型和 Java 评分后端
- **内置 MySQL**: 存储智能体会话记忆
- **部署端口**: 8082（对外）

## 部署架构

```
前端 → Agent Backend (8082) → Java Backend (8081)
                ↓
          MySQL (内网)
```

## 快速部署

### 1. 环境要求

- Docker 20.10+
- Docker Compose v2+
- Java 评分后端已在 8081 端口运行

### 2. 配置环境变量

```bash
cd special-ops-deploy
cp .env.example .env
vim .env
```

关键配置项：

| 变量 | 说明 | 默认值 |
|---|---|---|
| `JAVA_BACKEND_URL` | Java 评分后端地址 | `http://172.17.0.1:8081` |
| `LLM_API_KEY` | 阿里云百炼 API Key | 已配置 |
| `LLM_MODEL` | 大模型名称 | `qwen3-vl-235b-a22b-instruct` |
| `AUTH_API_KEYS` | 前端鉴权 Key | `["app-50b15bd5240cf16958ab7f6e7d194e1f"]` |
| `MYSQL_ROOT_PASSWORD` | MySQL 密码 | `agent-memory-2026` |

> **注意**: `JAVA_BACKEND_URL` 使用 Docker 网桥网关 IP，如果连接失败，运行以下命令获取网关 IP：
> ```bash
> docker network inspect bridge --format '{{(index .IPAM.Config 0).Gateway}}'
> ```

### 3. 启动服务

```bash
docker compose up -d --build
```

### 4. 验证部署

```bash
# 健康检查
curl http://127.0.0.1:8082/health

# 对话测试（blocking 模式）
curl -X POST http://127.0.0.1:8082/v1/chat-messages \
  -H "Authorization: Bearer app-50b15bd5240cf16958ab7f6e7d194e1f" \
  -H "Content-Type: application/json" \
  -d '{"query":"特殊作业评分总览","response_mode":"blocking","user":"u_10001"}'

# 流式对话测试
curl -N -X POST http://127.0.0.1:8082/v1/chat-messages \
  -H "Authorization: Bearer app-50b15bd5240cf16958ab7f6e7d194e1f" \
  -H "Content-Type: application/json" \
  -d '{"query":"特殊作业评分总览","response_mode":"streaming","user":"u_10001"}'
```

## 前端接入

### 接口信息

- **Base URL**: `http://<服务器IP>:8082`
- **对话接口**: `POST /v1/chat-messages`
- **鉴权方式**: `Authorization: Bearer <AUTH_API_KEYS>`

### 请求格式

```json
{
  "query": "特殊作业评分总览",
  "inputs": {},
  "response_mode": "streaming",  // 或 "blocking"
  "conversation_id": "",         // 可选，续接会话
  "user": "u_10001"
}
```

### 响应格式

**Streaming 模式** (SSE):
```
event: message
data: {"event":"message","task_id":"...","message_id":"...","conversation_id":"...","answer":"部分内容","created_at":1234567890}

event: message_end
data: {"event":"message_end","task_id":"...","message_id":"...","conversation_id":"...","metadata":{...}}
```

**Blocking 模式** (JSON):
```json
{
  "task_id": "...",
  "id": "...",
  "message_id": "...",
  "conversation_id": "...",
  "answer": "完整回答内容",
  "metadata": {...},
  "created_at": 1234567890
}
```

## 接口规范说明

当前版本已适配 **系统评分接口规范 v3**，主要变更：

### 评分项编号格式

- **新格式**: 字符串编码，如 `special-functionBuild-tszybbgnjsqkpg`
- **旧格式**: 数字编号，如 `1.1`, `2.3`, `3.5`（兼容）

### 统一状态枚举

| 状态 | 说明 |
|---|---|
| `PASS` | 通过，满足评分标准 |
| `BUSINESS_ISSUE` | 存在业务问题，未满足标准 |
| `DATA_INSUFFICIENT` | 数据不足，无法评分 |
| `CALCULATION_ERROR` | 计算异常 |

### 主要字段映射

| 字段 | 说明 |
|---|---|
| `itemNo` | 评分项编号 |
| `detailText` | 详情文本 |
| `status` | 统一状态 |
| `dimensionCode` | 维度编码 |
| `dimensionName` | 维度名称 |
| `moduleCode` | 模块编码 |
| `moduleName` | 模块名称 |

## 常见问题

### 1. 智能体无法连接 Java 后端

**症状**: 回答显示"评分数据服务暂时不可用"

**解决方案**:
```bash
# 1. 确认宿主机 Java 后端正常
curl -X POST http://127.0.0.1:8081/systemScore/evaluate/detail \
  -H "Content-Type: application/json" \
  -d '{"modules":["special"]}'

# 2. 检查 Docker 网桥网关 IP
docker network inspect bridge --format '{{(index .IPAM.Config 0).Gateway}}'

# 3. 更新 .env 中的 JAVA_BACKEND_URL
# JAVA_BACKEND_URL=http://<网关IP>:8081

# 4. 重启服务
docker compose up -d
```

### 2. 会话记忆数据持久化

会话数据存储在 Docker volume `mysql-data` 中，执行 `docker compose down` 不会丢失数据。

**清空会话数据**:
```bash
docker compose down -v  # 删除 volume
```

### 3. 大模型调用失败

**检查项**:
- LLM_API_KEY 是否有效
- 百炼是否已开通 `qwen3-vl-235b-a22b-instruct` 模型
- 网络是否可访问 `https://dashscope.aliyuncs.com`

### 4. 查看日志

```bash
# 查看智能体日志
docker compose logs -f agent-backend

# 查看 MySQL 日志
docker compose logs -f mysql

# 查看所有日志
docker compose logs -f
```

### 5. 修改配置后生效

```bash
docker compose up -d --build
```

## 目录结构

```
special-ops-deploy/
├── docker-compose.yml          # Docker Compose 配置
├── .env.example                # 环境变量模板
├── .env                        # 实际环境变量（需创建）
├── README.md                   # 部署说明
├── CHANGELOG.md                # 更新日志
└── agent-backend/              # 智能体后端
    ├── Dockerfile              # 镜像构建文件
    ├── pyproject.toml          # Python 项目配置
    ├── app/                    # 应用代码
    │   ├── api/                # API 路由
    │   ├── graph/              # LangGraph 图逻辑
    │   ├── llm/                # 大模型客户端
    │   ├── tools/              # 工具和技能
    │   └── sse/                # SSE 流式响应
    └── config/                 # 配置文件
        ├── tools.yaml          # 工具注册表
        └── settings.yaml       # 应用设置
```

## 技术栈

- **后端框架**: FastAPI 0.115+
- **AI 编排**: LangGraph 0.2+
- **大模型**: 阿里云百炼（OpenAI 兼容）
- **数据库**: MySQL 8.0
- **容器化**: Docker + Docker Compose

## 维护命令

```bash
# 启动服务
docker compose up -d

# 停止服务
docker compose down

# 重启服务
docker compose restart agent-backend

# 查看运行状态
docker compose ps

# 进入容器
docker compose exec agent-backend bash
docker compose exec mysql mysql -uroot -p

# 更新镜像
docker compose build --no-cache
docker compose up -d
```

## 联系方式

如有问题，请联系开发团队。
