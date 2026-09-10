# 特殊作业评分智能体 · Docker 部署包（仅智能体）

Java 评分后端已在服务器 8081 端口部署好，本包**只部署智能体**，并**内置一个 MySQL 容器**存会话记忆，无需额外数据库配置。

| 服务 | 端口 | 说明 |
|---|---|---|
| `agent-backend` | 8082（对外） | FastAPI + LangGraph 智能体，Dify 兼容接口，调用大模型 + Java 评分后端 |
| `mysql` | 不对外 | 内置 MySQL，只存智能体会话记忆（`agent_memory`） |

前端访问 `http://<服务器IP>:8082/v1/chat-messages`，鉴权用 Bearer Key。

---

## 一、前置条件

1. 服务器已装 **Docker** 和 **Docker Compose v2**。
2. **Java 评分后端已在本机 8081 端口运行**（本包不包含、不部署 Java）。
3. 其余（MySQL、大模型、鉴权）都在包里配好了默认值，基本开箱即用。

---

## 二、部署步骤

### 1. 配置环境变量（通常只需改一个）

```bash
cd special-ops-deploy
cp .env.example .env
vim .env
```

`.env` 关键项（其余都有默认值，可不改）：

| 变量 | 说明 |
|---|---|
| `JAVA_BACKEND_URL` | Java 评分后端地址。默认 `http://172.17.0.1:8081`（Docker 网桥网关，指向宿主机）；不通就改 `docker network inspect bridge` 查到的网关 IP 或服务器内网 IP |
| `MYSQL_ROOT_PASSWORD` | 内置 MySQL 的密码，已给默认值，一般不用改 |
| `LLM_API_KEY` / `LLM_MODEL` | 阿里云百炼大模型（默认已填好） |
| `AUTH_API_KEYS` | 前端鉴权 Bearer Key（默认已填好） |

> 内置 MySQL 只存智能体会话记忆，和服务器上已有的 MySQL、Java 的业务库 `admin_new` 完全无关、互不影响。

### 2. 启动

```bash
docker compose up -d --build
```

首次启动会拉取 `mysql:8.0` 和 `python:3.13-slim` 镜像，需稍等。

### 3. 验证

```bash
# 健康检查
curl http://127.0.0.1:8082/health
# 期望：{"status":"ok"}

# 带鉴权对话（blocking）
curl -X POST http://127.0.0.1:8082/v1/chat-messages \
  -H "Authorization: Bearer app-50b15bd5240cf16958ab7f6e7d194e1f" \
  -H "Content-Type: application/json" \
  -d '{"query":"特殊作业评分总览","response_mode":"blocking","user":"u_10001"}'
```

---

## 三、前端接入

- 地址：`http://<服务器IP>:8082`
- 接口：`POST /v1/chat-messages`
- 鉴权头：`Authorization: Bearer <AUTH_API_KEYS 里的 key>`
- 请求体（Dify 标准格式）：

```json
{
  "query": "特殊作业评分总览",
  "inputs": {},
  "response_mode": "streaming",
  "conversation_id": "",
  "user": "u_10001"
}
```

响应为标准 Dify SSE / blocking 格式（`message` / `message_end` / `error` / `ping`）。

---

## 四、常见问题

1. **智能体调不到 Java（回答显示"评分数据服务暂时不可用"）**
   先确认宿主机 8081 上 Java 正常：`curl -X POST http://127.0.0.1:8081/systemScore/evaluate/detail -H "Content-Type: application/json" -d '{"modules":["special"]}'`。
   若宿主机通、容器不通，则是网关地址不对：运行 `docker network inspect bridge --format '{{(index .IPAM.Config 0).Gateway}}'` 拿到网关 IP，把 `.env` 的 `JAVA_BACKEND_URL` 改成 `http://<网关IP>:8081`，再 `docker compose up -d`。

2. **会话记忆数据会丢吗？**
   不会。内置 MySQL 数据挂在 `mysql-data` 卷上，`docker compose down` 不丢数据；只有 `docker compose down -v` 才会清空。

3. **大模型调用报错**
   确认 `LLM_API_KEY` 有效，且百炼已开通 `qwen3-vl-235b-a22b-instruct`。

4. **改配置后生效**
   ```bash
   docker compose up -d --build
   ```

5. **查看日志**
   ```bash
   docker compose logs -f agent-backend
   docker compose logs -f mysql
   ```

---

## 五、目录结构

```
special-ops-deploy/
├── docker-compose.yml
├── .env.example
├── README.md
└── agent-backend/
    ├── Dockerfile
    ├── .dockerignore
    ├── pyproject.toml
    ├── app/
    └── config/
```
