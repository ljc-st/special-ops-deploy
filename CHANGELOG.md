# 更新日志

## [2026-09-10] - 接口适配更新

### 变更内容
- 适配新版统一评分接口规范（系统评分接口规范 v3）
- 更新评分项编号格式支持：
  - 新格式：字符串编码（如 `special-functionBuild-tszybbgnjsqkpg`）
  - 旧格式：数字编号（如 `1.1`, `2.3`）兼容处理
- 更新统一状态枚举：
  - `PASS`: 通过
  - `BUSINESS_ISSUE`: 存在业务问题
  - `DATA_INSUFFICIENT`: 数据不足
  - `CALCULATION_ERROR`: 计算异常
- 更新字段名映射：
  - `itemNo`: 评分项编号
  - `detailText`: 详情文本（原 `reason`, `issueDesc`）
  - `status`: 统一状态
  - `dimensionCode/dimensionName`: 维度编码/名称
  - `moduleCode/moduleName`: 模块编码/名称

### 修改文件
- `agent-backend/app/tools/skills.py`: 更新评分项处理逻辑，支持新旧格式兼容
- `agent-backend/app/tools/score_format.py`: 更新结果格式化，适配新字段名
- `agent-backend/config/tools.yaml`: 更新工具配置，调整观察模板
- `agent-backend/app/graph/prompts.py`: 更新系统提示词，说明新格式

### 兼容性
- 完全兼容旧格式接口返回
- 自动识别新旧格式评分项编号
- 优先使用新格式字段，回退到旧格式字段
