"""公众号正文图片 OCR：把内容图（表格/海报/名单）里的文字还原进正文。

设计要点：
- 只处理正文容器内的内容图：按下载字节数跳过图标、分割线、二维码等小图；
- 引擎用 RapidOCR（onnxruntime，中文模型随包内置，CPU 可跑）；未安装时
  ocr_available() 返回 False，调用方安静降级为丢弃图片的旧行为；
- 识别出的文字以 "[图片 N 识别]" 块按原始位置插回正文，保持阅读顺序。
"""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)

# 小于该字节数的图基本是图标/分割线/二维码，识别不出有效内容
_MIN_IMAGE_BYTES = 8_000
# 单图下载上限，防止异常大图拖垮内存
_MAX_IMAGE_BYTES = 20_000_000
# OCR 结果少于该字数视为无有效内容（二维码/纯装饰图）
_MIN_OCR_CHARS = 8

_ENGINE = None
_ENGINE_FAILED = False


def ocr_available() -> bool:
    """探测 OCR 引擎是否可用（缺依赖时返回 False，不抛异常）。"""
    global _ENGINE_FAILED
    if _ENGINE_FAILED:
        return False
    try:
        import rapidocr_onnxruntime  # noqa: F401

        return True
    except Exception:
        _ENGINE_FAILED = True
        return False


def _engine():
    """懒加载并复用 RapidOCR 实例（模型常驻内存，首次加载较慢）。"""
    global _ENGINE
    if _ENGINE is None:
        from rapidocr_onnxruntime import RapidOCR

        _ENGINE = RapidOCR()
    return _ENGINE


def _download(url: str, *, ua: str, timeout: float = 20.0) -> bytes:
    """下载正文图片（微信 CDN 公开链接）；超限/失败返回空。"""
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            resp = client.get(url, headers={"User-Agent": ua})
        if resp.status_code != 200:
            return b""
        data = resp.content
        if len(data) > _MAX_IMAGE_BYTES:
            return b""
        return data
    except Exception:
        return b""


def ocr_image_bytes(data: bytes) -> str:
    """对图片字节做 OCR，返回拼接后的纯文本（无有效内容返回空串）。"""
    if not data or len(data) < _MIN_IMAGE_BYTES:
        return ""
    try:
        import cv2
        import numpy as np

        arr = np.frombuffer(data, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            return ""
        result, _ = _engine()(img)
    except Exception as exc:
        logger.warning("OCR 识别失败: %s", exc)
        return ""
    if not result:
        return ""
    text = " ".join(item[1].strip() for item in result if item[1] and item[1].strip())
    return text if len(text) >= _MIN_OCR_CHARS else ""


def ocr_article_images(image_urls: list[str], *, ua: str, timeout: float = 20.0) -> dict[int, str]:
    """批量下载并识别正文图片，返回 {序号: 文本}（仅含有有效内容的图）。"""
    if not image_urls or not ocr_available():
        return {}
    out: dict[int, str] = {}
    for index, url in enumerate(image_urls):
        text = ocr_image_bytes(_download(url, ua=ua, timeout=timeout))
        if text:
            out[index] = text
    return out
