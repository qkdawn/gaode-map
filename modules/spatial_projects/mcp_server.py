"""MCP entry point for history-backed spatial projects.

Run with ``python -m modules.spatial_projects.mcp_server``.  The default
stdio transport is suitable for Codex; use ``--transport streamable-http``
when deploying the same server for a remote MCP client.
"""

import argparse
import inspect
import json
import sys
from typing import Any

from modules.spatial_projects.service import SpatialProjectService

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:  # pragma: no cover - exercised in dependency-light local environments
    FastMCP = None


class _StdioMcpFallback:
    """Small MCP stdio implementation used only when the official SDK is unavailable.

    It covers the MCP surface needed by local Codex: initialize, tools/list,
    tools/call, and ping. Streamable HTTP always requires the official SDK.
    """

    def __init__(self, name: str):
        self.name = name
        self._tools: dict[str, Any] = {}

    def tool(self):
        def register(callback):
            self._tools[callback.__name__] = callback
            return callback

        return register

    @staticmethod
    def _schema(callback: Any) -> dict[str, Any]:
        properties: dict[str, Any] = {}
        required = []
        for parameter in inspect.signature(callback).parameters.values():
            annotation = parameter.annotation
            type_name = "integer" if annotation is int else "boolean" if annotation is bool else "string"
            properties[parameter.name] = {"type": type_name}
            if parameter.default is inspect.Parameter.empty:
                required.append(parameter.name)
        return {"type": "object", "properties": properties, "required": required, "additionalProperties": False}

    def _tool_list(self) -> dict[str, Any]:
        return {
            "tools": [
                {
                    "name": name,
                    "description": inspect.getdoc(callback) or "",
                    "inputSchema": self._schema(callback),
                }
                for name, callback in self._tools.items()
            ]
        }

    @staticmethod
    def _write(message: dict[str, Any]) -> None:
        sys.stdout.write(json.dumps(message, ensure_ascii=True, default=str) + "\n")
        sys.stdout.flush()

    def _handle(self, request: dict[str, Any]) -> dict[str, Any] | None:
        request_id = request.get("id")
        method = request.get("method")
        if method == "notifications/initialized" or request_id is None:
            return None
        if method == "initialize":
            return {"jsonrpc": "2.0", "id": request_id, "result": {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}, "serverInfo": {"name": self.name, "version": "0.1.0"}}}
        if method == "ping":
            return {"jsonrpc": "2.0", "id": request_id, "result": {}}
        if method == "tools/list":
            return {"jsonrpc": "2.0", "id": request_id, "result": self._tool_list()}
        if method == "tools/call":
            params = request.get("params") if isinstance(request.get("params"), dict) else {}
            name = str(params.get("name") or "")
            callback = self._tools.get(name)
            if callback is None:
                return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32602, "message": "unknown_tool"}}
            arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
            try:
                result = callback(**arguments)
                content = {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, default=str)}]}
                return {"jsonrpc": "2.0", "id": request_id, "result": content}
            except Exception as exc:
                return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32603, "message": str(exc)}}
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": "method_not_found"}}

    def run(self, *, transport: str) -> None:
        if transport != "stdio":
            raise RuntimeError("Streamable HTTP requires the official 'mcp' package. Install project dependencies before using this transport.")
        for raw_line in sys.stdin:
            try:
                request = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            if not isinstance(request, dict):
                continue
            response = self._handle(request)
            if response is not None:
                self._write(response)


service = SpatialProjectService()
mcp = FastMCP("Spatial Project") if FastMCP is not None else _StdioMcpFallback("spatial-project")


def _call(callback, **kwargs: Any) -> dict[str, Any]:
    try:
        return callback(**kwargs)
    except LookupError as exc:
        return {"status": "not_found", "error": str(exc)}
    except ValueError as exc:
        return {"status": "invalid_request", "error": str(exc)}


@mcp.tool()
def list_history_projects(limit: int = 100) -> list[dict[str, Any]]:
    """List history-backed spatial projects by identity only; read one for documents and datasets."""
    return _call(service.list_history_projects, limit=limit)


@mcp.tool()
def read_history_project(history_id: str) -> dict[str, Any]:
    """Read one history-backed spatial project, its documents, datasets, scope, and version status."""
    return _call(service.read_history_project, history_id=history_id)


@mcp.tool()
def list_history_project_documents(history_id: str) -> dict[str, Any]:
    """List project documents linked to one analysis history, including their roles and parse status."""
    return _call(service.list_history_project_documents, history_id=history_id)


@mcp.tool()
def list_history_project_datasets(history_id: str) -> dict[str, Any]:
    """List datasets available for one analysis history, including years, counts, and warnings."""
    return _call(service.list_history_project_datasets, history_id=history_id)


@mcp.tool()
def query_history_project_dataset(history_id: str, source_id: str, filters: dict[str, Any] | None = None, sort: dict[str, Any] | None = None, limit: int = 20, offset: int = 0, year: int | None = None) -> dict[str, Any]:
    """Read a bounded page from a history-backed spatial dataset."""
    return _call(service.query_history_project_dataset, history_id=history_id, source_id=source_id, filters=filters, sort=sort, limit=limit, offset=offset, year=year)


@mcp.tool()
def aggregate_history_project_dataset(history_id: str, source_id: str, group_by: str = "", metrics: list[dict[str, Any]] | None = None, filters: dict[str, Any] | None = None, top_k: int = 20, year: int | None = None) -> dict[str, Any]:
    """Aggregate a history-backed dataset without loading every record into the Agent context."""
    return _call(service.aggregate_history_project_dataset, history_id=history_id, source_id=source_id, group_by=group_by, metrics=metrics, filters=filters, top_k=top_k, year=year)


@mcp.tool()
def read_history_project_dataset_record(history_id: str, source_id: str, record_id: str, year: int | None = None) -> dict[str, Any]:
    """Read one spatial dataset record from a history-backed project."""
    return _call(service.read_history_project_dataset_record, history_id=history_id, source_id=source_id, record_id=record_id, year=year)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--transport", choices=("stdio", "streamable-http"), default="stdio")
    args = parser.parse_args()
    mcp.run(transport=args.transport)


if __name__ == "__main__":
    main()
