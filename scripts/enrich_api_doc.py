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
# Prompt 构造
# ─────────────────────────────────────────────

def build_api_desc_prompt(api: dict) -> str:
    method = api.get("method", "")
    path = api.get("path", "")
    func_name = api.get("route_name") or api.get("func_name", "")
    req = api.get("request", {})
    body_params = req.get("body_params", [])
    query_params = req.get("query_params", [])
    path_params = req.get("path_params", [])

    params_desc = ""
    if path_params:
        params_desc += f"路径参数: {', '.join(p['name'] for p in path_params)}\n"
    if query_params:
        params_desc += f"查询参数: {', '.join(p['name'] for p in query_params)}\n"
    if body_params:
        params_desc += f"请求体参数: {', '.join(p['name'] for p in body_params)}\n"

    return (
        f"你是一个 API 文档专家，请根据以下信息，用中文写一句简洁的接口功能描述"
        f"（15字以内，不加标点符号，不要带引号，直接输出描述文字）。\n\n"
        f"接口方法: {method}\n"
        f"接口路径: {path}\n"
        f"函数名: {func_name}\n"
        f"{params_desc}\n"
        f"只输出描述，不要解释，不要换行。"
    )


def build_field_desc_prompt(api: dict, field: dict, field_kind: str) -> str:
    method = api.get("method", "")
    path = api.get("path", "")
    api_desc = api.get("description", "")
    fname = field.get("name", "")
    ftype = field.get("type", "string")

    return (
        f"你是一个 API 文档专家，请根据以下信息，用中文写一句简洁的字段说明"
        f"（10字以内，不加标点符号，不要带引号，直接输出说明文字）。\n\n"
        f"所属接口: {method} {path}\n"
        f"接口描述: {api_desc}\n"
        f"字段位置: {field_kind}\n"
        f"字段名称: {fname}\n"
        f"字段类型: {ftype}\n\n"
        f"只输出字段说明，不要解释，不要换行。"
    )


# ─────────────────────────────────────────────
# 收集任务
# ─────────────────────────────────────────────

def collect_tasks(doc: dict, force: bool = False) -> list:
    """
    扫描 JSON，收集所有需要 AI 生成描述的任务。

    每个任务结构：
    {
      "id": "唯一标识（api索引_kind_字段索引）",
      "api_index": int,
      "kind": "api_desc" | "request_field" | "response_field",
      "loc_key": str,        # 仅 request_field 有
      "field_index": int,    # 仅 request_field / response_field 有
      "label": "用于展示的可读标签",
      "prompt": "发给 AI 的完整 prompt",
      "current": "当前值（空则需要填）",
      "result": ""           # 由 Agent 填写后回填此字段
    }
    """
    tasks = []
    for i, api in enumerate(doc.get("apis", [])):
        method = api.get("method", "")
        path = api.get("path", "")

        # 接口描述
        desc = api.get("description", "")
        if force or not desc or desc.endswith("接口"):
            tasks.append({
                "id": f"{i}_api_desc",
                "api_index": i,
                "kind": "api_desc",
                "label": f"接口描述 | {method} {path}",
                "prompt": build_api_desc_prompt(api),
                "current": desc,
                "result": "",
            })

        # 请求参数字段
        req = api.get("request", {})
        for loc_key in ("path_params", "query_params", "body_params"):
            for j, param in enumerate(req.get(loc_key, [])):
                if force or not param.get("description", ""):
                    tasks.append({
                        "id": f"{i}_request_{loc_key}_{j}",
                        "api_index": i,
                        "kind": "request_field",
                        "loc_key": loc_key,
                        "field_index": j,
                        "label": f"请求字段 | {method} {path} → {param.get('name', '')}",
                        "prompt": build_field_desc_prompt(api, param, "请求参数"),
                        "current": param.get("description", ""),
                        "result": "",
                    })

        # 响应参数字段
        resp_fields = api.get("response", {}).get("success", {}).get("fields", [])
        for j, field in enumerate(resp_fields):
            if force or not field.get("description", ""):
                tasks.append({
                    "id": f"{i}_response_field_{j}",
                    "api_index": i,
                    "kind": "response_field",
                    "field_index": j,
                    "label": f"响应字段 | {method} {path} → {field.get('name', '')}",
                    "prompt": build_field_desc_prompt(api, field, "响应参数"),
                    "current": field.get("description", ""),
                    "result": "",
                })

    return tasks


# ─────────────────────────────────────────────
# 写回结果
# ─────────────────────────────────────────────

def apply_task_result(doc: dict, task: dict, result: str):
    """将单条 result 写回 doc 对应位置"""
    i = task["api_index"]
    api = doc["apis"][i]
    kind = task["kind"]

    if kind == "api_desc":
        api["description"] = result
    elif kind == "request_field":
        loc_key = task["loc_key"]
        j = task["field_index"]
        api["request"][loc_key][j]["description"] = result
    elif kind == "response_field":
        j = task["field_index"]
        api["response"]["success"]["fields"][j]["description"] = result


# ─────────────────────────────────────────────
# 主流程
# ─────────────────────────────────────────────

def cmd_export_prompts(args):
    """--export-prompts：扫描 JSON，输出 prompts.json 任务清单"""
    with open(args.input, "r", encoding="utf-8") as f:
        doc = json.load(f)

    tasks = collect_tasks(doc, force=args.force)

    if not tasks:
        print("✅ 所有字段描述已完整，无需增强。")
        return

    # 统计
    api_desc_count   = sum(1 for t in tasks if t["kind"] == "api_desc")
    req_field_count  = sum(1 for t in tasks if t["kind"] == "request_field")
    resp_field_count = sum(1 for t in tasks if t["kind"] == "response_field")
    print(f"📋 共 {len(tasks)} 个描述需要 AI 生成：")
    print(f"   接口描述: {api_desc_count} 个")
    print(f"   请求字段: {req_field_count} 个")
    print(f"   响应字段: {resp_field_count} 个")

    out_path = args.output or "prompts.json"
    os.makedirs(os.path.dirname(out_path) if os.path.dirname(out_path) else ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(tasks, f, ensure_ascii=False, indent=2)
    print(f"💾 任务清单已保存到: {out_path}")
    print()
    print("📌 下一步：由 Agent 读取该文件，逐条调用 AI 填写每条任务的 result 字段，")
    print(f"   然后执行：python3 enrich_api_doc.py --apply-results -p {out_path} -i {args.input}")


def cmd_apply_results(args):
    """--apply-results：读取 Agent 填好的 prompts.json，写回 api_doc.json"""
    with open(args.input, "r", encoding="utf-8") as f:
        doc = json.load(f)

    with open(args.prompts, "r", encoding="utf-8") as f:
        tasks = json.load(f)

    success = 0
    skip = 0
    for task in tasks:
        result = task.get("result", "").strip().strip("。，、；：").strip()
        if result:
            apply_task_result(doc, task, result)
            success += 1
        else:
            print(f"  ⚠️  跳过（result 为空）: {task.get('label', task.get('id', ''))}")
            skip += 1

    print(f"\n✅ 写回完成：成功 {success} 条，跳过 {skip} 条")

    out_path = args.input if args.inplace else (args.output or args.input)
    os.makedirs(os.path.dirname(out_path) if os.path.dirname(out_path) else ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
    print(f"💾 已保存到: {out_path}")


def cmd_dry_run(args):
    """--dry-run：仅打印任务预览，不写文件（兼容旧用法）"""
    with open(args.input, "r", encoding="utf-8") as f:
        doc = json.load(f)

    tasks = collect_tasks(doc, force=args.force)

    if not tasks:
        print("✅ 所有字段描述已完整，无需增强。")
        return

    print(f"📋 共 {len(tasks)} 个描述需要 AI 生成：\n")
    for idx, t in enumerate(tasks):
        print(f"  [{idx+1}/{len(tasks)}] {t['label']}")
        print(f"  当前值: '{t['current']}'")
        print(f"  Prompt: {t['prompt'][:120]}...")
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
