#!/usr/bin/env python3
"""
Git API Gateway Doc - Django/DRF Diff Parser
解析 git diff 文件，识别 Django/DRF 的 API 变更，生成标准化 JSON 接口文档
"""

import re
import json
import sys
import argparse
import os
from datetime import datetime
from copy import deepcopy


# ─────────────────────────────────────────────
# 常量
# ─────────────────────────────────────────────

# HTTP 方法与 DRF/Django 装饰器的映射
DRF_METHOD_MAP = {
    # @api_view 装饰器
    r"@api_view\(\['GET'\]\)": ["GET"],
    r"@api_view\(\['POST'\]\)": ["POST"],
    r"@api_view\(\['PUT'\]\)": ["PUT"],
    r"@api_view\(\['PATCH'\]\)": ["PATCH"],
    r"@api_view\(\['DELETE'\]\)": ["DELETE"],
    r"@api_view\(\[([^\]]+)\]\)": None,  # 多方法，动态解析
    # ViewSet @action 装饰器
    r"@action\(.*?methods=\[([^\]]+)\]": None,
    # 类视图方法
    "def get(": ["GET"],
    "def post(": ["POST"],
    "def put(": ["PUT"],
    "def patch(": ["PATCH"],
    "def delete(": ["DELETE"],
    "def list(": ["GET"],
    "def create(": ["POST"],
    "def retrieve(": ["GET"],
    "def update(": ["PUT"],
    "def partial_update(": ["PATCH"],
    "def destroy(": ["DELETE"],
}

# urls.py 中 path/re_path/url 的 HTTP 方法推断依据 view 函数名
URL_METHOD_HINTS = {
    "list": "GET",
    "create": "POST",
    "retrieve": "GET",
    "update": "PUT",
    "partial_update": "PATCH",
    "destroy": "DELETE",
    "detail": "GET",
}

# 变更类型标识注释
CHANGE_TAGS = {
    "new": "NEW",
    "changed": "CHANGED",
    "modified": "MODIFIED",
}

# 常见 Django 内置字段类型 → JSON Schema 类型映射
FIELD_TYPE_MAP = {
    "IntegerField": "integer",
    "FloatField": "number",
    "DecimalField": "number",
    "CharField": "string",
    "TextField": "string",
    "EmailField": "string",
    "URLField": "string",
    "BooleanField": "boolean",
    "DateField": "string",
    "DateTimeField": "string",
    "JSONField": "object",
    "FileField": "string",
    "ImageField": "string",
    "ForeignKey": "integer",
    "OneToOneField": "integer",
    "ManyToManyField": "array",
    # DRF Serializer fields
    "SerializerMethodField": "any",
    "PrimaryKeyRelatedField": "integer",
    "StringRelatedField": "string",
    "SlugRelatedField": "string",
    "HyperlinkedRelatedField": "string",
    "ListField": "array",
    "DictField": "object",
}

CHANGE_TYPE_NEW = "新增"
CHANGE_TYPE_MODIFIED = "变更"


# ─────────────────────────────────────────────
# 工具函数
# ─────────────────────────────────────────────

def normalize_url_path(raw_path: str) -> str:
    """
    将 Django urls.py 中的路径转化为标准 REST 格式
    例如: 'users/<int:pk>/profile/' → '/users/{pk}/profile'
    """
    # 去引号
    raw_path = raw_path.strip("'\"")
    # 转换 <int:pk> 等参数
    path = re.sub(r"<(?:\w+:)?(\w+)>", r"{\1}", raw_path)
    # 确保以 / 开头
    if not path.startswith("/"):
        path = "/" + path
    # 去掉结尾 /（网关习惯）
    path = path.rstrip("/")
    return path if path else "/"


def extract_methods_from_api_view(decorator_line: str) -> list:
    """从 @api_view(['GET', 'POST']) 提取 HTTP 方法列表"""
    m = re.search(r"@api_view\(\[([^\]]+)\]\)", decorator_line)
    if not m:
        return []
    raw = m.group(1)
    methods = [s.strip().strip("'\"") for s in raw.split(",")]
    return [m.upper() for m in methods if m]


def extract_methods_from_action(decorator_line: str) -> list:
    """从 @action(detail=True, methods=['post']) 提取方法"""
    m = re.search(r"methods=\[([^\]]+)\]", decorator_line)
    if not m:
        return ["GET"]
    raw = m.group(1)
    methods = [s.strip().strip("'\"") for s in raw.split(",")]
    return [m.upper() for m in methods if m]


def infer_method_from_view_func(func_name: str) -> list:
    """根据 view 函数名推断 HTTP 方法"""
    for hint_key, method in URL_METHOD_HINTS.items():
        if hint_key in func_name.lower():
            return [method]
    return ["GET"]


def extract_serializer_fields(diff_lines: list, serializer_name: str) -> list:
    """
    在 diff 中找到指定 Serializer 的字段定义（新增行）
    返回字段列表 [{name, type, required, description}]
    """
    fields = []
    in_serializer = False
    indent_base = None

    for line in diff_lines:
        # 只处理新增行（+ 开头）和上下文行
        raw = line[1:] if line.startswith(("+", " ", "-")) else line
        stripped = raw.strip()

        # 检测是否进入目标 Serializer 类
        if re.match(rf"class\s+{re.escape(serializer_name)}\s*\(", stripped):
            in_serializer = True
            indent_base = len(raw) - len(raw.lstrip())
            continue

        if in_serializer:
            current_indent = len(raw) - len(raw.lstrip()) if raw.strip() else 999
            # 遇到同级或更浅的类定义，退出
            if stripped.startswith("class ") and current_indent <= indent_base:
                break

            # 只取新增行（views/serializers）中的字段
            if not line.startswith("+"):
                continue

            # 匹配 DRF 字段: field_name = SomeField(...)
            m = re.match(r"\s+(\w+)\s*=\s*(\w+)\(", stripped)
            if m:
                fname = m.group(1)
                ftype_raw = m.group(2)
                if fname in ("Meta", "class") or ftype_raw in ("serializers",):
                    continue
                json_type = FIELD_TYPE_MAP.get(ftype_raw, "string")
                required = "null=True" not in raw and "blank=True" not in raw
                fields.append({
                    "name": fname,
                    "type": json_type,
                    "required": required,
                    "description": "",
                })

    return fields


def build_url_prefix(file_path: str) -> str:
    """
    从文件路径推断 URL 前缀（基于 app 名称）
    例如: inventory_management/urls.py → /inventory_management
    """
    parts = file_path.replace("\\", "/").split("/")
    if len(parts) >= 2 and parts[-1] in ("urls.py", "views.py"):
        app_name = parts[-2]
        return f"/{app_name}"
    return ""


# ─────────────────────────────────────────────
# 核心解析器
# ─────────────────────────────────────────────

class DjangoDiffParser:
    """
    解析 Django/DRF git diff，提取 API 变更信息
    """

    def __init__(self, diff_text: str):
        self.diff_text = diff_text
        self.files = self._split_by_file(diff_text)
        self.apis = []

    # ── 拆分文件块 ──────────────────────────────
    def _split_by_file(self, text: str) -> list:
        """将 diff 按文件拆分为 [{path, lines, change_type}]"""
        pattern = re.compile(r"^diff --git a/.+ b/(.+)$", re.MULTILINE)
        matches = list(pattern.finditer(text))
        result = []
        for i, m in enumerate(matches):
            start = m.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            block = text[start:end]
            file_path = m.group(1).strip()
            lines = block.split("\n")
            # 判断新文件还是修改
            is_new_file = any("new file mode" in l for l in lines[:5])
            result.append({
                "path": file_path,
                "lines": lines,
                "is_new_file": is_new_file,
            })
        return result

    # ── 主入口 ──────────────────────────────────
    def parse(self) -> list:
        for file_info in self.files:
            path = file_info["path"]
            lines = file_info["lines"]
            is_new = file_info["is_new_file"]

            if path.endswith("urls.py"):
                self._parse_urls_file(path, lines, is_new)
            elif path.endswith("views.py"):
                self._parse_views_file(path, lines, is_new)
            # serializers.py 作为辅助，暂时不单独解析路由

        return self.apis

    # ── 解析 urls.py ────────────────────────────
    def _parse_urls_file(self, path: str, lines: list, is_new_file: bool):
        url_prefix = build_url_prefix(path)

        # 只处理新增行
        added_lines = [l[1:] for l in lines if l.startswith("+") and not l.startswith("+++")]

        for line in added_lines:
            stripped = line.strip()

            # 匹配 path('some/path/', view_func, name='xxx')
            m = re.match(
                r"path\(['\"]([^'\"]*)['\"],\s*(?:views\.)?(\w+)(?:\.as_view\(\))?,?\s*(?:name=['\"]([^'\"]*)['\"])?",
                stripped,
            )
            if not m:
                # 匹配 re_path 或 url()
                m = re.match(
                    r"(?:re_path|url)\(['\"]([^'\"]*)['\"],\s*(?:views\.)?(\w+)",
                    stripped,
                )
            if not m:
                continue

            raw_path = m.group(1)
            view_func = m.group(2)
            route_name = m.group(3) if m.lastindex >= 3 else view_func

            full_path = url_prefix + normalize_url_path(raw_path)
            methods = infer_method_from_view_func(view_func)
            change_type = CHANGE_TYPE_NEW if is_new_file else CHANGE_TYPE_NEW

            # 从注释提取描述
            desc = self._extract_inline_comment(line) or f"{view_func} 接口"

            for method in methods:
                api = self._make_api_entry(
                    method=method,
                    path=full_path,
                    description=desc,
                    func_name=view_func,
                    route_name=route_name,
                    change_type=change_type,
                    source_file=path,
                )
                self.apis.append(api)

    # ── 解析 views.py ───────────────────────────
    def _parse_views_file(self, path: str, lines: list, is_new_file: bool):
        url_prefix = build_url_prefix(path)
        pending_methods = []   # 当前装饰器收集到的方法
        pending_action_path = None  # @action 中的 url_path
        pending_change_type = CHANGE_TYPE_NEW

        i = 0
        while i < len(lines):
            line = lines[i]
            raw = line[1:] if line.startswith(("+", " ", "-")) else line
            stripped = raw.strip()

            # 跳过删除行
            if line.startswith("-") and not line.startswith("---"):
                i += 1
                continue

            is_added = line.startswith("+") and not line.startswith("+++")
            is_context = line.startswith(" ")

            # ── 检测 @api_view ──────────────────
            if "@api_view(" in stripped:
                pending_methods = extract_methods_from_api_view(stripped)
                if "# NEW" in raw.upper() or "# 新增" in raw:
                    pending_change_type = CHANGE_TYPE_NEW
                else:
                    pending_change_type = CHANGE_TYPE_MODIFIED if not is_new_file else CHANGE_TYPE_NEW

            # ── 检测 @action ────────────────────
            elif "@action(" in stripped:
                pending_methods = extract_methods_from_action(stripped)
                url_m = re.search(r"url_path=['\"]([^'\"]+)['\"]", stripped)
                pending_action_path = url_m.group(1) if url_m else None
                pending_change_type = CHANGE_TYPE_NEW if (is_added or is_new_file) else CHANGE_TYPE_MODIFIED

            # ── 检测函数/方法定义 def xxx(request ...) ─
            elif stripped.startswith("def ") and ("request" in stripped or "self" in stripped):
                func_m = re.match(r"def\s+(\w+)\s*\(", stripped)
                if not func_m:
                    i += 1
                    continue

                func_name = func_m.group(1)
                # 跳过 helper / private 函数
                if func_name.startswith("_") or func_name in (
                        "calculate_supplier_score", "get_performance_grade",
                ):
                    pending_methods = []
                    i += 1
                    continue

                # 收集函数体（新增行）以提取 docstring / 注释
                body_lines = self._collect_function_body(lines, i)

                # 提取描述
                desc = self._extract_func_description(body_lines, func_name)

                # 提取 URL 路径
                extracted_path = self._extract_path_from_body(body_lines, url_prefix, func_name, pending_action_path)

                # 确定方法
                if not pending_methods:
                    pending_methods = self._infer_methods_from_func(func_name, body_lines)

                # 变更类型
                if not is_added and not is_new_file:
                    change_type = CHANGE_TYPE_MODIFIED
                else:
                    change_type = pending_change_type

                # 提取请求/响应参数
                request_params = self._extract_request_params(body_lines)
                response_params = self._extract_response_params(body_lines)

                for method in pending_methods:
                    api = self._make_api_entry(
                        method=method,
                        path=extracted_path,
                        description=desc,
                        func_name=func_name,
                        route_name=func_name,
                        change_type=change_type,
                        source_file=path,
                        request_params=request_params,
                        response_params=response_params,
                    )
                    self.apis.append(api)

                # 重置 pending
                pending_methods = []
                pending_action_path = None

            i += 1

    # ── 辅助：收集函数体行 ───────────────────────
    def _collect_function_body(self, lines: list, def_index: int, max_lines: int = 60) -> list:
        """收集 def 之后的函数体（含 + 和上下文行）"""
        body = []
        for j in range(def_index + 1, min(def_index + max_lines, len(lines))):
            l = lines[j]
            raw = l[1:] if l.startswith(("+", " ", "-")) else l
            stripped = raw.strip()
            # 遇到同级 def / class 停止
            if stripped.startswith(("def ", "class ")) and not raw.startswith("    "):
                break
            body.append(l)
        return body

    # ── 辅助：提取函数描述 ──────────────────────
    def _extract_func_description(self, body_lines: list, func_name: str) -> str:
        """优先从注释/docstring提取描述，否则使用函数名"""
        for line in body_lines[:8]:
            raw = line[1:] if line.startswith(("+", " ")) else line
            stripped = raw.strip()
            # 单行注释
            if stripped.startswith("#"):
                comment = stripped.lstrip("# ").strip()
                if comment and not comment.startswith("type:") and len(comment) > 2:
                    # 过滤 NEW/CHANGED 标签
                    comment = re.sub(r"^(NEW|CHANGED|MODIFIED)[:\s]*", "", comment, flags=re.IGNORECASE).strip()
                    if comment:
                        return comment
            # docstring
            if stripped.startswith(('"""', "'''")):
                doc = stripped.strip('"""').strip("'''").strip()
                if doc:
                    return doc
        # fallback：转换函数名为可读描述
        return func_name.replace("_", " ").title() + " 接口"

    # ── 辅助：从函数体推断路径 ──────────────────
    def _extract_path_from_body(
            self, body_lines: list, url_prefix: str, func_name: str, action_path: str = None
    ) -> str:
        """尽量从注释/Response 中推断路径，否则用函数名"""
        if action_path:
            return url_prefix + "/" + action_path.strip("/")
        # 检查注释中有没有明显路径
        for line in body_lines[:10]:
            raw = line[1:] if line.startswith(("+", " ")) else line
            m = re.search(r"['\"]/([\w/<>:{}]+)['\"]", raw)
            if m:
                p = m.group(0).strip("'\"")
                if "/" in p and len(p) > 2:
                    return normalize_url_path(p)
        # fallback
        slug = func_name.replace("_", "-")
        return f"{url_prefix}/{slug}"

    # ── 辅助：从函数体推断 HTTP 方法 ────────────
    def _infer_methods_from_func(self, func_name: str, body_lines: list) -> list:
        """根据函数名和函数体推断方法"""
        # 先试函数名
        for key, method in URL_METHOD_HINTS.items():
            if key in func_name.lower():
                return [method]
        # 扫函数体
        for line in body_lines:
            raw = line[1:] if line.startswith(("+", " ")) else line
            stripped = raw.strip()
            for prefix in ("def get(", "def post(", "def put(", "def patch(", "def delete("):
                if stripped.startswith(prefix):
                    return [prefix[4:7].upper()]
        return ["GET"]

    # ── 辅助：提取请求参数 ──────────────────────
    def _extract_request_params(self, body_lines: list) -> list:
        """
        从函数体新增行中提取请求参数
        支持:
          - request.data.get('key', ...)
          - request.GET.get('key', ...)
          - request.query_params.get('key', ...)
          - <int:pk> / <str:slug> 路径参数
          - Serializer(data=request.data) → 展开 Serializer 字段（如可识别）
        """
        params = []
        seen = set()

        for line in body_lines:
            if not line.startswith(("+", " ")):
                continue
            raw = line[1:] if line.startswith(("+", " ")) else line

            # request.data.get / request.GET.get / request.query_params.get
            for pattern, location in [
                (r"request\.data\.get\(['\"](\w+)['\"]", "body"),
                (r"request\.GET\.get\(['\"](\w+)['\"]", "query"),
                (r"request\.query_params\.get\(['\"](\w+)['\"]", "query"),
                (r"request\.POST\.get\(['\"](\w+)['\"]", "body"),
            ]:
                for m in re.finditer(pattern, raw):
                    pname = m.group(1)
                    if pname not in seen:
                        seen.add(pname)
                        # 尝试推断是否有默认值（暗示非必须）
                        # request.data.get('key', default)
                        dm = re.search(
                            rf"['\"]?{re.escape(pname)}['\"]?,\s*([^)]+)\)", raw
                        )
                        has_default = dm is not None and dm.group(1).strip() not in ("", "None")
                        params.append({
                            "name": pname,
                            "location": location,
                            "type": "string",
                            "required": not has_default,
                            "description": "",
                        })

            # 路径参数 <int:pk> 等（来自 url pattern）
            for m in re.finditer(r"\{(\w+)\}", raw):
                pname = m.group(1)
                if pname not in seen:
                    seen.add(pname)
                    params.append({
                        "name": pname,
                        "location": "path",
                        "type": "integer" if pname in ("pk", "id") else "string",
                        "required": True,
                        "description": "",
                    })

        return params

    # ── 辅助：提取响应参数 ──────────────────────
    def _extract_response_params(self, body_lines: list) -> list:
        """
        从 Response({...}) 中提取响应字段
        支持:
          - Response({'key': value, ...})
          - Response(serializer.data)
          - Response({'code': 200, 'data': ...})
        """
        params = []
        seen = set()

        # 合并函数体为字符串方便多行匹配
        body_text = "\n".join(
            (l[1:] if l.startswith(("+", " ")) else l)
            for l in body_lines
        )

        # 尝试提取 Response({...}) 内容
        for m in re.finditer(r"Response\s*\(\s*\{([^}]{1,500})\}", body_text, re.DOTALL):
            block = m.group(1)
            for km in re.finditer(r"['\"](\w+)['\"]:\s*([^,}\n]+)", block):
                key = km.group(1)
                val = km.group(2).strip()
                if key in seen:
                    continue
                seen.add(key)
                # 推断类型
                rtype = "string"
                if re.match(r"^\d+$", val):
                    rtype = "integer"
                elif val.lower() in ("true", "false"):
                    rtype = "boolean"
                elif "serializer" in val.lower() or ".data" in val:
                    rtype = "object"
                elif val.startswith("["):
                    rtype = "array"
                elif val.startswith("{"):
                    rtype = "object"
                elif "Map.of" in val or "{" in val:
                    rtype = "object"
                params.append({
                    "name": key,
                    "type": rtype,
                    "description": "",
                })

        # 如果 Response(serializer.data)，打上标记
        if not params and re.search(r"Response\s*\(\s*serializer\.data\s*\)", body_text):
            params.append({
                "name": "data",
                "type": "object",
                "description": "序列化后的模型数据",
            })

        return params

    # ── 辅助：提取行内注释 ──────────────────────
    def _extract_inline_comment(self, line: str) -> str:
        m = re.search(r"#\s*(.+)$", line)
        if m:
            return m.group(1).strip()
        return ""

    # ── 构造 API 条目 ───────────────────────────
    def _make_api_entry(
            self,
            method: str,
            path: str,
            description: str,
            func_name: str,
            route_name: str,
            change_type: str,
            source_file: str,
            request_params: list = None,
            response_params: list = None,
    ) -> dict:
        return {
            "method": method.upper(),
            "path": path,
            "description": description,
            "change_type": change_type,
            "func_name": func_name,
            "route_name": route_name,
            "source_file": source_file,
            "request_params": request_params or [],
            "response_params": response_params or [],
            "auth_required": True,  # Django 默认需要认证，可后续覆盖
        }


# ─────────────────────────────────────────────
# JSON 生成器
# ─────────────────────────────────────────────

def build_api_json(apis: list, diff_file: str) -> dict:
    """
    将解析出的 API 列表构建为标准 JSON 文档结构
    """
    result = {
        "meta": {
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "source_diff": os.path.basename(diff_file),
            "framework": "Django/DRF",
            "total_changes": len(apis),
            "new_apis": sum(1 for a in apis if a["change_type"] == CHANGE_TYPE_NEW),
            "modified_apis": sum(1 for a in apis if a["change_type"] == CHANGE_TYPE_MODIFIED),
        },
        "apis": [],
    }

    for api in apis:
        entry = {
            "method": api["method"],
            "path": api["path"],
            "description": api["description"],
            "change_type": api["change_type"],
            "route_name": api["route_name"],
            "source_file": api["source_file"],
            "auth_required": api.get("auth_required", True),
            "request": {
                "path_params": [
                    p for p in api["request_params"] if p.get("location") == "path"
                ],
                "query_params": [
                    p for p in api["request_params"] if p.get("location") == "query"
                ],
                "body_params": [
                    p for p in api["request_params"] if p.get("location") == "body"
                ],
            },
            "response": {
                "success": {
                    "status_code": 201 if api["method"] == "POST" else 200,
                    "fields": api["response_params"],
                },
                "error_codes": _default_error_codes(api["method"]),
            },
        }
        result["apis"].append(entry)

    return result


def _default_error_codes(method: str) -> list:
    """根据 HTTP 方法返回常见错误码"""
    base = [
        {"code": 400, "description": "请求参数错误"},
        {"code": 401, "description": "未认证"},
        {"code": 403, "description": "权限不足"},
        {"code": 500, "description": "服务器内部错误"},
    ]
    if method in ("GET", "PUT", "PATCH", "DELETE"):
        base.insert(1, {"code": 404, "description": "资源不存在"})
    return base


# ─────────────────────────────────────────────
# 主函数
# ─────────────────────────────────────────────

def parse_diff_to_json(diff_file: str, output_file: str = None) -> dict:
    """
    主入口：读取 diff 文件 → 解析 → 生成 JSON

    Args:
        diff_file: git diff 文件路径
        output_file: 输出 JSON 文件路径（不传则不写文件）

    Returns:
        dict: API 文档 JSON 结构
    """
    with open(diff_file, "r", encoding="utf-8") as f:
        diff_text = f.read()

    parser = DjangoDiffParser(diff_text)
    apis = parser.parse()

    doc = build_api_json(apis, diff_file)

    if output_file:
        os.makedirs(os.path.dirname(output_file) if os.path.dirname(output_file) else ".", exist_ok=True)
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=2)
        print(f"✅ API 文档已生成: {output_file}")
        print(f"   新增接口: {doc['meta']['new_apis']} 个")
        print(f"   变更接口: {doc['meta']['modified_apis']} 个")
        print(f"   合计:     {doc['meta']['total_changes']} 个")

    return doc


def main():
    parser = argparse.ArgumentParser(
        description="Django/DRF Git Diff → API JSON 文档生成器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 解析 diff 文件并输出到 JSON
  python parse_git_diff.py -d changes.diff -o api_doc.json

  # 实时从 git 生成
  git diff HEAD~1 | python parse_git_diff.py -d /dev/stdin -o api_doc.json

  # 打印到控制台
  python parse_git_diff.py -d changes.diff
        """,
    )
    parser.add_argument("--diff-file", "-d", required=True, help="git diff 文件路径")
    parser.add_argument("--output", "-o", help="输出 JSON 文件路径（可选，默认打印到控制台）")

    args = parser.parse_args()

    if not os.path.exists(args.diff_file) and args.diff_file != "/dev/stdin":
        print(f"❌ 文件不存在: {args.diff_file}")
        sys.exit(1)

    doc = parse_diff_to_json(args.diff_file, args.output)

    if not args.output:
        print(json.dumps(doc, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
