# 基于 MongoDB 的在线问卷系统

> 课程项目第一阶段。完整文档在项目完成后补全，数据库设计见 [docs/DATABASE_DESIGN.md](docs/DATABASE_DESIGN.md)。

## 快速开始（开发中）

```bash
# 1. 创建虚拟环境并安装依赖（Python 3.11+）
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Mac / Linux
pip install -r requirements.txt

# 2. 配置
copy .env.example .env          # Mac / Linux：cp .env.example .env

# 3. 启动 MongoDB（本地默认端口 27017）

# 4. 启动服务
uvicorn app.main:app --reload
# 访问 http://localhost:8000/api/health

# 5. 运行测试（自动使用独立测试库 survey_test）
pytest
```
