# -*- coding: utf-8 -*-
"""
讯飞 PDF OCR — 扫描版课件文字提取
API: https://www.xfyun.cn/doc/words/pdfOcr/API.html

流程: POST 上传 PDF → 轮询任务状态 → 下载 Markdown 结果
"""

import base64
import hashlib
import hmac
import os
import time
from pathlib import Path

import requests

# ============================================================
# CONFIG — 从 .env 读取
# ============================================================
APP_ID = os.environ.get("XF_PDFOCR_APP_ID", "5c75015a")
API_SECRET = os.environ.get("XF_PDFOCR_API_SECRET", "YTQxNzQ1MjhkNzljODMxYTQ1OTRiMWZh")

START_URL = "https://iocr.xfyun.cn/ocrzdq/v1/pdfOcr/start"
STATUS_URL = "https://iocr.xfyun.cn/ocrzdq/v1/pdfOcr/status"

# 数学公式多的课件用 markdown 格式
EXPORT_FORMAT = "markdown"

# PDF 目录
PDF_DIR = Path("./knowledge")
# 输出目录
OUTPUT_DIR = Path("./knowledge_text")
# 任务状态缓存
CACHE_FILE = Path("./pdf_ocr_cache.json")


def make_signature(app_id: str, timestamp: str, secret: str) -> str:
    """生成签名: Base64(HmacSHA1(MD5(appId + timestamp), secret))"""
    md5_hash = hashlib.md5((app_id + timestamp).encode()).hexdigest()
    hmac_sha1 = hmac.new(
        secret.encode(), md5_hash.encode(), hashlib.sha1
    ).digest()
    return base64.b64encode(hmac_sha1).decode()


def make_headers() -> dict:
    """生成带鉴权的请求头"""
    timestamp = str(int(time.time()))
    return {
        "appId": APP_ID,
        "timestamp": timestamp,
        "signature": make_signature(APP_ID, timestamp, API_SECRET),
    }


def start_task(pdf_path: Path) -> dict | None:
    """上传 PDF，返回 taskNo"""
    print(f"  📤 上传: {pdf_path.name}")
    headers = make_headers()

    with open(pdf_path, "rb") as f:
        files = {"file": (pdf_path.name, f, "application/pdf")}
        data = {"exportFormat": EXPORT_FORMAT}

        try:
            resp = requests.post(
                START_URL, headers=headers, files=files, data=data, timeout=60
            )
            result = resp.json()
        except Exception as e:
            print(f"  ❌ 上传失败: {e}")
            return None

    if not result.get("flag"):
        print(f"  ❌ API 返回错误: {result.get('desc', result)}")
        return None

    task_no = result["data"]["taskNo"]
    print(f"  ✅ 任务创建: {task_no}")
    return result["data"]


def check_status(task_no: str) -> dict | None:
    """轮询任务状态直到完成"""
    while True:
        headers = make_headers()
        try:
            resp = requests.get(
                STATUS_URL, headers=headers, params={"taskNo": task_no}, timeout=30
            )
            result = resp.json()
        except Exception as e:
            print(f"  ⚠️ 查询状态失败: {e}，重试...")
            time.sleep(5)
            continue

        if not result.get("flag"):
            print(f"  ❌ 查询失败: {result.get('desc', result)}")
            return None

        status = result["data"]["status"]
        print(f"  ⏳ 状态: {status}")

        if status in ("FINISH", "FAILED", "ANY_FAILED"):
            return result["data"]
        elif status == "STOP":
            return None

        # 5 秒轮询一次（API 限制）
        time.sleep(5)


def download_result(data: dict, output_path: Path) -> bool:
    """下载 OCR 结果文件"""
    down_url = data.get("downUrl")
    if not down_url:
        print(f"  ❌ 无下载链接")
        return False

    try:
        resp = requests.get(down_url, timeout=60)
        resp.raise_for_status()

        # API 返回的是双重 UTF-8 编码的文本，需要修复
        raw_bytes = resp.content
        try:
            text = raw_bytes.decode("utf-8").encode("latin-1").decode("utf-8")
        except (UnicodeDecodeError, UnicodeEncodeError):
            text = raw_bytes.decode("utf-8")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(text)

        print(f"  💾 保存: {output_path.name}")
        return True
    except Exception as e:
        print(f"  ❌ 下载失败: {e}")
        return False


def ocr_pdf(pdf_path: Path, output_dir: Path) -> Path | None:
    """对单个 PDF 执行 OCR，返回输出文件路径"""
    output_path = output_dir / f"{pdf_path.stem}.md"

    # 跳过已处理的
    if output_path.exists() and output_path.stat().st_size > 100:
        print(f"  ⏭️ 已存在，跳过: {output_path.name}")
        return output_path

    data = start_task(pdf_path)
    if not data:
        return None

    task_no = data["taskNo"]
    result = check_status(task_no)

    if not result or result.get("status") != "FINISH":
        print(f"  ❌ 任务未完成: {result.get('status') if result else 'unknown'}")
        return None

    if download_result(result, output_path):
        return output_path
    return None


def clean_markdown(text: str) -> str:
    """清理 markdown 文本：去除 base64 图片、多余空行"""
    import re

    # 去除 base64 嵌入图片（可能跨多行）
    text = re.sub(r"!\[img\]\(data:image/[^)]+\)", "", text)
    # 去除残留的超长 base64 行（通常在图片标记附近）
    text = re.sub(r"[A-Za-z0-9+/=]{200,}", "", text)
    # 压缩多余空行
    text = re.sub(r"\n{4,}", "\n\n\n", text)
    return text


def find_all_pdfs(pdf_dir: Path) -> list[Path]:
    """递归查找所有 PDF 文件"""
    return sorted(pdf_dir.rglob("*.pdf"))


def main():
    pdfs = find_all_pdfs(PDF_DIR)
    print(f"共发现 {len(pdfs)} 个 PDF 文件\n")

    success, failed = 0, 0
    for i, pdf in enumerate(pdfs, 1):
        rel_path = pdf.relative_to(PDF_DIR)
        print(f"[{i}/{len(pdfs)}] {rel_path}")
        result = ocr_pdf(pdf, OUTPUT_DIR / rel_path.parent)
        if result:
            success += 1
        else:
            failed += 1
        print()

    print(f"完成: 成功 {success}, 失败 {failed}")


if __name__ == "__main__":
    main()
