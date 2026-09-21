# 贡献指南

感谢你关注跨境电商多智能体运营矩阵。欢迎提交问题、文档改进、测试用例和功能实现。

## 开始之前

- 普通缺陷或功能建议请使用仓库中的中文 Issue 模板。
- 安全漏洞不要创建公开 Issue，请按照 [安全策略](SECURITY.md) 私下报告。
- 大范围架构调整建议先创建 Issue，说明目标、边界和兼容性影响。

## 本地开发

要求 Python 3.11+。完整业务联调还需要 PostgreSQL 16、pgvector 与 Redis 7。

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

初始化 Demo 数据并启动服务：

```bash
python -m ecom_agent_matrix.scripts.bootstrap_demo
python -m uvicorn ecom_agent_matrix.api.main:app --reload --port 8002
```

## 提交前检查

```bash
python -m compileall -q ecom_agent_matrix eval
ruff check ecom_agent_matrix test eval
ruff format --check ecom_agent_matrix test eval
pytest -q
python -m eval.runner --suite deterministic --fail-on-regression
python -m eval.enterprise.runner --suite all --fail-on-regression
python -m eval.enterprise.advanced_runner --suite all --fail-on-regression
```

涉及路由、SQL、审批、租户隔离、RAG 引用或对话记忆的修改，必须补充相应回归测试。不得通过放宽安全校验来让测试通过。

## 提交与合并请求

- 每次提交只解决一个清晰问题，提交信息使用简短的祈使句。
- 合并请求应说明：问题、方案、验证方式、风险和界面变化。
- 不要提交 `.env`、API Key、数据库密码、客户数据、模型密钥或私有日志。
- 如果改变 API 或 Demo 行为，请同步更新 README 或 `docs/`。
- 如果改变前端，请附上修改前后说明；适合时附截图。

## 设计原则

- 认证、授权、审批、幂等和租户隔离由代码强制执行，不能依赖提示词。
- 高置信单任务优先走确定性 Fast Path，复杂组合任务才进入 Typed DAG。
- 错误应面向用户说明原因和下一步，同时把技术细节保留在可展开区域。
- 评估报告必须来自实际运行，未运行的能力应标为 `NOT_RUN`，不能虚构结果。

