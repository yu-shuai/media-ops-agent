"""
图片生成服务模块
使用火山引擎方舟 Ark 生图模型（Seedream）生成小红书风格配图
"""
import os
import asyncio
import uuid
import random
import httpx
from pathlib import Path
from typing import List, Optional
from datetime import datetime
from dotenv import load_dotenv

from volcenginesdkarkruntime import AsyncArk

load_dotenv()


class ImageService:
    """图片生成服务类"""

    XHS_STYLE_PROMPT = """请根据以下内容生成一张小红书风格的爆款配图：

【内容主题】
{content}

【图片要求】
- 风格：小红书流行的高质感、精致感、氛围感风格
- 色调：明亮温暖、柔和治愈、或高级感色调
- 构图：简洁大气、留白得当、视觉重点突出
- 比例：3:4 竖版构图（适合手机浏览）

【风格参考】
- 美食：诱人的食物特写，暖色调打光
- 穿搭：时尚感穿搭展示，简约背景
- 家居：温馨舒适的生活场景，ins风或日系风
- 知识/干货：清新简约的图文排版，扁平插画
- 其他：根据内容匹配最适合的小红书流行风格

请生成一张高质量、有吸引力的图片。"""

    FALLBACK_PROMPTS = [
        "小红书风格，明亮温暖的生活场景，咖啡和书本，柔和自然光，3:4竖版构图",
        "小红书风格，创意工作台，文具和绿植，ins风格，3:4竖版构图",
        "小红书风格，清新简约的扁平插画，渐变色背景，3:4竖版构图",
    ]

    def __init__(self):
        # 生图 API Key：优先 ARK_API_KEY，未配置时回退 LLM_API_KEY（同属方舟账号）
        self.api_key = (os.getenv("ARK_API_KEY", "").strip()
                        or os.getenv("LLM_API_KEY", "").strip())
        self.base_url = os.getenv("ARK_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3").rstrip("/")
        self.model = os.getenv("IMAGE_MODEL", "ep-20260923014947-j8fcl")
        self.size = os.getenv("IMAGE_SIZE", "2K")

        self.image_dir = Path("static/images/generated")
        self.image_dir.mkdir(parents=True, exist_ok=True)

        if not self.api_key:
            raise ValueError("ARK_API_KEY 未配置（也未回退到 LLM_API_KEY）")

    def _save_image(self, image_bytes: bytes, prefix: str = "xhs") -> str:
        """保存图片到本地"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        unique_id = str(uuid.uuid4())[:8]
        filename = f"{prefix}_{timestamp}_{unique_id}.png"

        file_path = self.image_dir / filename
        with open(file_path, "wb") as f:
            f.write(image_bytes)

        return f"/static/images/generated/{filename}"

    async def _call_ark_api(self, prompt: str) -> Optional[str]:
        """调用方舟生图 API，下载图片并保存到本地，返回静态访问路径"""
        try:
            async with AsyncArk(base_url=self.base_url, api_key=self.api_key) as client:
                response = await client.images.generate(
                    model=self.model,
                    prompt=prompt,
                    sequential_image_generation="disabled",
                    response_format="url",
                    size=self.size,
                    stream=False,
                    watermark=True,
                )
                image_url = response.data[0].url

            # 返回的 URL 有时效限制，下载保存到本地
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.get(image_url)
                resp.raise_for_status()
                return self._save_image(resp.content)

        except Exception as e:
            print(f"[ImageService] 生图请求异常: {e}")
            return None

    async def generate_single_image(
        self,
        prompt: str,
        optimize_for_xhs: bool = True,
    ) -> Optional[str]:
        """生成单张图片（失败时使用备用提示词重试一次）"""
        current_prompt = self.XHS_STYLE_PROMPT.format(content=prompt) if optimize_for_xhs else prompt

        print(f"[ImageService] 生成图片: {prompt[:50]}...")

        # 首次尝试
        image_path = await self._call_ark_api(current_prompt)
        if image_path:
            print(f"[ImageService] 图片生成成功: {image_path}")
            return image_path

        # 使用备用提示词重试
        print(f"[ImageService] 首次失败，使用备用提示词重试...")
        await asyncio.sleep(1)

        fallback_prompt = random.choice(self.FALLBACK_PROMPTS)
        image_path = await self._call_ark_api(fallback_prompt)
        if image_path:
            print(f"[ImageService] 备用提示词成功: {image_path}")
            return image_path

        print(f"[ImageService] 图片生成失败，跳过")
        return None

    async def generate_images(
        self,
        visual_points: List[str],
        optimize_for_xhs: bool = True,
    ) -> List[str]:
        """批量生成配图（并行）"""
        if not visual_points:
            return []

        tasks = [
            self.generate_single_image(prompt=point, optimize_for_xhs=optimize_for_xhs)
            for point in visual_points
        ]
        results = await asyncio.gather(*tasks)

        image_paths = [path for path in results if path is not None]
        print(f"[ImageService] 成功生成 {len(image_paths)}/{len(visual_points)} 张图片")
        return image_paths


# 单例实例
image_service = ImageService()
