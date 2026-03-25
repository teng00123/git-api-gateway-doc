#!/usr/bin/env python3
"""
Git API Gateway Doc - AI 字段描述增强器（Agent 驱动模式）

本脚本不自行调用 AI，而是将任务拆成两步：
  1. --export-prompts  → 扫描 JSON，输出待填充的 prompts.json（任务清单）
  2. --apply-results   → 读取 Agent 填好结果的 prompts.json，写回 api_doc.json

由调用方（任意 Agent）负责读取 prompts.json、逐个调用 AI、填写 result 字段后，
再调用 --apply-results 写回。

使用方式:
  # Step A: 导出任务清单
  python3 enrich_api_doc.py --export-prompts -i api_doc.json -o prompts.json

  # Step B: （由 Agent 完成）读取 prompts.json，逐个调 AI 填写 result 字段

  # Step C: 将结果写回 api_doc.json
  python3 enrich_api_doc.py --apply-results -p prompts.json -i api_doc.json
  python3 enrich_api_doc.py --apply-results -p prompts.json -i api_doc.json --inplace
  python3 enrich_api_doc.py --apply-results -p prompts.json -i api_doc.json -o enriched.json

兼容旧用法（保留 --dry-run，打印任务预览）:
  python3 enrich_api_doc.py -i api_doc.json --dry-run
"""

import json
import sys
import os
import argparse


# ─────────────────────────────────────────────
# Prompt 构造（批量：每个接口一个 prompt）
# ─────────────────────────────────────────────

def build_batch_prompt(api: dict, need_desc: bool, req_fields: list, resp_fields: list) -> str:
    """
    将一个接口的所有待填字段打包成单个 prompt，要求 AI 返回 JSON。

    need_desc:   是否需要生成接口描述
    req_fields:  [(loc_key, field_index, field_dict), ...]
    resp_fields: [(field_index, field_dict), ...]
    """
    method = api.get("method", "")
    path = api.get("path", "")
    func_name = api.get("route_name") or api.get("func_name", "")
    current_desc = api.get("description", "")

    # 构造字段清单
    field_lines = []
    field_keys = []  # 与 field_lines 对应，用于 apply 时定位

    if need_desc:
        req = api.get("request", {})
        all_params = (
                req.get("path_params", []) +
                req.get("query_params", []) +
                req.get("body_params", [])
        )
        param_names = ", ".join(p["name"] for p in all_params) if all_params else "无"
        field_lines.append(f'  "api_desc": "接口功能描述（15字以内）"  // {method} {path}，函数名: {func_name}，参数: {param_names}')
        field_keys.append(("api_desc", None, None, None))

    for loc_key, j, param in req_fields:
        key = f"req_{loc_key}_{j}"
        field_lines.append(f'  "{key}": "字段说明（10字以内）"  // 请求参数 {param["name"]}（{param.get("type","string")}）')
        field_keys.append(("request_field", loc_key, j, None))

    for j, field in resp_fields:
        key = f"resp_{j}"
        field_lines.append(f'  "{key}": "字段说明（10字以内）"  // 响应参数 {field["name"]}（{field.get("type","string")}）')
        field_keys.append(("response_field", None, None, j))

    fields_block = "\n".join(field_lines)

    prompt = f"""你是一个 API 文档专家。请为以下接口的字段批量生成简洁的中文描述，直接返回 JSON，不要任何解释。

接口: {method} {path}
当前描述: {current_desc or "（待生成）"}

请填写以下 JSON 中每个字段的描述（替换引号内的说明文字，保持 key 不变）：

{{
{fields_block}
}}

要求：
- 每个值 10 字以内（api_desc 15 字以内）
- 不加标点符号，不带引号
- 只输出 JSON，不要任何其他内容"""

    return prompt, field_keys


# ─────────────────────────────────────────────
# 收集任务（按接口批量）
# ─────────────────────────────────────────────

def collect_tasks(doc: dict, force: bool = False) -> list:
    """
    扫描 JSON，按接口维度收集批量任务。

    每个任务结构：
    {
      "id": "batch_{api_index}",
      "api_index": int,
      "kind": "batch",
      "label": "GET /path （N 个字段）",
      "prompt": "发给 AI 的完整批量 prompt",
      "field_keys": [...],   # 与 prompt 中字段对应的写回路径
      "result": {}           # 由 Agent 填写：{"api_desc": "...", "req_query_params_0": "...", ...}
    }
    """
    tasks = []
    for i, api in enumerate(doc.get("apis", [])):
        method = api.get("method", "")
        path = api.get("path", "")

        need_desc = force or not api.get("description", "") or api.get("description", "").endswith("接口")

        req = api.get("request", {})
        req_fields = []
        for loc_key in ("path_params", "query_params", "body_params"):
            for j, param in enumerate(req.get(loc_key, [])):
                if force or not param.get("description", ""):
                    req_fields.append((loc_key, j, param))

        resp_fields_raw = api.get("response", {}).get("success", {}).get("fields", [])
        resp_fields = [
            (j, field)
            for j, field in enumerate(resp_fields_raw)
            if force or not field.get("description", "")
        ]

        if not need_desc and not req_fields and not resp_fields:
            continue

        total = (1 if need_desc else 0) + len(req_fields) + len(resp_fields)
        prompt, field_keys = build_batch_prompt(api, need_desc, req_fields, resp_fields)

        tasks.append({
            "id": f"batch_{i}",
            "api_index": i,
            "kind": "batch",
            "label": f"{method} {path} （{total} 个字段）",
            "prompt": prompt,
            "field_keys": field_keys,
            "result": {},
        })

    return tasks


# ─────────────────────────────────────────────
# 写回结果
# ─────────────────────────────────────────────

def apply_batch_result(doc: dict, task: dict):
    """将一条批量任务的 result dict 写回 doc"""
    i = task["api_index"]
    api = doc["apis"][i]
    result = task.get("result", {})
    if not result:
        return 0

    written = 0
    for fk in task["field_keys"]:
        kind, loc_key, req_j, resp_j = fk

        if kind == "api_desc":
            val = result.get("api_desc", "").strip().strip("。，、；：").strip()
            if val:
                api["description"] = val
                written += 1

        elif kind == "request_field":
            key = f"req_{loc_key}_{req_j}"
            val = result.get(key, "").strip().strip("。，、；：").strip()
            if val:
                api["request"][loc_key][req_j]["description"] = val
                written += 1

        elif kind == "response_field":
            key = f"resp_{resp_j}"
            val = result.get(key, "").strip().strip("。，、；：").strip()
            if val:
                api["response"]["success"]["fields"][resp_j]["description"] = val
                written += 1

    return written


# ─────────────────────────────────────────────
# 主流程
# ─────────────────────────────────────────────

def cmd_export_prompts(args):
    """--export-prompts：扫描 JSON，输出 prompts.json 批量任务清单"""
    with open(args.input, "r", encoding="utf-8") as f:
        doc = json.load(f)

    tasks = collect_tasks(doc, force=args.force)

    if not tasks:
        print("✅ 所有字段描述已完整，无需增强。")
        return

    total_fields = sum(len(t["field_keys"]) for t in tasks)
    print(f"📋 共 {len(tasks)} 个接口需要 AI 生成描述（合计 {total_fields} 个字段）")
    for t in tasks:
        print(f"   [{t['id']}] {t['label']}")

    out_path = args.output or "prompts.json"
    os.makedirs(os.path.dirname(out_path) if os.path.dirname(out_path) else ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(tasks, f, ensure_ascii=False, indent=2)
    print(f"\n💾 任务清单已保存到: {out_path}")
    print()
    print("📌 下一步：由 Agent 读取该文件，对每条任务调用 AI，")
    print("   将返回的 JSON 填入对应任务的 result 字段，然后执行：")
    print(f"   python3 enrich_api_doc.py --apply-results -p {out_path} -i {args.input}")


def cmd_apply_results(args):
    """--apply-results：读取 Agent 填好的 prompts.json，写回 api_doc.json"""
    with open(args.input, "r", encoding="utf-8") as f:
        doc = json.load(f)

    with open(args.prompts, "r", encoding="utf-8") as f:
        tasks = json.load(f)

    total_written = 0
    skip = 0
    for task in tasks:
        if not task.get("result"):
            print(f"  ⚠️  跳过（result 为空）: {task.get('label', task.get('id', ''))}")
            skip += 1
            continue
        written = apply_batch_result(doc, task)
        total_written += written

    print(f"\n✅ 写回完成：共写入 {total_written} 个字段描述，跳过 {skip} 条任务")

    out_path = args.input if args.inplace else (args.output or args.input)
    os.makedirs(os.path.dirname(out_path) if os.path.dirname(out_path) else ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
    print(f"💾 已保存到: {out_path}")


def cmd_dry_run(args):
    """--dry-run：仅打印任务预览，不写文件"""
    with open(args.input, "r", encoding="utf-8") as f:
        doc = json.load(f)

    tasks = collect_tasks(doc, force=args.force)

    if not tasks:
        print("✅ 所有字段描述已完整，无需增强。")
        return

    total_fields = sum(len(t["field_keys"]) for t in tasks)
    print(f"📋 共 {len(tasks)} 个批量任务（合计 {total_fields} 个字段）\n")
    for idx, t in enumerate(tasks):
        print(f"  [{idx+1}/{len(tasks)}] {t['label']}")
        print(f"  Prompt 预览: {t['prompt'][:200]}...")
        print()


# ─────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="API JSON 字段描述 AI 增强器（Agent 驱动模式）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
工作流:
  # Step 1: 导出任务清单
  python3 enrich_api_doc.py --export-prompts -i api_doc.json -o prompts.json

  # Step 2: （由 Agent 完成）读取 prompts.json，为每条任务的 result 字段填写 AI 生成的描述

  # Step 3: 写回结果（原地覆盖）
  python3 enrich_api_doc.py --apply-results -p prompts.json -i api_doc.json --inplace

  # Step 3: 写回结果（输出到新文件）
  python3 enrich_api_doc.py --apply-results -p prompts.json -i api_doc.json -o enriched.json

  # 预览任务（不写文件）
  python3 enrich_api_doc.py --dry-run -i api_doc.json
        """,
    )

    parser.add_argument("--input",          "-i", required=True,       help="输入 JSON 文件路径（api_doc.json）")
    parser.add_argument("--output",         "-o",                      help="输出 JSON 文件路径")
    parser.add_argument("--inplace",              action="store_true", help="原地覆盖输入文件（用于 --apply-results）")
    parser.add_argument("--force",                action="store_true", help="强制重新生成所有描述（包括已有的）")

    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--export-prompts",   action="store_true", help="导出任务清单到 prompts.json（默认输出路径 prompts.json）")
    mode.add_argument("--apply-results",    action="store_true", help="将 Agent 填写好的 prompts.json 结果写回 JSON")
    mode.add_argument("--dry-run",          action="store_true", help="预览任务，不写文件（兼容旧用法）")

    parser.add_argument("--prompts",        "-p",                      help="prompts.json 文件路径（--apply-results 时必填）")

    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"❌ 文件不存在: {args.input}")
        sys.exit(1)

    if args.apply_results:
        if not args.prompts:
            print("❌ --apply-results 需要指定 --prompts / -p")
            sys.exit(1)
        if not os.path.exists(args.prompts):
            print(f"❌ prompts 文件不存在: {args.prompts}")
            sys.exit(1)
        cmd_apply_results(args)

    elif args.export_prompts:
        cmd_export_prompts(args)

    elif args.dry_run:
        cmd_dry_run(args)

    else:
        # 默认行为：export-prompts（无模式参数时）
        print("ℹ️  未指定模式，默认执行 --export-prompts")
        print("   提示：使用 --export-prompts / --apply-results / --dry-run 明确指定模式\n")
        cmd_export_prompts(args)


if __name__ == "__main__":
    main()
