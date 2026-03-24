#!/usr/bin/env python3
"""
Git API Gateway Doc - MD 文档生成器
支持自定义模板，从 JSON 接口数据渲染为 Markdown 文档
"""

import json
import re
import os
import sys
import argparse
from datetime import datetime
from string import Template


# ─────────────────────────────────────────────
# 内置默认模板
# ─────────────────────────────────────────────

# 可用变量（单个 API 条目）:
#   $method          - HTTP 方法，如 GET
#   $path            - 接口路径，如 /api/users/{pk}
#   $description     - 接口描述
#   $change_type     - 变更类型（新增/变更）
#   $route_name      - 路由名称
#   $source_file     - 来源文件
#   $auth_required   - 是否需要认证
#   $request_params  - 请求参数（自动渲染为表格）
#   $response_params - 响应参数（自动渲染为表格）
#   $error_codes     - 错误码（自动渲染为表格）
#
# 文档级变量:
#   $generated_at    - 生成时间
#   $source_diff     - 源 diff 文件名
#   $total_changes   - 总变更数
#   $new_apis        - 新增接口数
#   $modified_apis   - 变更接口数
#   $api_list        - 所有接口渲染后拼接的内容

DEFAULT_DOC_TEMPLATE = """\
# API 变更文档

> 生成时间：$generated_at  
> 来源文件：$source_diff  
> 接口总数：$total_changes（新增 $new_apis · 变更 $modified_apis）

---

$api_list
"""

DEFAULT_API_TEMPLATE = """\
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
"""

# 极简模板示例（可通过 --preset minimal 使用）
MINIMAL_API_TEMPLATE = """\
### $method $path

$description

请求参数：
$request_params

响应参数：
$response_params

"""

# 紧凑模板（表格风格）
COMPACT_API_TEMPLATE = """\
#### `$method` $path [$change_type]

> $description

$request_params
$response_params

"""

PRESETS = {
    "default": DEFAULT_API_TEMPLATE,
    "minimal": MINIMAL_API_TEMPLATE,
    "compact": COMPACT_API_TEMPLATE,
}


# ─────────────────────────────────────────────
# 表格渲染
# ─────────────────────────────────────────────

def render_params_table(params: list, columns: list, empty_msg: str = "_无_") -> str:
    """
    将参数列表渲染为 Markdown 表格
    columns: [(key, 表头名), ...]
    """
    if not params:
        return empty_msg

    header = "| " + " | ".join(col[1] for col in columns) + " |"
    sep    = "| " + " | ".join("------------ " for _ in columns) + " |"
    rows = []
    for p in params:
        cells = []
        for key, _ in columns:
            val = p.get(key, "")
            if isinstance(val, bool):
                val = "是" if val else "否"
            elif key == "required" and isinstance(val, str):
                val = "是" if val.lower() in ("true", "yes", "1", "是") else "否"
            cells.append(str(val) if val != "" else "-")
        rows.append("| " + " | ".join(cells) + " |")

    return "\n".join([header, sep] + rows)


def render_request_params(api: dict) -> str:
    """渲染请求参数（路径参数 + Query + Body 合并展示）"""
    req = api.get("request", {})
    all_params = []

    for loc_key, loc_label in [
        ("path_params", "path"),
        ("query_params", "query"),
        ("body_params", "body"),
    ]:
        for p in req.get(loc_key, []):
            all_params.append({**p, "location": loc_label})

    if not all_params:
        return "_无请求参数_"

    return render_params_table(
        all_params,
        columns=[
            ("name",        "参数名称"),
            ("type",        "参数类型"),
            ("required",    "必选"),
            ("description", "描述"),
        ],
    )


def render_response_params(api: dict) -> str:
    """渲染响应参数"""
    fields = api.get("response", {}).get("success", {}).get("fields", [])
    if not fields:
        return "_无响应字段_"
    return render_params_table(
        fields,
        columns=[
            ("name",        "参数名称"),
            ("type",        "参数类型"),
            ("description", "描述"),
        ],
    )


# 类型默认值映射
TYPE_DEFAULTS = {
    "integer": 0,
    "number":  0.0,
    "boolean": False,
    "array":   [],
    "object":  {},
    "any":     None,
    "string":  "",
}

def _default_value(field: dict):
    """根据字段 type 生成示例默认值"""
    t = field.get("type", "string")
    name = field.get("name", "")
    # 语义推断更贴切的示例值
    hints = {
        "id": 1, "pk": 1, "count": 0, "total": 0, "code": 0,
        "status": "active", "message": "success", "name": "示例名称",
        "email": "user@example.com", "phone": "13800138000",
        "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
        "url": "https://example.com", "date": "2026-01-01",
        "created_at": "2026-01-01T00:00:00", "updated_at": "2026-01-01T00:00:00",
        "description": "描述信息", "reason": "原因",
    }
    if name in hints:
        return hints[name]
    return TYPE_DEFAULTS.get(t, "")


def render_request_example(api: dict) -> str:
    """生成请求示例 JSON（body 参数）"""
    req = api.get("request", {})
    body_params = req.get("body_params", [])
    path_params = req.get("path_params", [])
    query_params = req.get("query_params", [])

    example = {}

    # body 参数组成请求体
    for p in body_params:
        example[p["name"]] = _default_value(p)

    # 无 body 时用 path/query 参数示意
    if not example:
        for p in path_params + query_params:
            example[p["name"]] = _default_value(p)

    if not example:
        return "_无请求体_"

    return "```json\n" + json.dumps(example, ensure_ascii=False, indent=2) + "\n```"


def render_response_example(api: dict) -> str:
    """生成响应示例 JSON，固定包裹 code/data 结构"""
    fields = api.get("response", {}).get("success", {}).get("fields", [])
    status_code = api.get("response", {}).get("success", {}).get("status_code", 200)

    # 构建 data 对象
    data_obj = {}
    for f in fields:
        name = f.get("name", "")
        # code/message 等顶层字段不放进 data
        if name in ("code", "message", "msg", "error", "detail"):
            continue
        data_obj[name] = _default_value(f)

    # 固定外层结构
    example = {
        "code": 0,
        "message": "success",
        "data": data_obj if data_obj else {},
    }

    return "```json\n" + json.dumps(example, ensure_ascii=False, indent=2) + "\n```"


def render_error_codes(api: dict) -> str:
    """渲染错误码表格"""
    codes = api.get("response", {}).get("error_codes", [])
    if not codes:
        return "_无_"
    return render_params_table(
        codes,
        columns=[
            ("code",        "状态码"),
            ("description", "说明"),
        ],
    )


# ─────────────────────────────────────────────
# 自定义模板引擎（支持 ### 等原生 Markdown 符号）
# ─────────────────────────────────────────────

def safe_substitute(template_str: str, mapping: dict) -> str:
    """
    安全替换模板变量，未找到的变量保留原样（不报错）
    支持 $var 和 ${var} 两种格式
    """
    def replacer(match):
        # 匹配 ${varname} 或 $varname
        var = match.group(1) or match.group(2)
        return str(mapping.get(var, match.group(0)))

    pattern = re.compile(r'\$\{(\w+)\}|\$(\w+)')
    return pattern.sub(replacer, template_str)


# ─────────────────────────────────────────────
# 核心渲染函数
# ─────────────────────────────────────────────

def render_api_block(api: dict, api_template: str) -> str:
    """
    渲染单个 API 条目
    """
    mapping = {
        "method":           api.get("method", ""),
        "path":             api.get("path", ""),
        "description":      api.get("description", ""),
        "change_type":      api.get("change_type", ""),
        "route_name":       api.get("route_name", ""),
        "source_file":      api.get("source_file", ""),
        "auth_required":    "需要" if api.get("auth_required") else "不需要",
        "request_params":   render_request_params(api),
        "response_params":  render_response_params(api),
        "error_codes":      render_error_codes(api),
        "request_example":  render_request_example(api),
        "response_example": render_response_example(api),
    }
    return safe_substitute(api_template, mapping)


def render_document(doc: dict, doc_template: str, api_template: str) -> str:
    """
    渲染完整 MD 文档
    """
    meta = doc.get("meta", {})

    # 先渲染所有 API 块
    api_blocks = [render_api_block(api, api_template) for api in doc.get("apis", [])]
    api_list = "\n".join(api_blocks)

    mapping = {
        "generated_at":   meta.get("generated_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        "source_diff":    meta.get("source_diff", ""),
        "total_changes":  str(meta.get("total_changes", len(doc.get("apis", [])))),
        "new_apis":       str(meta.get("new_apis", 0)),
        "modified_apis":  str(meta.get("modified_apis", 0)),
        "api_list":       api_list,
    }
    return safe_substitute(doc_template, mapping)


# ─────────────────────────────────────────────
# 从 diff/json 生成 MD 的主函数
# ─────────────────────────────────────────────

def _safe_filename(api: dict) -> str:
    """
    根据 API 的 method + path 生成安全的文件名
    例如: GET /inventory/stock-levels/{pk}/adjust → GET_inventory_stock-levels_{pk}_adjust.md
    """
    method = api.get("method", "UNKNOWN").upper()
    path   = api.get("path", "unknown").strip("/")
    # 将路径分隔符和特殊字符替换为下划线
    safe_path = re.sub(r"[/\s]", "_", path)
    safe_path = re.sub(r"[^\w\-.]", "", safe_path)
    # return f"{method}_{safe_path}.md"
    return f"{safe_path}.md"


def generate_md(
        input_file: str,
        output_file: str = None,
        output_dir: str = None,
        api_template: str = None,
        doc_template: str = None,
        preset: str = "default",
        api_filter: str = None,
        split_files: bool = False,
) -> str:
    """
    主入口：读取 JSON 接口文档 → 渲染为 Markdown

    Args:
        input_file:   JSON 文档路径（由 parse_git_diff.py 生成）
        output_file:  输出 .md 文件路径（合并模式，可选）
        output_dir:   输出目录（split_files=True 时必填，每个 API 单独一个文件）
        api_template: 单个 API 的 Markdown 模板字符串（可选，优先级高于 preset）
        doc_template: 整体文档模板字符串（可选）
        preset:       内置模板名称 default | minimal | compact
        api_filter:   只输出指定变更类型 "新增" | "变更"（可选）
        split_files:  True = 每个 API 单独生成一个 .md 文件

    Returns:
        str: 合并模式时返回完整 MD 内容；split 模式时返回生成文件列表（换行分隔）
    """
    # 读取 JSON
    with open(input_file, "r", encoding="utf-8") as f:
        doc = json.load(f)

    # 过滤
    if api_filter:
        doc["apis"] = [a for a in doc["apis"] if a.get("change_type") == api_filter]
        doc["meta"]["total_changes"] = len(doc["apis"])

    # 选定模板
    chosen_api_template = api_template or PRESETS.get(preset, DEFAULT_API_TEMPLATE)
    chosen_doc_template = doc_template or DEFAULT_DOC_TEMPLATE

    # ── 拆分模式：每个 API 单独一个文件 ──────────
    if split_files:
        base_dir = output_dir or "api_docs"
        os.makedirs(base_dir, exist_ok=True)

        generated = []
        for api in doc.get("apis", []):
            md_content = render_api_block(api, chosen_api_template)
            filename   = _safe_filename(api)
            filepath   = os.path.join(base_dir, filename)

            with open(filepath, "w", encoding="utf-8") as f:
                f.write(md_content)

            generated.append(filepath)
            print(f"  📄 {filepath}")

        print(f"\n✅ 共生成 {len(generated)} 个 API 文档 → {base_dir}/")
        return "\n".join(generated)

    # ── 合并模式：所有 API 输出到单个文件 ─────────
    md_content = render_document(doc, chosen_doc_template, chosen_api_template)

    if output_file:
        os.makedirs(os.path.dirname(output_file) if os.path.dirname(output_file) else ".", exist_ok=True)
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(md_content)
        print(f"✅ Markdown 文档已生成: {output_file}")

    return md_content


# ─────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="API JSON → 自定义 Markdown 文档生成器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=r"""
示例:

  # 使用默认模板
  python generate_md.py -i api_doc.json -o api_doc.md

  # 使用内置精简模板
  python generate_md.py -i api_doc.json -o api_doc.md --preset minimal

  # 使用自定义 API 模板（命令行传入）
  python generate_md.py -i api_doc.json -o api_doc.md \
    --api-template "### $method $path\n**说明**: $description\n\n$request_params\n"

  # 从外部模板文件读取
  python generate_md.py -i api_doc.json -o api_doc.md \
    --api-template-file my_template.md

  # 只输出新增接口
  python generate_md.py -i api_doc.json -o new_only.md --filter 新增

可用模板变量（API 级别）:
  $method          HTTP 方法（GET/POST/PUT/PATCH/DELETE）
  $path            接口路径（如 /api/users/{pk}）
  $description     接口描述
  $change_type     变更类型（新增/变更）
  $route_name      路由名称
  $source_file     来源文件
  $auth_required   认证要求（需要/不需要）
  $request_params  请求参数表格（自动渲染）
  $response_params 响应参数表格（自动渲染）
  $error_codes     错误码表格（自动渲染）

可用模板变量（文档级别）:
  $generated_at    生成时间
  $source_diff     源 diff 文件名
  $total_changes   总接口数
  $new_apis        新增接口数
  $modified_apis   变更接口数
  $api_list        所有 API 块拼接内容
        """,
    )

    parser.add_argument("--input",  "-i", required=True,  help="输入 JSON 文件路径")
    parser.add_argument("--output", "-o",                  help="合并模式：输出 MD 文件路径（不传则打印到控制台）")
    parser.add_argument("--split",  "-s", action="store_true",
                        help="拆分模式：每个 API 单独生成一个 .md 文件")
    parser.add_argument("--output-dir", "-od", default="api_docs",
                        help="拆分模式下的输出目录（默认 api_docs/）")
    parser.add_argument("--preset", "-p", default="default",
                        choices=list(PRESETS.keys()),      help="内置模板预设（default/minimal/compact）")
    parser.add_argument("--api-template",      "-t",       help="自定义 API 模板字符串（优先级最高）")
    parser.add_argument("--api-template-file", "-tf",      help="从文件读取自定义 API 模板")
    parser.add_argument("--doc-template-file", "-df",      help="从文件读取自定义文档模板")
    parser.add_argument("--filter", "-f",
                        choices=["新增", "变更"],           help="只输出指定变更类型的接口")
    parser.add_argument("--show-presets",                  action="store_true",
                        help="打印所有内置模板内容后退出")

    args = parser.parse_args()

    # 打印预设
    if args.show_presets:
        for name, tpl in PRESETS.items():
            print(f"\n{'='*40}\n[preset: {name}]\n{'='*40}")
            print(tpl)
        sys.exit(0)

    # 读取模板文件
    api_template = args.api_template
    if not api_template and args.api_template_file:
        with open(args.api_template_file, "r", encoding="utf-8") as f:
            api_template = f.read()

    doc_template = None
    if args.doc_template_file:
        with open(args.doc_template_file, "r", encoding="utf-8") as f:
            doc_template = f.read()

    # 生成
    md = generate_md(
        input_file=args.input,
        output_file=args.output,
        output_dir=args.output_dir,
        api_template=api_template,
        doc_template=doc_template,
        preset=args.preset,
        api_filter=args.filter,
        split_files=args.split,
    )

    if not args.split and not args.output:
        print(md)


if __name__ == "__main__":
    main()
