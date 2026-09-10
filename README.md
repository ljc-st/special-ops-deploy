# 特殊作业评分智能体

基于 LangGraph 的智能评分对话系统，专注于特殊作业模块的评分查询与分析。

## 项目特点

- ✅ **Dify 兼容接口**: 支持 streaming 和 blocking 两种响应模式
- ✅ **智能技能编排**: 高频场景预定义为组合技能，提升响应效率
- ✅ **统一接口规范**: 适配最新的评分接口规范 v3
- ✅ **会话记忆**: MySQL 持久化存储，支持多轮对话上下文
- ✅ **Docker 部署**: 一键启动，内置 MySQL，无需额外配置

## 快速开始

```bash
# 1. 配置环境变量
cp .env.example .env
vim .env  # 修改 JAVA_BACKEND_URL 等配置

# 2. 启动服务
docker compose up -d --build

# 3. 验证部署
curl http://127.0.0.1:8082/health

# 4. 测试对话
curl -X POST http://127.0.0.1:8082/v1/chat-messages \
  -H "Authorization: Bearer app-50b15bd5240cf16958ab7f6e7d194e1f" \
  -H "Content-Type: application/json" \
  -d '{"query":"特殊作业评分总览","response_mode":"blocking","user":"u_10001"}'
```

## 项目结构

```
special-ops-deploy/
├── docker-compose.yml          # 服务编排配置
├── .env.example                # 环境变量模板
├── README.md                   # 项目说明
├── DEPLOY.md                   # 详细部署指南
├── CHANGELOG.md                # 更新日志
└── agent-backend/              # 智能体后端
    ├── app/                    # 应用代码
    │   ├── api/                # API 路由层
    │   ├── graph/              # LangGraph 图逻辑
    │   ├── llm/                # 大模型客户端
    │   ├── tools/              # 工具和技能实现
    │   └── sse/                # SSE 流式响应
    └── config/                 # 配置文件
        ├── tools.yaml          # 工具注册表
        └── settings.yaml       # 应用设置
```

## 技术架构

### 核心技术栈

- **FastAPI**: 高性能异步 Web 框架
- **LangGraph**: AI Agent 编排引擎
- **阿里云百炼**: 大语言模型（OpenAI 兼容）
- **MySQL 8.0**: 会话记忆存储
- **Docker**: 容器化部署

### 架构设计

```
┌─────────┐     ┌──────────────┐     ┌─────────────┐
│  前端   │────▶│ Agent Backend│────▶│Java Backend │
│         │     │   (8082)     │     │   (8081)    │
└─────────┘     └──────┬───────┘     └─────────────┘
                       │
                       ▼
                 ┌──────────┐
                 │  MySQL   │
                 │ (内网)   │
                 └──────────┘
```

### 评分技能

系统提供 8 个预定义技能，覆盖高频查询场景：

1. **special_score_overview**: 评分总览（总分/维度/通过状态）
2. **special_report_function_build**: 报备功能建设评估
3. **special_ticket_function_build**: 作业票功能建设评估
4. **special_inspection_function_build**: 抽查功能建设评估
5. **special_data_quality_evaluation**: 数据质量维度评估
6. **special_application_effect_evaluation**: 应用成效维度评估
7. **special_score_drilldown**: 扣分项分析
8. **special_ticket_issue**: 问题票据查询

## 接口规范

当前版本适配 **系统评分接口规范 v3**：

### 评分项编号

- **新格式**: `special-functionBuild-tszybbgnjsqkpg`（字符串编码）
- **旧格式**: `1.1`, `2.3`, `3.5`（数字编号，兼容）

### 统一状态

| 状态 | 说明 |
|------|------|
| `PASS` | 通过 |
| `BUSINESS_ISSUE` | 业务问题 |
| `DATA_INSUFFICIENT` | 数据不足 |
| `CALCULATION_ERROR` | 计算异常 |

### 关键字段

- `itemNo`: 评分项编号
- `detailText`: 详情文本
- `status`: 统一状态
- `dimensionCode/dimensionName`: 维度编码/名称
- `moduleCode/moduleName`: 模块编码/名称

## 配置说明

### 必需配置

| 环境变量 | 说明 | 示例 |
|---------|------|------|
| `JAVA_BACKEND_URL` | Java 评分后端地址 | `http://172.17.0.1:8081` |
| `LLM_API_KEY` | 大模型 API Key | `sk-xxx` |
| `AUTH_API_KEYS` | 前端鉴权 Keys | `["app-xxx"]` |

### 可选配置

| 环境变量 | 说明 | 默认值 |
|---------|------|--------|
| `LLM_MODEL` | 模型名称 | `qwen3-vl-235b-a22b-instruct` |
| `MYSQL_ROOT_PASSWORD` | MySQL 密码 | `agent-memory-2026` |
| `MEMORY_DATABASE` | 数据库名 | `agent_memory` |

详细配置说明见 [DEPLOY.md](DEPLOY.md)

## API 文档

### 对话接口

**POST** `/v1/chat-messages`

**请求头**:
```
Authorization: Bearer <AUTH_API_KEY>
Content-Type: application/json
```

**请求体**:
```json
{
  "query": "特殊作业评分总览",
  "response_mode": "streaming",  // 或 "blocking"
  "conversation_id": "",         // 可选
  "user": "u_10001"
}
```

**响应**: 
- Streaming: SSE 事件流
- Blocking: JSON 对象

详细 API 文档见 [DEPLOY.md](DEPLOY.md#前端接入)

## 开发指南

### 本地开发

```bash
# 安装依赖
cd agent-backend
pip install -e .

# 配置环境变量
export JAVA_BACKEND_URL=http://localhost:8081
export LLM_API_KEY=your_key
export AUTH_API_KEYS='["app-test"]'

# 启动服务
uvicorn app.main:app --reload --port 8000
```

### 添加新技能

1. 在 `app/tools/skills.py` 中实现技能函数
2. 在 `SKILLS` 字典中注册
3. 在 `config/tools.yaml` 中添加工具配置
4. 在 `app/graph/prompts.py` 中更新提示词

### 代码结构

- `app/api/`: API 路由和请求响应模型
- `app/graph/`: LangGraph 状态机和编排逻辑
- `app/tools/`: 工具执行器和技能实现
- `app/llm/`: 大模型客户端封装
- `app/sse/`: SSE 流式响应处理

## 监控和维护

### 日志查看

```bash
# 查看所有日志
docker compose logs -f

# 查看智能体日志
docker compose logs -f agent-backend

# 查看 MySQL 日志
docker compose logs -f mysql
```

### 服务管理

```bash
# 重启服务
docker compose restart agent-backend

# 查看服务状态
docker compose ps

# 停止服务
docker compose down

# 清空数据（包括会话记忆）
docker compose down -v
```

## 常见问题

### 无法连接 Java 后端

检查 `JAVA_BACKEND_URL` 配置是否正确：

```bash
# 获取 Docker 网桥网关 IP
docker network inspect bridge --format '{{(index .IPAM.Config 0).Gateway}}'

# 更新 .env
JAVA_BACKEND_URL=http://<网关IP>:8081

# 重启服务
docker compose up -d
```

### 大模型调用失败

- 检查 API Key 是否有效
- 确认已开通对应模型
- 验证网络连通性

更多问题见 [DEPLOY.md](DEPLOY.md#常见问题)

## 版本历史

### v1.0.0 (2026-09-10)

- ✅ 适配评分接口规范 v3
- ✅ 支持新旧格式评分项编号
- ✅ 更新统一状态枚举
- ✅ 优化结果格式化逻辑
- ✅ 完善部署文档

详见 [CHANGELOG.md](CHANGELOG.md)

## 许可证

本项目为内部使用项目。

## 联系方式

如有问题或建议，请联系开发团队。
