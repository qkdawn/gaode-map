from __future__ import annotations

from typing import Any, Dict, List, Tuple

from .schemas import AnalysisSnapshot, ExecutionTraceItem, PlanStep, ToolResult
from .tool_adapters.scope_tools import extract_scope_polygon
from .tools import RegisteredTool


def _has_requirement(requirement: str, snapshot: AnalysisSnapshot, artifacts: Dict[str, object]) -> bool:
    del snapshot
    if requirement in artifacts and artifacts.get(requirement):
        return True
    if requirement == "scope_polygon":
        return bool(artifacts.get("scope_polygon"))
    if requirement == "current_pois":
        return bool(artifacts.get("current_pois"))
    return False


def _inject_scope_artifacts(snapshot: AnalysisSnapshot, artifacts: Dict[str, object]) -> None:
    scope = snapshot.scope if isinstance(snapshot.scope, dict) else {}
    polygon = extract_scope_polygon(snapshot)
    isochrone_feature = scope.get("isochrone_feature") if isinstance(scope.get("isochrone_feature"), dict) else {}

    if polygon and not artifacts.get("scope_polygon"):
        artifacts["scope_polygon"] = polygon
    if scope and not artifacts.get("scope_data"):
        artifacts["scope_data"] = scope
    if isochrone_feature and not artifacts.get("isochrone_feature"):
        artifacts["isochrone_feature"] = isochrone_feature


def _inject_current_pois_artifacts(snapshot: AnalysisSnapshot, artifacts: Dict[str, object]) -> None:
    if snapshot.pois and not artifacts.get("current_pois"):
        artifacts["current_pois"] = list(snapshot.pois or [])
    if isinstance(snapshot.poi_summary, dict) and snapshot.poi_summary and not artifacts.get("current_poi_summary"):
        artifacts["current_poi_summary"] = dict(snapshot.poi_summary or {})


def _inject_available_requirements(
    *,
    requirements: List[str],
    snapshot: AnalysisSnapshot,
    artifacts: Dict[str, object],
) -> None:
    required = set(requirements or [])
    if "scope_polygon" in required and not artifacts.get("scope_polygon"):
        _inject_scope_artifacts(snapshot, artifacts)
    if "current_pois" in required and not artifacts.get("current_pois"):
        _inject_current_pois_artifacts(snapshot, artifacts)


def _validate_value(value: Any, schema: Dict[str, Any], path: str) -> List[str]:
    if not schema:
        return []
    if "anyOf" in schema:
        branches = schema.get("anyOf") or []
        if any(not _validate_value(value, branch, path) for branch in branches if isinstance(branch, dict)):
            return []
        return [f"{path} 不符合 anyOf 约束"]
    if "enum" in schema and value not in list(schema.get("enum") or []):
        return [f"{path} 必须是 {list(schema.get('enum') or [])} 之一"]

    expected_type = schema.get("type")
    if isinstance(expected_type, list):
        if any(not _validate_value(value, {**schema, "type": item}, path) for item in expected_type):
            return []
        return [f"{path} 类型不匹配"]
    if expected_type == "null":
        return [] if value is None else [f"{path} 必须为 null"]
    if expected_type == "object":
        if not isinstance(value, dict):
            return [f"{path} 必须是 object"]
        return _validate_object(value, schema, path)
    if expected_type == "array":
        if not isinstance(value, list):
            return [f"{path} 必须是 array"]
        item_schema = schema.get("items") if isinstance(schema.get("items"), dict) else {}
        errors: List[str] = []
        for index, item in enumerate(value):
            errors.extend(_validate_value(item, item_schema, f"{path}[{index}]"))
        return errors
    if expected_type == "string":
        if not isinstance(value, str):
            return [f"{path} 必须是 string"]
        return []
    if expected_type == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            return [f"{path} 必须是 integer"]
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if isinstance(minimum, (int, float)) and value < minimum:
            return [f"{path} 不能小于 {minimum}"]
        if isinstance(maximum, (int, float)) and value > maximum:
            return [f"{path} 不能大于 {maximum}"]
        return []
    if expected_type == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return [f"{path} 必须是 number"]
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if isinstance(minimum, (int, float)) and value < minimum:
            return [f"{path} 不能小于 {minimum}"]
        if isinstance(maximum, (int, float)) and value > maximum:
            return [f"{path} 不能大于 {maximum}"]
        return []
    if expected_type == "boolean":
        return [] if isinstance(value, bool) else [f"{path} 必须是 boolean"]
    return []


def _validate_object(arguments: Dict[str, Any], schema: Dict[str, Any], path: str = "arguments") -> List[str]:
    errors: List[str] = []
    properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    required = [str(item) for item in (schema.get("required") or []) if str(item).strip()]
    additional_properties = schema.get("additionalProperties", True)

    for name in required:
        if name not in arguments:
            errors.append(f"{path}.{name} 缺失")
    if additional_properties is False:
        for name in arguments.keys():
            if name not in properties:
                errors.append(f"{path}.{name} 不允许出现")
    for name, value in arguments.items():
        prop_schema = properties.get(name)
        if isinstance(prop_schema, dict):
            errors.extend(_validate_value(value, prop_schema, f"{path}.{name}"))
    return errors


def validate_tool_arguments(arguments: Dict[str, Any], schema: Dict[str, Any]) -> List[str]:
    if not isinstance(arguments, dict):
        return ["arguments 必须是 object"]
    if not isinstance(schema, dict) or not schema:
        return []
    if schema.get("type") == "object":
        return _validate_object(arguments, schema)
    return _validate_value(arguments, schema, "arguments")


def json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    return str(value)


async def execute_plan_step(
    *,
    registered_tool: RegisteredTool,
    step: PlanStep,
    snapshot: AnalysisSnapshot,
    artifacts: Dict[str, object],
    question: str,
) -> Tuple[ToolResult, ExecutionTraceItem]:
    validation_errors = validate_tool_arguments(step.arguments, registered_tool.spec.input_schema)
    if validation_errors:
        result = ToolResult(
            tool_name=registered_tool.spec.name,
            status="failed",
            warnings=list(validation_errors),
            error="invalid_arguments",
        )
    else:
        _inject_available_requirements(
            requirements=registered_tool.spec.requires,
            snapshot=snapshot,
            artifacts=artifacts,
        )
        missing = [req for req in registered_tool.spec.requires if not _has_requirement(req, snapshot, artifacts)]
        if missing:
            result = ToolResult(
                tool_name=registered_tool.spec.name,
                status="failed",
                warnings=[f"缺少前置条件: {', '.join(missing)}"],
                error="missing_requirements",
            )
        else:
            result = await registered_tool.runner(
                arguments=step.arguments,
                snapshot=snapshot,
                artifacts=artifacts,
                question=question,
            )
            result.result = json_safe(result.result)
            result.evidence = json_safe(result.evidence)
            result.warnings = [str(item) for item in (result.warnings or [])]
            result.artifacts = json_safe(result.artifacts)

    trace = ExecutionTraceItem(
        tool_name=registered_tool.spec.name,
        status=result.status,
        reason=step.reason,
        message=result.error or ("执行成功" if result.status == "success" else "执行失败"),
        cost_level=registered_tool.spec.cost_level,
        risk_level=registered_tool.spec.risk_level,
        evidence_count=len(result.evidence or []),
        warning_count=len(result.warnings or []),
    )
    return result, trace
