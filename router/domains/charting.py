from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from modules.charting import build_svg, delete_chart_file, get_chart_path, pick_numeric_table, save_svg

router = APIRouter()


@router.post("/bar_chart")
async def bar_chart(request: Request):
    text = (await request.body()).decode("utf-8")
    x_title, labels, series, values = pick_numeric_table(text)
    svg_content = build_svg(labels, series, values, x_title=x_title)

    chart_id, filename = save_svg(svg_content)
    base_url = str(request.base_url).rstrip("/")
    return {
        "chart_id": chart_id,
        "url": f"{base_url}/download/{filename}",
        "series": series,
        "labels": labels,
        "x_title": x_title,
        "chart": {
            "labels": labels,
            "series": series,
            "values": values,
        },
    }


@router.get("/download/{filename}")
def download_chart(filename: str):
    filepath = get_chart_path(filename)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="Chart not found.")
    return FileResponse(
        filepath,
        media_type="image/svg+xml",
        filename=os.path.basename(filepath),
    )

