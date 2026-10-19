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

# 3. 启动 MongoDB（本地默认端口 27017，见下方“MongoDB 安装与启动”）

# 4. 启动服务
uvicorn app.main:app --reload
# 访问 http://localhost:8000/api/health

# 5. 运行测试（自动使用独立测试库 survey_test）
pytest
```

## MongoDB 安装与启动

本项目在 MongoDB Community Server 8.3 上开发和测试，连接串通过 `.env` 中的 `MONGO_URI` 配置（默认 `mongodb://localhost:27017`）。

### Windows：配置为系统服务（推荐，开机自动启动）

1. 从 [MongoDB 官网](https://www.mongodb.com/try/download/community) 安装 MongoDB Community Server 和 mongosh。
   安装时若勾选了 “Install MongoD as a Service”，服务已自动配置好，可跳过下面的步骤。
2. 创建数据目录、日志目录和配置文件 `C:\data\mongod.cfg`：

   ```yaml
   storage:
     dbPath: C:\data\db
   systemLog:
     destination: file
     path: C:\data\log\mongod.log
     logAppend: true
   net:
     port: 27017
     bindIp: 127.0.0.1
   ```

   ```powershell
   mkdir C:\data\db, C:\data\log
   ```

3. **以管理员身份**打开 PowerShell（开始菜单搜索 PowerShell → 右键 → 以管理员身份运行），注册并启动服务（路径中的 `8.3` 换成实际安装的版本）：

   ```powershell
   & "C:\Program Files\MongoDB\Server\8.3\bin\mongod.exe" --config "C:\data\mongod.cfg" --install
   net start MongoDB
   ```

4. 验证：`mongosh --eval "db.runCommand({ping:1})"` 输出 `{ ok: 1 }`。

服务管理（管理员 PowerShell）：

| 操作 | 命令 |
|---|---|
| 启动 / 停止 | `net start MongoDB` / `net stop MongoDB` |
| 查看状态 | `sc.exe query MongoDB` |
| 卸载服务（不删除数据） | `net stop MongoDB` 后 `sc.exe delete MongoDB` |

### Windows：不使用服务，手动启动

在普通 PowerShell 窗口中运行，窗口保持打开期间 MongoDB 可用：

```powershell
& "C:\Program Files\MongoDB\Server\8.3\bin\mongod.exe" --dbpath C:\data\db
```

停止：在该窗口按 `Ctrl+C`，或另开窗口执行 `mongosh --eval "db.adminCommand({shutdown:1})"`。
注意：服务和手动启动不要同时运行，二者使用同一端口和数据目录。

### Mac（Homebrew）

```bash
brew tap mongodb/brew
brew install mongodb-community mongosh
brew services start mongodb-community   # 作为后台服务启动
# 或手动启动：mongod --dbpath ~/data/db（需先 mkdir -p ~/data/db）
```
