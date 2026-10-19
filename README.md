# 基于 MongoDB 的在线问卷系统

> 课程项目第一阶段。完整文档在项目完成后补全，数据库设计见 [docs/DATABASE_DESIGN.md](docs/DATABASE_DESIGN.md)。

## 快速开始（开发中）

```bash
# 1. 创建虚拟环境并安装依赖（Python 3.11+）
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Mac / Linux
pip install -r requirements.txt

# 2. 配置：复制模板后修改 JWT_SECRET、PUBLIC_BASE_URL 等（各项说明见 .env.example）
copy .env.example .env          # Mac / Linux：cp .env.example .env

# 3. 启动 MongoDB（Windows：双击 scripts/start_mongo.bat 并保持窗口打开；见下方“MongoDB 安装与启动”）

# 4. 启动服务
uvicorn app.main:app --reload
# 访问 http://127.0.0.1:8000/api/health ，返回 {"status":"ok","database":"ok"}

# 5. 运行测试（自动使用独立测试库 survey_test）
pytest
```

> **本地访问请用 `http://127.0.0.1:8000`，不要用 `localhost`。** Windows 会把 `localhost` 先解析为 IPv6 地址 `::1`，而 uvicorn 默认只监听 IPv4 的 `127.0.0.1`，每个请求要先等 IPv6 连接失败（约 2 秒）再回退（实测 `localhost` 每次约 2 秒，`127.0.0.1` 约 0.002 秒）。部署到 Linux 服务器时使用服务器的域名或 IP，不受影响。

## MongoDB 安装与启动

本项目在 MongoDB Community Server 8.3 上开发和测试，连接串通过 `.env` 中的 `MONGO_URI` 配置。

### Windows：首次准备（只需一次）

1. 从 [MongoDB 官网](https://www.mongodb.com/try/download/community) 安装 MongoDB Community Server 和 mongosh（安装时不必勾选 “Install MongoD as a Service”）。
2. 创建数据目录和日志目录：

   ```powershell
   mkdir C:\data\db, C:\data\log
   ```

3. 创建配置文件 `C:\data\mongod.cfg`：

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

### Windows：每次开发前启动 MongoDB（默认方式）

**每次开发或运行测试前，先双击 [`scripts/start_mongo.bat`](scripts/start_mongo.bat)，并保持它的窗口开着。**

- 窗口里不会滚动输出，日志写在 `C:\data\log\mongod.log`，这是正常的。
- 停止：在该窗口按 `Ctrl+C`。
- 若窗口提示 “MongoDB has stopped”，最常见的原因是已经有一个 MongoDB 在运行。
- 配置文件不在默认位置时，可在命令行运行 `scripts\start_mongo.bat D:\path\to\mongod.cfg`。
- 验证是否启动成功：`mongosh --eval "db.runCommand({ping:1})"` 输出 `{ ok: 1 }`。

不用脚本时，也可以在 PowerShell 中直接运行（窗口同样需要保持打开）：

```powershell
mongod --config C:\data\mongod.cfg
```

### Windows：可选，注册为系统服务（开机自动启动）

如果不想每次手动启动，可以把 MongoDB 注册为 Windows 服务（注册后就不要再运行 `start_mongo.bat`，二者使用同一端口和数据目录）。

**以管理员身份**打开 PowerShell（开始菜单搜索 PowerShell → 右键 → 以管理员身份运行），执行（路径中的 `8.3` 换成实际安装的版本）：

```powershell
& "C:\Program Files\MongoDB\Server\8.3\bin\mongod.exe" --config "C:\data\mongod.cfg" --install
net start MongoDB
```

| 操作 | 命令（管理员 PowerShell） |
|---|---|
| 启动 / 停止 | `net start MongoDB` / `net stop MongoDB` |
| 查看状态 | `sc.exe query MongoDB` |
| 卸载服务（不删除数据） | `net stop MongoDB` 后 `sc.exe delete MongoDB` |

### Mac（Homebrew）

```bash
brew tap mongodb/brew
brew install mongodb-community mongosh
brew services start mongodb-community   # 作为后台服务启动
# 或手动启动：mongod --dbpath ~/data/db（需先 mkdir -p ~/data/db）
```

### 初始化数据库（集合、校验规则、索引）

应用启动时会自动执行；也可以手动执行（可重复执行，不会影响已有数据）：

```bash
python -m scripts.init_db
```
