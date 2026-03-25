---
name: git-api-gateway-doc
description: Scan git diff for new or modified API interfaces and generate gateway documentation in standardized format. Use when user requests API documentation generation from git changes, asks to document new endpoints, or needs gateway docs for recent interface modifications. Triggers on phrases like "generate gateway docs from git diff", "document new APIs", "scan git for interface changes", "API gateway documentation" etc.
---

# Git API Gateway Doc

## ⚠️ 严格约束（必须遵守）

1. **用户必须提供真实的 diff 文件或 diff 内容**，才能执行本 skill。
2. **禁止在任何情况下自动生成示例 diff、演示项目或 demo 数据**，即使解析结果为空。
3. 如果解析结果 `total_changes = 0`（无 API 变更），**只输出提示信息，立即停止，不生成任何文件**。
4. 用户未提供 diff 时，**只询问 diff 文件路径，不做其他任何操作**。

```
✅ 用户给了 diff → 解析 → 有 API → 生成文档
✅ 用户给了 diff → 解析 → 无 API → 提示"未检测到 API 变更，请确认 diff 包含 urls.py 或 views.py 的修改"
❌ 用户未给 diff  → 禁止生成 demo / 示例 / 演示项目
❌ 解析结果为空  → 禁止补充 demo 数据或示例接口
```

---

## Overview

从 Django / DRF 项目的 `git diff` 文件中自动识别新增和变更的 API 接口，生成标准化 Markdown 文档。

**两个核心脚本：**
- `scripts/parse_git_diff.py` — 解析 diff → 输出结构化 JSON
- `scripts/generate_md.py` — 读取 JSON + 模板 → 输出 Markdown（每个接口一个文件）

**内置模板文件（优先使用）：**
- `assets/default_template.md` — 完整格式（含请求/响应参数、示例、错误码）
- `assets/minimal_template.md` — 精简格式（仅含请求参数和示例）

---

## Workflow（标准流程）

### Step 1：获取 git diff

```bash
git diff HEAD~1 > changes.diff
# 或分支对比
git diff main..feature-branch > changes.diff
```

### Step 2：解析 diff → JSON

```bash
python3 scripts/parse_git_diff.py \
  --diff-file changes.diff \
  --output api_doc.json
```

### Step 2.5（可选）：AI 增强字段描述

本步骤由 **Agent 自身驱动**，脚本不调用任何 AI 接口，适配任意平台。

**Step 2.5-A：导出待填充的任务清单**

```bash
python3 scripts/enrich_api_doc.py --export-prompts \
  -i api_doc.json \
  -o prompts.json

# 强制重新生成所有描述（包括已有的）
python3 scripts/enrich_api_doc.py --export-prompts \
  -i api_doc.json \
  -o prompts.json \
  --force

# 预览任务，不写文件
python3 scripts/enrich_api_doc.py --dry-run -i api_doc.json
```

**Step 2.5-B：Agent 填充描述（由你完成）**

读取 `prompts.json`，其中每条任务对应**一个接口**的所有空字段，包含：
- `label`：接口标识，如 `GET /articles/ （6 个字段）`
- `prompt`：发给 AI 的批量 prompt，要求 AI 返回 JSON
- `field_keys`：字段写回路径（脚本内部使用，无需关注）
- `result`：**需要你填写 AI 返回的 JSON 对象**，key 与 prompt 中一致

对每条任务，将 AI 返回的 JSON 填入 `result` 字段，保存文件。

> **批量设计**：每个接口的所有字段打包为一个 prompt，AI 一次返回所有字段描述，
> 接口数量即为 AI 调用次数（而非字段总数），大幅减少调用轮次。

**Step 2.5-C：将结果写回 api_doc.json**

```bash
# 原地覆盖
python3 scripts/enrich_api_doc.py --apply-results \
  -p prompts.json \
  -i api_doc.json \
  --inplace

# 输出到新文件
python3 scripts/enrich_api_doc.py --apply-results \
  -p prompts.json \
  -i api_doc.json \
  -o api_doc_enriched.json
```

### Step 3：使用模板生成 MD（每个接口单独一个文件）

```bash
# ✅ 推荐：使用内置 default 模板
python3 scripts/generate_md.py \
  --input api_doc.json \
  --split \
  --output-dir api_docs/ \
  --api-template-file assets/default_template.md

# 精简模板
python3 scripts/generate_md.py \
  --input api_doc.json \
  --split \
  --output-dir api_docs/ \
  --api-template-file assets/minimal_template.md

# 只输出新增接口
python3 scripts/generate_md.py \
  --input api_doc.json \
  --split \
  --output-dir api_docs/ \
  --api-template-file assets/default_template.md \
  --filter 新增
```

### 一键端到端（含 AI 增强）

```bash
# Step 1-2: 解析 diff → 导出任务清单
git diff HEAD~1 > changes.diff && \
python3 scripts/parse_git_diff.py -d changes.diff -o api_doc.json && \
python3 scripts/enrich_api_doc.py --export-prompts -i api_doc.json -o prompts.json

# Step 3: 由 Agent 读取 prompts.json，填写每条 result 字段

# Step 4: 写回 + 生成 MD
python3 scripts/enrich_api_doc.py --apply-results -p prompts.json -i api_doc.json --inplace && \
python3 scripts/generate_md.py \
  -i api_doc.json \
  --split \
  --output-dir api_docs/ \
  --api-template-file assets/default_template.md
```

不需要 AI 增强时，跳过 Step 2.5 直接生成：

```bash
git diff HEAD~1 > changes.diff && \
python3 scripts/parse_git_diff.py -d changes.diff -o api_doc.json && \
python3 scripts/generate_md.py \
  -i api_doc.json \
  --split \
  --output-dir api_docs/ \
  --api-template-file assets/default_template.md
```

---

## 内置模板说明

### assets/default_template.md（完整格式）

```
### $change_type | `$method` $path

**描述：** $description  
**来源：** `$source_file`  
**认证：** $auth_required

#### 请求参数

$request_params

#### 请求示例

$request_example

#### 响应参数

$response_params

#### 响应示例

$response_example

#### 错误码

$error_codes

---
```

### assets/minimal_template.md（精简格式）

```
### $method $path

**描述：** $description

#### 请求参数

$request_params

#### 请求示例

$request_example

#### 响应示例

$response_example

---
```

### 自定义模板

如需自定义，复制 `assets/default_template.md` 修改后，用 `--api-template-file` 指定即可。模板是普通文本文件，用 `$变量名` 作为占位符，Markdown 语法（`###`、`**` 等）直接写入，原样保留。

---

## 模板可用变量

### API 级别

| 变量 | 内容 |
| ------------ | ------------ |
| `$method` | HTTP 方法（GET / POST / PUT / PATCH / DELETE） |
| `$path` | 接口路径（如 `/api/users/{pk}`） |
| `$description` | 接口描述 |
| `$change_type` | 变更类型（新增 / 变更） |
| `$route_name` | 路由名称 |
| `$source_file` | 来源文件路径 |
| `$auth_required` | 认证要求（需要 / 不需要） |
| `$request_params` | 请求参数表格（自动渲染） |
| `$response_params` | 响应参数表格（自动渲染） |
| `$request_example` | 请求体 JSON 示例代码块 |
| `$response_example` | 响应 JSON 示例，固定 `code/message/data` 结构 |
| `$error_codes` | 错误码表格（自动渲染） |

### 文档级别（用于 `--doc-template-file`）

| 变量 | 内容 |
| ------------ | ------------ |
| `$generated_at` | 生成时间 |
| `$source_diff` | 源 diff 文件名 |
| `$total_changes` | 总接口数 |
| `$new_apis` | 新增接口数 |
| `$modified_apis` | 变更接口数 |
| `$api_list` | 所有 API 块拼接内容 |

---

## 输出格式

### 参数表格

```
| 参数名称 | 参数类型 | 必选 | 描述 |
| ------------ | ------------ | ------------ | ------------ |
| account_id   | integer      | 是           | 用户ID        |
| page         | integer      | 否           | 页码          |
```

### 响应示例（固定外层结构）

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "id": 1,
    "name": "示例名称"
  }
}
```

### 生成文件命名规则

拆分模式下文件名格式：`{METHOD}_{路径下划线连接}.md`

```
POST /inventory/transfer-stock  →  POST_inventory_transfer-stock.md
GET  /users/{pk}/profile        →  GET_users_pk_profile.md
```

---

## generate_md.py 完整参数

| 参数 | 简写 | 说明 |
| ------------ | ------------ | ------------ |
| `--input` | `-i` | 输入 JSON 文件路径（必填） |
| `--split` | `-s` | 拆分模式：每个 API 单独一个 .md 文件 |
| `--output-dir` | `-od` | 拆分模式输出目录（默认 `api_docs/`） |
| `--output` | `-o` | 合并模式：所有 API 输出到一个 .md 文件 |
| `--api-template-file` | `-tf` | 模板文件路径（优先级最高，推荐使用） |
| `--api-template` | `-t` | 直接传入模板字符串 |
| `--doc-template-file` | `-df` | 文档级模板文件路径 |
| `--preset` | `-p` | 内置预设：`default` / `minimal` / `compact` |
| `--filter` | `-f` | 过滤变更类型：`新增` 或 `变更` |
| `--show-presets` | — | 打印所有内置预设模板内容 |

## parse_git_diff.py 完整参数

| 参数 | 简写 | 说明 |
| ------------ | ------------ | ------------ |
| `--diff-file` | `-d` | git diff 文件路径（必填） |
| `--output` | `-o` | 输出 JSON 文件路径（不填则打印到控制台） |

---

## 注意事项

- 仅解析 `urls.py` 和 `views.py` 中的变更行（`+` 开头）
- `serializers.py` / `models.py` 变更仅用于类型推断，不单独生成接口
- URL 前缀自动从 app 目录名推断（`inventory_management/views.py` → `/inventory_management`）
- `auth_required` 默认 `true`，可在 JSON 中手动修改后重新渲染

## scripts/

- `parse_git_diff.py`：解析 Django/DRF git diff，输出结构化 API JSON
- `enrich_api_doc.py`：AI 字段描述增强器（Agent 驱动模式，平台无关）
  - `--export-prompts`：扫描 JSON，输出 prompts.json 任务清单（含每条字段的 prompt）
  - `--apply-results`：读取 Agent 填好 result 的 prompts.json，写回 api_doc.json
  - `--dry-run`：预览任务，不写文件
- `generate_md.py`：读取 API JSON + 模板，渲染为 Markdown 文档

## assets/

- `default_template.md`：默认完整格式模板（推荐）
- `minimal_template.md`：精简格式模板
