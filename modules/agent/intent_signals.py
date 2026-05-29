from __future__ import annotations


def mentions_summary(text: str) -> bool:
    return any(token in text for token in ("总结", "概括", "商业特征", "分析这个区域"))


def mentions_next_analysis(text: str) -> bool:
    return any(token in text for token in ("下一步", "继续", "还可以", "做什么分析", "还能分析"))


def mentions_road(text: str) -> bool:
    return any(token in text for token in ("路网", "可达性", "通达", "交通"))


def mentions_supply(text: str) -> bool:
    return any(token in text for token in ("补充餐饮", "补充零售", "餐饮", "零售", "购物", "咖啡", "业态", "选址", "补位"))


def mentions_population(text: str) -> bool:
    return any(token in text for token in ("人口", "人群", "居民", "常住", "性别", "年龄"))


def mentions_nightlight(text: str) -> bool:
    return any(token in text for token in ("夜光", "夜间", "夜里", "亮灯", "灯光", "夜生活", "活力"))
