# 基于 MongoDB 的在线问卷系统

一个简化版的在线问卷系统（类似问卷星 / Google Forms）：注册用户创建问卷，设置题目、校验规则和跳转规则，发布后通过链接 `/survey/<shortCode>` 分发；其他用户登录后填写，创建者查看实时统计。所有数据存储在 MongoDB 中。

> 课程项目第一阶段。
> - **GitHub 仓库**：https://github.com/honeySeae/mongodb-survey-system
> - **示例问卷**：本地 http://127.0.0.1:8000/survey/Food26（先运行 `python -m scripts.seed_demo`），见[十、示例问卷](#十示例问卷)

## 目录

[一、项目简介](#一项目简介) · [二、快速开始](#二快速开始) · [三、部署](#三部署) · [四、技术栈与版本](#四技术栈与版本) · [五、项目结构](#五项目结构) · [六、数据库设计](#六数据库设计) · [七、API 说明](#七api-说明) · [八、关键逻辑说明](#八关键逻辑说明) · [九、测试](#九测试) · [十、示例问卷](#十示例问卷) · [十一、文档索引](#十一文档索引)

---

## 一、项目简介

| 功能 | 说明 |
|---|---|
| 账号 | 注册、登录（JWT），密码用 bcrypt 哈希；登录后只能看到自己创建的问卷 |
| 问卷管理 | 创建（标题、说明、是否匿名、提交策略、截止时间）、我的问卷列表、发布、关闭、删除草稿；每份问卷有 `/survey/<shortCode>` 链接 |
| 题型 | 单选（选项、必答）；多选（至少 / 最多 / 必须选几项）；文本填空（最少 / 最多字数）；数字填空（最小值、最大值、是否整数） |
| 跳转 | 按单选、多选、数字的答案跳到后面的题或结束问卷；规则存在问卷数据中，用下拉框设置，保存时检查合法性 |
| 填写 | 填写前需登录；逐题展开，由后端计算下一题；不合法时提示错误；**提交时后端重新计算跳转路径并校验**；支持多人同时填写、匿名、多次填写（三种提交策略） |
| 统计 | 单选各选项人数与作答人数；多选各选项被选次数；填空列出全部内容，数字题给出平均值；整份问卷统计与单题统计；聚合管道实时计算；匿名问卷不返回填写人 |

---

## 二、快速开始

**环境要求**：Python 3.11 及以上；MongoDB 5.0 及以上（统计中的 `$lookup` 写法需要 5.0+）。Node.js 22+ 和 Chrome / Edge 只有界面测试需要，没有时这些测试自动跳过。

### 1. 安装依赖

```bash
git clone https://github.com/honeySeae/mongodb-survey-system.git && cd mongodb-survey-system
python -m venv .venv
.venv\Scripts\activate            # Windows（PowerShell / cmd）
# source .venv/bin/activate       # Mac / Linux
pip install -r requirements.txt
```

### 2. 启动 MongoDB

- **Windows**：首次需要安装 MongoDB 并创建 `C:\data\mongod.cfg`（只监听 127.0.0.1，步骤见 [docs/DEPLOY.md](docs/DEPLOY.md#windows默认方式开发时使用)）。之后**每次开发或运行测试前双击 [`scripts/start_mongo.bat`](scripts/start_mongo.bat) 并保持窗口开着**；也可以直接运行 `mongod --config C:\data\mongod.cfg`。
- **Mac**：`brew services start mongodb-community`（安装见 [docs/DEPLOY.md](docs/DEPLOY.md#machomebrew)）。
- **Linux 服务器**：见[三、部署](#三部署)。
- 验证：`mongosh --eval "db.runCommand({ping:1})"` 输出 `{ ok: 1 }`。

### 3. 配置 `.env`

```bash
copy .env.example .env      # Windows；Mac / Linux：cp .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(48))"   # 生成 JWT_SECRET，填入 .env
```

| 变量 | 作用 | 本地示例 |
|---|---|---|
| `MONGO_URI` | MongoDB 连接串 | `mongodb://127.0.0.1:27017` |
| `MONGO_DB_NAME` | 数据库名（测试自动改用 `survey_test`） | `survey_dev` |
| `JWT_SECRET` | 登录令牌签名密钥，**至少 32 个字符**；`.env.example` 中的示例值会被拒绝 | 用上面的命令生成 |
| `JWT_EXPIRE_MINUTES` | 登录有效期（分钟） | `1440` |
| `PUBLIC_BASE_URL` | 对外访问地址，用于生成问卷链接，结尾不加 `/` | `http://127.0.0.1:8000` |
| `BCRYPT_ROUNDS` | 可选，bcrypt 强度，默认 12 | 不设置 |

`MONGO_URI`、`JWT_SECRET`、`PUBLIC_BASE_URL` 没有默认值，缺少或不合法时程序拒绝启动并给出提示。

### 4. 初始化数据库、启动服务、生成示例问卷

```bash
python -m scripts.init_db          # 可选：创建集合、$jsonSchema 校验和索引（启动服务时也会自动执行，可重复执行）
uvicorn app.main:app --reload      # 启动服务
python -m scripts.seed_demo        # 生成示例问卷 Food26（另开一个终端，或先于服务运行均可）
```

浏览器打开 **http://127.0.0.1:8000**（进入登录页）；接口文档 http://127.0.0.1:8000/docs ；健康检查 `/api/health` 返回 `{"status":"ok","database":"ok"}`。

> 本地请用 `127.0.0.1`，不要用 `localhost`：Windows 会先尝试 IPv6 的 `::1`，而 uvicorn 默认只监听 IPv4，每个请求要多等约 2 秒。

运行测试见[九、测试](#九测试)。

---

## 三、部署

部署到阿里云 Linux 服务器（Ubuntu 24.04、systemd）的完整步骤见 **[docs/DEPLOY.md](docs/DEPLOY.md#二部署到-linux-服务器阿里云)**。要点：

- MongoDB 只监听本机（`bindIp: 127.0.0.1`），安全组**只开放 8000 端口，不开放 27017**；
- **必须重新生成 `JWT_SECRET`**，`PUBLIC_BASE_URL` 改为服务器的公网地址；
- 生成示例问卷时用 `--owner-password` 换掉创建者密码。

---

## 四、技术栈与版本

**前端**：原生 HTML + CSS + JavaScript（ES 模块），由后端静态托管；不使用任何前端框架、CDN 或外部字体。

| 组件 | 版本 | 用途 |
|---|---|---|
| Python | 3.14.2（要求 3.11+） | 开发语言 |
| FastAPI / Uvicorn | 0.147.0 / 0.54.0 | Web 框架 / ASGI 服务器 |
| PyMongo | 4.19.0 | MongoDB 驱动 |
| Pydantic / pydantic-settings | 2.14.1 / 2.16.0 | 请求响应模型、读取配置 |
| bcrypt / PyJWT / python-dotenv | 5.0.0 / 2.15.1 / 1.2.4 | 密码哈希 / 登录令牌 / 读取 `.env` |
| MongoDB | 8.3.11（要求 5.0+） | 数据库 |
| pytest / httpx2 / pytest-cov | 9.1.1 / 2.14.0 / 7.1.0 | 测试框架 / TestClient 的 HTTP 客户端 / 覆盖率 |
| Node.js / Chrome | 24.14.0 / 155（可选） | 界面测试（无界面 Chrome）、前端纯函数测试 |

全部 Python 依赖及版本见 [`requirements.txt`](requirements.txt)。**没有使用任何现成的问卷系统框架或库**（如 SurveyJS、xiaoju-survey）。

---

## 五、项目结构

```
app/            后端：routers（接口）→ services（业务流程）→ logic / stats（纯函数）→ repositories（数据库读写）
  logic/        operators.py 运算符表、question_rules.py 题目设置检查、survey_check.py 跳转规则检查、
                validation.py 答案校验、jump.py 路径计算、survey_state.py 问卷状态规则
  stats/        pipelines.py 统计聚合管道
  db_schema.py  三个集合的 $jsonSchema 校验规则与索引
static/         前端页面：登录、我的问卷、编辑、填写、统计
scripts/        init_db.py 初始化数据库；seed_demo.py 示例问卷；sport_survey_e2e.py 端到端测试；start_mongo.bat
tests/          pytest 测试；tests/ui/ 界面测试；tests/js/ 前端纯函数测试
docs/           设计文档、API 说明、部署、测试用例、AI 使用日志
```

关键逻辑（校验、跳转、统计管道）都是不访问数据库的纯函数，便于单独测试和第二阶段修改。

---

## 六、数据库设计

> 完整设计（字段表、取值、业务规则、设计理由、统计管道、为什么适合 MongoDB、第二阶段扩展点、修订记录）见 **[docs/DATABASE_DESIGN.md](docs/DATABASE_DESIGN.md)**。

| 集合 | 作用 | 一条文档代表 | 主要字段 |
|---|---|---|---|
| `users` | 用户账号（创建者和填写者是同一种用户） | 一个用户 | `username`、`passwordHash`、`createdAt` |
| `surveys` | 问卷，**题目、选项、校验规则、跳转规则都嵌入其中** | 一份问卷 | `ownerId`、`shortCode`、`status`、`settings`、`questions[]` |
| `responses` | 填写结果 | 一次提交 | `surveyId`、`respondentId`、`isLatest`、`answers[{questionId, value}]` |

**题目为什么嵌入问卷**：题目总是和问卷一起读取，一次查询拿到整份问卷；题目数量有限（上限 100 道），远小于 16MB；只有创建者编辑，整份问卷一次写入，跳转规则的合法性在同一文档内即可检查；数组顺序就是题目顺序。题目和选项使用**稳定 id**（`q_` / `o_` + 6 位），跳转规则和答卷引用 id 而不是“第几题”，调整顺序、改选项文字都不会使规则和旧答卷出错。

**答卷为什么单独成集合**：答卷数量没有上限，嵌入会让问卷文档无限增长；多人同时提交不会争抢同一文档；统计需要对大量答卷做聚合。`answers` 用 `{questionId, value}` 数组，所有题型的统计管道可以共用前三步，一个 `answers.questionId` 索引覆盖所有题。

**索引**：`users.username` 唯一；`surveys.shortCode` 唯一；`surveys {ownerId, createdAt}`；`responses {surveyId, submittedAt}`；`responses {surveyId, respondentId}` **唯一、部分索引 `isLatest: true`**（每人每份问卷最多一份“最新”答卷，也是并发提交的最终保证）；`responses.answers.questionId`。三个集合都有 `$jsonSchema` 校验（`validationLevel: moderate`、不禁止额外字段，为第二阶段留余地），见 `app/db_schema.py`。

**关键业务规则**：

- **匿名**：填写前必须登录，始终记录 `respondentId`（用于防止重复填写），匿名问卷的统计和答卷列表不返回填写人；
- **提交策略**：`once` 每人一次；`latest` 可重填、以最后一次为准；`all` 每次都算。所有提交都保留，用 `isLatest` 区分；
- **问卷状态**：草稿 → 已发布 → 已关闭；超过截止时间视同关闭，延长后恢复；发布后题目、匿名设置、提交策略锁定。

---

## 七、API 说明

> 每个接口的参数、请求与返回示例、错误码见 **[docs/API.md](docs/API.md)**。运行服务后也可以在 http://127.0.0.1:8000/docs 交互调试。

除注册、登录、`/api/meta`、`/api/health` 外都需要请求头 `Authorization: Bearer <accessToken>`。请求和响应均为 JSON；错误统一为 `{code, message, errors?}`，例如 `{"code": "VALIDATION_ERROR", "message": "提交内容不合法", "errors": [{"field": "username", "message": "用户名只能包含字母、数字和下划线"}]}`。访问别人的问卷与访问不存在的问卷一样返回 404。

| 模块 | 方法 | 路径 | 用途 |
|---|---|---|---|
| 账号 | POST | `/api/auth/register` | 注册 |
| | POST | `/api/auth/login` | 登录，返回令牌 |
| | GET | `/api/auth/me` | 当前用户 |
| 问卷管理 | POST | `/api/surveys` | 创建问卷（草稿） |
| | GET | `/api/surveys` | 我的问卷列表 |
| | GET | `/api/surveys/{id}` | 问卷详情（含题目和警告） |
| | PATCH | `/api/surveys/{id}` | 修改基本信息和设置 |
| | DELETE | `/api/surveys/{id}` | 删除草稿 |
| | POST | `/api/surveys/{id}/publish` | 发布 |
| | POST | `/api/surveys/{id}/close` | 关闭 |
| 题目 | POST | `/api/surveys/{id}/questions` | 添加题目 |
| | PUT | `/api/surveys/{id}/questions/{qid}` | 修改题目（含跳转规则） |
| | DELETE | `/api/surveys/{id}/questions/{qid}` | 删除题目 |
| | PUT | `/api/surveys/{id}/questions/order` | 调整题目顺序 |
| 填写 | GET | `/api/s/{shortCode}` | 填写者获取问卷（不含跳转规则） |
| | POST | `/api/s/{shortCode}/path` | 路径预览（下一题与错误，不保存） |
| | POST | `/api/s/{shortCode}/responses` | 提交答卷 |
| 统计 | GET | `/api/surveys/{id}/stats` | 整份问卷统计 |
| | GET | `/api/surveys/{id}/stats/questions/{qid}` | 单题统计（填空题内容可分页） |
| | GET | `/api/surveys/{id}/responses` | 答卷列表 |
| 其他 | GET | `/api/meta` | 题型、运算符表、长度上限（前端使用） |
| | GET | `/api/health` | 健康检查 |

---

## 八、关键逻辑说明

### 1. 校验

校验写成不访问数据库的纯函数，分两个时机：

- **保存题目时**（`app/logic/question_rules.py`）：各题型只允许自己的设置字段；`min ≤ max`、`minLength ≤ maxLength`、`minSelect ≤ maxSelect ≤ 选项数`；类型严格（布尔值不当数字、`"3"` 不当 3）。
- **提交答案时**（`app/logic/validation.py`）：必答；单选必须是本题选项；多选不重复、数量限制；文本按 Unicode 字符计字数；数字必须是 JSON 数字、在范围内、整数题必须为整数且在 64 位范围内。选填题未作答不校验，一旦作答就必须合法。保存前规范化：文本去首尾空白、多选按选项顺序、整数题 `3.0` 存为 `3`。

### 2. 跳转

每道题的 `logic` 中有若干条规则 `{when: {op, value}, goto}` 和一个 `defaultNext`，存在问卷数据中，程序只负责解释。

| 题型 | 运算符 |
|---|---|
| 单选 | `eq`（选择了）、`in`（选择了其中之一） |
| 多选 | `contains`、`containsAny`、`containsAll`、`equals` |
| 数字 | `eq` `ne` `gt` `gte` `lt` `lte`、`between`（含两端） |

- **约定**：规则按顺序检查，**第一条成立的生效**；**只能往后跳**或跳到 `END`；都不成立时走 `defaultNext`（为空则顺序进入下一题）；选填题未作答不匹配任何规则；被跳过的题不显示、不校验、不保存。
- **保存时检查**（`app/logic/survey_check.py`）：运算符与题型匹配、值合法、只能引用本题选项、目标在本题之后；每次修改和调整顺序后都检查整份问卷。规则重叠、永远不会成立的规则、永远不会显示的题给出警告。
- **路径计算**（`app/logic/jump.py`）：从第 1 题开始，校验当前题 → 按规则找下一题，遇到第一个错误即停。填写时的逐题预览和提交用同一个函数；**提交时后端从第一题重新计算**，只保存路径上作答的题，路径外的答案丢弃。

### 3. 统计

用 MongoDB 聚合管道实时计算（`app/stats/pipelines.py`），各题型共用前三步：

```js
{ $match: { surveyId: S, ...口径, "answers.questionId": Q } },  // 使用索引
{ $unwind: "$answers" },
{ $match: { "answers.questionId": Q } }
```

之后单选按值分组计数，多选再 `$unwind` 一次后计数，数字用 `$avg`，填空列出内容（分页）。**口径**：`latest` 只算 `isLatest: true`，`once`、`all` 算全部答卷，问卷列表、统计、答卷列表三处数字一致。**匿名**：实名问卷用 `$lookup` 只取用户名；匿名问卷的管道不含 `$lookup`、不输出 `respondentId`。各题型完整管道见[设计文档 6.8](docs/DATABASE_DESIGN.md)。

---

## 九、测试

```bash
pytest                                                      # 全部测试（含界面测试）
pytest -m "not ui"                                          # 只跑后端测试（不需要 Node.js 和 Chrome）
pytest --cov=app --cov=scripts --cov-report=term-missing    # 代码覆盖率
```

在项目根目录、激活虚拟环境并启动 MongoDB 后运行。测试使用独立数据库（`survey_test`、`survey_ui_test`），不影响开发数据。

**运行结果**（2026-10-22）：**660 个测试全部通过**。覆盖率：`app/` 99%；`app/` 与 `scripts/` 合计 88%（`scripts/sport_survey_e2e.py` 是对着运行中的服务手动执行的端到端脚本，不在 pytest 中运行，不计它时为 99%）。另有一项基于开发者手工创建的问卷的端到端测试（15 位模拟填写人、6 份不合法答卷、43 项统计核对，全部一致）。

**代表性用例**（完整的 99 条用例、端到端测试、界面测试和手工测试见 **[docs/TEST_CASES.md](docs/TEST_CASES.md)**）。“水果问卷”是设计文档 3.4 的示例问卷：第 1 题选“不喜欢”跳到第 5 题，第 4 题填 0 结束。

| 测试点 | 测试步骤 | 输入 | 期望输出 | 实际结果 |
|---|---|---|---|---|
| 年龄 0–120 整数（需求原文） | 校验“0–120 的整数”数字题的答案 | 121；119.5；`3.0` | “不能大于 120”；“必须为整数”；保存为 `3` | “不能大于 120”；“必须为整数”；`3.0` 保存为整数 `3`，通过 |
| 多条规则命中顺序 | 多选题设两条规则后计算答题路径 | 规则 ① `containsAll [A, B]` → 第 4 题，② `contains A` → 第 3 题；答案选 A、B | 按第一条跳到第 4 题 | 路径为 [第 1 题, 第 4 题]，通过 |
| 往前跳被拒绝 | 保存跳转规则时整体检查 | 第 2 题的规则跳到第 1 题 | 拒绝，“只能跳转到后面的题目或 END（目标是第 1 题）” | 错误字段 `logic.rules[0].goto`，信息为“第 2 题第 1 条规则：只能跳转到后面的题目或 END（目标是第 1 题）”，通过 |
| 被跳过的必答题、多余答案 | 登录后向已发布的水果问卷提交答案 | 第 1 题选“不喜欢”，同时提交第 2~4 题的答案（含不合法值）和一个不存在的题目 id | 201，只保存第 1、5 题 | 201，返回和数据库中保存的题目都是 [第 1 题, 第 5 题]，通过 |
| 三种提交策略 | 同一人向 once / latest / all 问卷各提交多次 | 完整合法的答案 | once：第二次 409；latest：只有最后一份 isLatest；all：三份都计入 | once：第二次 409 `ALREADY_SUBMITTED`，库中 1 份；latest：3 份的 isLatest 为 [false, false, true]；all：3 份都保存，统计时都计入，通过 |
| 截止/关闭后提交 | 问卷关闭或截止时间已过后提交 | 完整合法的答案 | 409 `SURVEY_CLOSED` / `SURVEY_EXPIRED`，不保存 | 409，`SURVEY_CLOSED`“问卷已关闭，不再接受填写”或 `SURVEY_EXPIRED`“问卷已截止，不再接受填写”，库中没有答卷，通过 |
| 统计与匿名 | 4 人按不同路径填写水果问卷后，创建者查看统计和答卷列表 | 4 份答卷（实名 / 匿名各一份问卷） | 喜欢 3、不喜欢 1；数字平均 10/3；匿名问卷返回内容中没有任何用户名和用户 id | 喜欢 3、不喜欢 1；第 4 题内容 [0, 3, 7]，平均值 10/3；匿名问卷 3 个接口的返回中找不到任何用户名、用户 id 和 username/respondentId 字段，通过 |

---

## 十、示例问卷

`scripts/seed_demo.py` 生成一份已发布的示例问卷 **“大学生饮食习惯调查”**（12 道题，覆盖四种题型、单选/多选/数字三类跳转和各种校验）和 12 位填写人的 13 份答卷。

| 项目 | 内容 |
|---|---|
| **访问链接** | 本地 **http://127.0.0.1:8000/survey/Food26**；部署后 `<PUBLIC_BASE_URL>/survey/Food26` |
| 填写人账号 | `demo_s01` ~ `demo_s12`，密码均为 `demo123456`；也可以自己注册新账号填写 |
| 创建者账号 | `demo_owner`，本地密码 `demo123456`（线上用 `--owner-password` 另设）；登录后在“我的问卷”中点“统计结果” |
| 设置 | 已发布、实名、`latest`（可以重填，以最后一次为准）、不限截止时间 |

```bash
python -m scripts.seed_demo                        # 已存在时不重复生成，直接输出链接和账号
python -m scripts.seed_demo --reset                # 只删除示例问卷及其答卷后重新生成（链接仍为 Food26）
python -m scripts.seed_demo --owner-password XXX   # 指定创建者密码（部署到服务器时使用）
```

先启动 MongoDB 即可运行，不需要先启动服务。链接代码固定为 `Food26`；若已被另一份问卷占用，脚本报错停止，不会覆盖。**建议试的路径**：第 1 题选“否”直接结束；第 4 题选“基本不吃”跳到第 6 题；第 7 题不选“外卖”直接到第 10 题；年龄填 150 或 18.5 会提示错误；提交后再次打开会预填上次的答案。

---

## 十一、文档索引

| 文档 | 内容 |
|---|---|
| [docs/DATABASE_DESIGN.md](docs/DATABASE_DESIGN.md) | 数据库设计：集合、字段、索引、业务规则、设计理由、统计聚合管道、为第二阶段预留的扩展点、修订记录 |
| [docs/API.md](docs/API.md) | API 说明：每个接口的参数、请求与返回示例、错误码 |
| [docs/DEPLOY.md](docs/DEPLOY.md) | MongoDB 安装配置（Windows / Mac）、部署到 Linux 服务器（阿里云） |
| [docs/TEST_CASES.md](docs/TEST_CASES.md) | 测试用例（步骤、输入、期望输出、实际结果）、运行记录、端到端测试、界面测试截图、手工测试 |
| [docs/sport_survey_e2e_result.md](docs/sport_survey_e2e_result.md) | 端到端测试（开发者手工创建的问卷）的完整核对结果 |
| [docs/AI_LOG.md](docs/AI_LOG.md) | AI 使用日志：每一步的提示词、AI 产出、是否修改、AI 的错误与开发者的决定 |
| [docs/KICKOFF_PROMPT.md](docs/KICKOFF_PROMPT.md) | 开工时给 AI 的提示词 |
| [CLAUDE.md](CLAUDE.md) | 给 AI（Claude Code）的项目约束与工作方式 |
