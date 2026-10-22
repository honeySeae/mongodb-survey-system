# API 说明

> 本文件是 [README](../README.md#七api-说明) 中“API 说明”的完整版：每个接口的参数、返回示例和错误码。
> 运行服务后，http://127.0.0.1:8000/docs 提供可交互的接口文档（点 Authorize 填入令牌即可调试）。

## 通用约定

- **认证**：除注册、登录、`/api/meta`、`/api/health` 外，所有接口都需要请求头 `Authorization: Bearer <accessToken>`（登录接口返回）。
- **请求与响应**均为 JSON，字段名使用驼峰命名；时间为带时区的 ISO 8601（返回统一为 UTC，以 `Z` 结尾；提交时必须带时区）。
- **只能操作自己的问卷**：访问别人的问卷与访问不存在的问卷一样返回 404。
- **统一错误格式**：

```json
{ "code": "VALIDATION_ERROR", "message": "提交内容不合法",
  "errors": [ { "field": "username", "message": "用户名只能包含字母、数字和下划线" } ] }
```

`errors` 只在有字段级错误时出现；与题目相关的错误还带 `questionId`。

| 状态码 | 错误码 | 含义 |
|---|---|---|
| 400 | `BAD_REQUEST` | 请求体无法解析（如不是 UTF-8 编码） |
| 401 | `NOT_AUTHENTICATED` / `INVALID_TOKEN` / `TOKEN_EXPIRED` / `INVALID_CREDENTIALS` | 未登录 / 令牌无效 / 已过期 / 用户名或密码错误 |
| 404 | `SURVEY_NOT_FOUND` / `QUESTION_NOT_FOUND` / `SURVEY_NOT_PUBLISHED` / `NOT_FOUND` | 资源不存在（含别人的问卷）/ 问卷尚未发布 |
| 409 | `USERNAME_TAKEN` | 用户名已被注册 |
| 409 | `INVALID_STATUS` / `FIELD_LOCKED` | 当前状态不允许该操作 / 字段已锁定 |
| 409 | `EDIT_CONFLICT` / `QUESTION_REFERENCED` | 问卷已被修改 / 题目被跳转规则引用 |
| 409 | `SURVEY_CLOSED` / `SURVEY_EXPIRED` / `ALREADY_SUBMITTED` / `SUBMIT_CONFLICT` | 问卷已关闭 / 已截止 / 已填写过（once）/ 同时提交冲突 |
| 422 | `VALIDATION_ERROR` / `NO_QUESTIONS` | 输入不合法 / 没有题目不能发布 |
| 500 | `INTERNAL_ERROR` / `SURVEY_DATA_INVALID` | 服务器内部错误 / 问卷数据异常 |

## 接口总览（22 个）

| 模块 | 方法 | 路径 | 说明 |
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
| 填写 | GET | `/api/s/{shortCode}` | 填写者获取问卷 |
| | POST | `/api/s/{shortCode}/path` | 路径预览（下一题与错误，不保存） |
| | POST | `/api/s/{shortCode}/responses` | 提交答卷 |
| 统计 | GET | `/api/surveys/{id}/stats` | 整份问卷统计 |
| | GET | `/api/surveys/{id}/stats/questions/{qid}` | 单题统计 |
| | GET | `/api/surveys/{id}/responses` | 答卷列表 |
| 其他 | GET | `/api/meta` | 题型、运算符表、长度上限（前端使用） |
| | GET | `/api/health` | 健康检查 |

运行服务后，http://127.0.0.1:8000/docs 提供可交互的接口文档（点 Authorize 填入令牌即可调试）。

## 1. 账号

### `POST /api/auth/register` 注册

| 参数（请求体） | 类型 | 说明 |
|---|---|---|
| `username` | string | 3–20 个字符，只能包含字母、数字、下划线；不区分大小写（保存为小写） |
| `password` | string | 至少 8 个字符，最多 72 字节 |

<details><summary>请求与返回示例</summary>

```json
// 请求
{ "username": "Alice_01", "password": "password123" }
// 201
{ "id": "6ad6008f4c5dce2dcadf114f", "username": "alice_01", "createdAt": "2026-10-19T11:35:43.182000Z" }
// 409
{ "code": "USERNAME_TAKEN", "message": "用户名已被注册" }
```
</details>

### `POST /api/auth/login` 登录

参数同注册。注册成功后不会自动登录，需再调用登录接口。

<details><summary>请求与返回示例</summary>

```json
// 请求
{ "username": "alice_01", "password": "password123" }
// 200
{ "accessToken": "eyJhbGciOiJIUzI1NiIs...", "tokenType": "bearer", "expiresIn": 86400,
  "user": { "id": "6ad6008f4c5dce2dcadf114f", "username": "alice_01", "createdAt": "2026-10-19T11:35:43.182000Z" } }
// 401（用户名不存在和密码错误返回完全相同的提示）
{ "code": "INVALID_CREDENTIALS", "message": "用户名或密码错误" }
```
</details>

### `GET /api/auth/me` 当前用户

无参数，返回 `{id, username, createdAt}`；未登录 401 `NOT_AUTHENTICATED`，令牌过期 401 `TOKEN_EXPIRED`。

## 2. 问卷管理

### `POST /api/surveys` 创建问卷

| 参数（请求体） | 类型 | 必填 | 说明 |
|---|---|---|---|
| `title` | string | 是 | 1–100 个字符 |
| `description` | string | 否 | 0–1000 个字符 |
| `allowAnonymous` | boolean | 否 | 默认 false |
| `submissionPolicy` | string | 否 | `once`（默认）/ `latest` / `all` |
| `deadline` | string \| null | 否 | 带时区的时间，必须晚于当前时间；null 表示不限 |

<details><summary>请求与返回示例</summary>

```json
// 请求
{ "title": "水果偏好调查", "description": "了解大家吃水果的习惯", "allowAnonymous": true,
  "submissionPolicy": "latest", "deadline": "2026-11-30T23:59:59+08:00" }
// 201（问卷详情，下面的“问卷详情”格式）
{ "id": "6ad6046148384937d865e193", "shortCode": "NSiZ9e", "url": "http://127.0.0.1:8000/survey/NSiZ9e",
  "title": "水果偏好调查", "description": "了解大家吃水果的习惯", "status": "draft", "isExpired": false,
  "settings": { "allowAnonymous": true, "submissionPolicy": "latest", "deadline": "2026-11-30T15:59:59Z" },
  "version": 1, "questions": [], "warnings": [],
  "createdAt": "2026-10-19T11:52:01.136000Z", "updatedAt": "2026-10-19T11:52:01.136000Z",
  "publishedAt": null, "closedAt": null }
// 422
{ "code": "VALIDATION_ERROR", "message": "提交内容不合法",
  "errors": [ { "field": "deadline", "message": "截止时间必须晚于当前时间" } ] }
```
</details>

### `GET /api/surveys` 我的问卷列表

无参数。返回数组，新的在前；每项不含题目，含 `questionCount`（题目数）与 `responseCount`（答卷数，口径与统计一致）。

<details><summary>返回示例</summary>

```json
[ { "id": "6ad6046148384937d865e193", "shortCode": "NSiZ9e", "url": "http://127.0.0.1:8000/survey/NSiZ9e",
    "title": "水果偏好调查", "status": "published", "isExpired": false,
    "settings": { "allowAnonymous": true, "submissionPolicy": "latest", "deadline": null },
    "questionCount": 5, "responseCount": 12,
    "createdAt": "...", "updatedAt": "...", "publishedAt": "...", "closedAt": null } ]
```
</details>

### `GET /api/surveys/{id}` 问卷详情

返回完整问卷（格式同创建问卷的返回），含 `questions`（含跳转规则）和 `warnings`（规则重叠、永远不会成立的规则、永远不会显示的题，不影响保存和发布）。

### `PATCH /api/surveys/{id}` 修改问卷

只提交要修改的字段（`title`、`description`、`allowAnonymous`、`submissionPolicy`、`deadline`）；`deadline: null` 表示改为不限。

| 问卷状态 | 可修改 |
|---|---|
| 草稿 | 全部 |
| 已发布 | 标题、说明、截止时间（必须晚于当前时间；已过期的问卷延长后恢复收集） |
| 已关闭 | 不能修改 |

<details><summary>返回示例</summary>

```json
// 200：问卷详情
// 409：已发布问卷修改提交策略（与当前值相同则不算修改）
{ "code": "FIELD_LOCKED", "message": "问卷已发布，不能修改提交策略（会影响已收集答卷的统计口径）",
  "errors": [ { "field": "submissionPolicy", "message": "问卷已发布，不能修改提交策略（会影响已收集答卷的统计口径）" } ] }
```
</details>

### `DELETE /api/surveys/{id}` 删除草稿

成功返回 204；已发布或已关闭的问卷 409 `INVALID_STATUS`。

### `POST /api/surveys/{id}/publish` 发布、`POST /api/surveys/{id}/close` 关闭

无请求体，成功返回问卷详情。发布条件：草稿、至少 1 道题、截止时间未过；只有已发布的问卷可以关闭，关闭后不能重新打开。

<details><summary>错误示例</summary>

```json
{ "code": "NO_QUESTIONS", "message": "问卷至少需要 1 道题才能发布" }
{ "code": "INVALID_STATUS", "message": "只有已发布的问卷可以关闭（当前状态：草稿）" }
```
</details>

## 3. 题目（只有草稿可以修改）

四个接口都可带查询参数 `expectedUpdatedAt`（读取问卷时看到的 `updatedAt`）：带了则检查期间问卷是否被修改过，被修改过返回 409 `EDIT_CONFLICT`。都返回修改后的完整问卷（含系统生成的 id 和 `warnings`）。每次修改后对整份问卷做一次合法性检查，不合法则拒绝本次修改。

### `POST /api/surveys/{id}/questions` 添加题目

| 参数（请求体） | 类型 | 说明 |
|---|---|---|
| `type` | string | `single_choice` / `multiple_choice` / `text` / `number` |
| `title` | string | 1–200 个字符 |
| `options` | `[{text}]` | 选择题必填，1–50 个，文字 1–100 个字符且不重复；id 由系统生成 |
| `validation` | object | `required`（默认 false）；多选 `minSelect`、`maxSelect`；文本 `minLength`、`maxLength`（≤ 10000）；数字 `min`、`max`、`integerOnly`。字段与题型不匹配直接拒绝 |
| `position` | integer | 可选，插入到第几题（从 1 开始），默认末尾 |

添加时**不接受跳转规则**（新题的选项 id 尚未生成），添加后通过修改题目设置。

<details><summary>请求与返回示例</summary>

```json
// 请求
{ "type": "multiple_choice", "title": "你喜欢哪些水果？",
  "options": [ {"text": "苹果"}, {"text": "香蕉"}, {"text": "榴莲"} ],
  "validation": { "required": true, "minSelect": 1, "maxSelect": 2 } }
// 201：完整问卷，其中新题为
{ "id": "q_m2n3p4", "type": "multiple_choice", "title": "你喜欢哪些水果？",
  "options": [ {"id": "o_g7h8i9", "text": "苹果"}, {"id": "o_j1k2l3", "text": "香蕉"}, {"id": "o_x9y8z7", "text": "榴莲"} ],
  "validation": { "required": true, "minSelect": 1, "maxSelect": 2 } }
// 422
{ "code": "VALIDATION_ERROR", "message": "题目设置不合法",
  "errors": [ { "questionId": "q_m2n3p4", "field": "validation.minSelect",
                "message": "第 2 题：最少选择数（5）不能大于选项数（3）" } ] }
```
</details>

### `PUT /api/surveys/{id}/questions/{qid}` 修改题目

整体替换一道题（id 不变）：`type`、`title`、`options`（保留的选项带原 `id`，新增选项只写 `text`，未出现的选项视为删除）、`validation`、`logic`（不提交表示没有跳转规则）。

`logic` 格式：`{ "rules": [ { "when": { "op": 运算符, "value": 值 }, "goto": 后面某题的 id 或 "END" } ], "defaultNext": null | "END" | 后面某题的 id }`。运算符见 [README 八、关键逻辑说明 → 2. 跳转](../README.md#2-跳转)。

<details><summary>请求与返回示例</summary>

```json
// 请求：选了“不喜欢”就跳到第 5 题，否则顺序进入下一题
{ "type": "single_choice", "title": "你喜欢吃水果吗？",
  "options": [ {"id": "o_a1b2c3", "text": "喜欢"}, {"id": "o_d4e5f6", "text": "不喜欢"} ],
  "validation": { "required": true },
  "logic": { "rules": [ { "when": { "op": "eq", "value": "o_d4e5f6" }, "goto": "q_p0x7mn" } ], "defaultNext": null } }
// 200：完整问卷
// 422：往前跳
{ "code": "VALIDATION_ERROR", "message": "题目设置不合法",
  "errors": [ { "questionId": "q_k3x9ab", "field": "logic.rules[0].goto",
                "message": "第 2 题第 1 条规则：只能跳转到后面的题目或 END（目标是第 1 题）" } ] }
```
</details>

### `DELETE /api/surveys/{id}/questions/{qid}` 删除题目

返回完整问卷；被其他题的跳转规则指向时 409：

```json
{ "code": "QUESTION_REFERENCED", "message": "第 1 题「你喜欢吃水果吗？」的第 1 条规则跳转到这道题，请先修改该规则",
  "errors": [ { "field": "id", "questionId": "q_p0x7mn", "message": "第 1 题「你喜欢吃水果吗？」的第 1 条规则跳转到这道题" } ] }
```

### `PUT /api/surveys/{id}/questions/order` 调整顺序

请求体 `{ "questionIds": [...] }`，必须恰好包含全部题目 id；调整后出现往前跳时 422（顺序不变）。

## 4. 填写（填写者，均需登录）

### `GET /api/s/{shortCode}` 获取问卷

返回填写者视角的问卷：题目只含 `id`、`type`、`title`、`options`、`validation`（**不含跳转规则**，也不含 `ownerId` 等内部字段）。已关闭或已过期时 `accepting: false`、`questions: null` 并给出 `notice`；草稿只有创建者能预览（`preview: true`），其他人 404 `SURVEY_NOT_PUBLISHED`。

<details><summary>返回示例</summary>

```json
{ "shortCode": "Food26", "title": "大学生饮食习惯调查", "description": "...",
  "settings": { "allowAnonymous": false, "submissionPolicy": "latest", "deadline": null },
  "status": "published", "isExpired": false, "accepting": true, "notice": null,
  "isOwner": false, "preview": false,
  "questions": [ { "id": "q_...", "type": "single_choice", "title": "你目前是在校大学生（含研究生）吗？",
                   "options": [ {"id": "o_...", "text": "是"}, {"id": "o_...", "text": "否"} ],
                   "validation": { "required": true } } ],
  "mySubmission": { "count": 1, "lastSubmittedAt": "2026-10-20T08:30:00Z", "canSubmit": true, "reason": null,
                    "latestAnswers": [ { "questionId": "q_...", "value": "o_..." } ] } }
```

`mySubmission.latestAnswers` 只在 `latest` 策略下返回本人最新一份答案（用于再次填写时预填）。
</details>

### `POST /api/s/{shortCode}/path` 路径预览

请求体 `{ "answers": [ { "questionId": "...", "value": ... } ] }`（最多 200 项）。答案中**没有**的题视为“还没答到”，值为 `null` 表示“看过但不答”。返回 200（有错误也是 200，错误放在 `errors` 中），不保存。

<details><summary>请求与返回示例</summary>

```json
// 请求：第 1 题选了“不喜欢”
{ "answers": [ { "questionId": "q_k3x9ab", "value": "o_d4e5f6" } ] }
// 200：跳到第 5 题
{ "path": ["q_k3x9ab", "q_p0x7mn"], "nextQuestionId": "q_p0x7mn", "finished": false, "errors": [] }
```
</details>

### `POST /api/s/{shortCode}/responses` 提交答卷

请求体同路径预览。后端**从第一题开始重新计算跳转路径并校验**：路径上必答题未答或答案不合法 → 422（只返回第一个错误，不保存）；路径外的答案丢弃。成功返回 201 和实际保存的（规范化后的）答案。

| 值的格式 | 示例 |
|---|---|
| 单选 | 选项 id：`"o_a1b2c3"` |
| 多选 | 选项 id 数组：`["o_g7h8i9", "o_x9y8z7"]`（保存时按选项顺序排列） |
| 文本 | 字符串（保存时去掉首尾空白） |
| 数字 | JSON 数字（不接受字符串；整数题 `7.0` 保存为 `7`；整数须在 64 位范围内） |

<details><summary>请求与返回示例</summary>

```json
// 请求
{ "answers": [ { "questionId": "q_k3x9ab", "value": "o_a1b2c3" },
               { "questionId": "q_m2n3p4", "value": ["o_x9y8z7", "o_g7h8i9"] },
               { "questionId": "q_r5s6t7", "value": 7.0 } ] }
// 201
{ "id": "6ad610bc6f7a52178c8edbcd", "submittedAt": "2026-10-19T12:44:44.219000Z", "isLatest": true,
  "answers": [ { "questionId": "q_k3x9ab", "value": "o_a1b2c3" },
               { "questionId": "q_m2n3p4", "value": ["o_g7h8i9", "o_x9y8z7"] },
               { "questionId": "q_r5s6t7", "value": 7 } ] }
// 422
{ "code": "VALIDATION_ERROR", "message": "答案不合法",
  "errors": [ { "questionId": "q_r5s6t7", "field": "value", "message": "第 3 题：必须为整数" } ] }
// 409（once 策略再次提交）
{ "code": "ALREADY_SUBMITTED", "message": "你已经填写过这份问卷（每人只能填写一次）" }
```
</details>

## 5. 统计（只有问卷创建者可以查看）

统计口径：`latest` 只算每人最新一份；`once`、`all` 算全部答卷。每道题同时返回**答卷数** `answerCount` 与**作答人数** `respondentCount`（按填写人去重，匿名问卷也返回数字）。匿名问卷不返回任何填写人信息。

### `GET /api/surveys/{id}/stats` 整份问卷统计

选择题返回全部选项的人数（次数），没人选的为 0；填空题返回最新 20 条内容和总数 `itemsTotal`；数字题另有平均值 `average`（没人作答时为 null）。

<details><summary>返回示例</summary>

```json
{ "surveyId": "...", "title": "水果偏好调查", "status": "published",
  "allowAnonymous": false, "submissionPolicy": "once", "scope": "全部答卷（每人一份）",
  "totalResponses": 4, "totalRespondents": 4,
  "questions": [
    { "questionId": "q_k3x9ab", "type": "single_choice", "title": "你喜欢吃水果吗？",
      "answerCount": 4, "respondentCount": 4,
      "options": [ {"id": "o_a1b2c3", "text": "喜欢", "count": 3}, {"id": "o_d4e5f6", "text": "不喜欢", "count": 1} ] },
    { "questionId": "q_r5s6t7", "type": "number", "title": "你每周吃几次水果？",
      "answerCount": 3, "respondentCount": 3, "average": 3.3333333333333335, "itemsTotal": 3,
      "items": [ { "value": 0, "submittedAt": "...", "username": "zhao_liu" },
                 { "value": 3, "submittedAt": "...", "username": "li_si" },
                 { "value": 7, "submittedAt": "...", "username": "zhang_san" } ] } ] }
```

匿名问卷的 `items` 中没有 `username` 字段。
</details>

### `GET /api/surveys/{id}/stats/questions/{qid}` 单题统计

查询参数 `offset`（默认 0）、`limit`（默认 50，最多 200）：填空题内容分页，可以查看全部。返回问卷层面的总数、`question`（格式同上）、`offset`、`limit`。

### `GET /api/surveys/{id}/responses` 答卷列表

查询参数 `offset`（默认 0）、`limit`（默认 20，最多 100）。口径与统计一致（`latest` 不含历史版本），新的在前。

<details><summary>返回示例</summary>

```json
{ "surveyId": "...", "scope": "每人最新一份答卷", "total": 12, "offset": 0, "limit": 20,
  "items": [ { "id": "6ad6...", "submittedAt": "...", "username": "demo_s12",
               "answers": [ { "questionId": "q_...", "value": "o_..." } ] } ] }
```

匿名问卷的每一项没有 `username`。
</details>

## 6. 其他

- `GET /api/meta`：题型列表、各题型允许的校验字段、**运算符表**（直接来自 `app/logic/operators.py`）、各项长度上限。前端的跳转规则编辑器据此显示可选的运算符，不维护副本。不需要登录。
- `GET /api/health`：`{"status": "ok", "database": "ok"}`；数据库不可用时 503。
