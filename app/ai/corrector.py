"""Optimized AI Corrector for N100 CPU: fewer calls, shorter prompts, batch analysis."""
import os, json, logging, hashlib, httpx
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Simple in-memory cache (keyed by content hash)
_cache: Dict[str, object] = {}
CACHE_MAX = 500

def _cache_key(text: str) -> str:
    return hashlib.md5(text[:2000].encode()).hexdigest()

class AICorrector:
    def __init__(self):
        self.api_base = os.environ.get("AI_API_BASE", "https://api.openai.com/v1")
        self.api_key = os.environ.get("AI_API_KEY", "")
        self.model = os.environ.get("AI_MODEL", "gpt-3.5-turbo")

    async def load_from_db(self, db):
        try:
            api_base = await db.get_config("ai_api_base", "")
            api_key = await db.get_config("ai_api_key", "")
            model = await db.get_config("ai_model", "")
            if api_base: self.api_base = api_base
            if api_key: self.api_key = api_key
            if model: self.model = model
        except Exception as e:
            logger.error(f"Failed to load AI config: {e}")

    # ── Combined batch analysis (single call replaces 3-4 separate calls) ──

    async def analyze_book(self, filename: str, content_sample: str,
                           existing_chapters: List[Dict] = None) -> Dict:
        """One-shot analysis: extract title, author, category, tags, and extra chapters.
        Replaces: extract_book_name + extract_category + extract_tags + detect_chapters (4 calls → 1).
        """
        ch_list = ""
        if existing_chapters:
            ch_list = "\n已有章节: " + ", ".join(
                ch["title"] for ch in existing_chapters[:20] if ch.get("title"))

        prompt = f"""分析这本书，返回JSON:
文件名:{filename}
内容:{content_sample[:800]}
{ch_list}
{{"title":"","author":"","category":"","tags":[""],"new_chapters":[{{"title":"","line":0}}]}}

category可选:小说/文学/历史/哲学/科学/技术/经济/管理/教育/艺术/漫画/其他
new_chapters:仅补充已有章节未覆盖的,无则返回空数组"""
        result = await self._call_api(prompt, max_tokens=300)
        return self._parse_json(result)

    # ── Individual methods (kept for backward compatibility) ──

    async def extract_book_name(self, filename: str, content_sample: str = "") -> Dict:
        ck = _cache_key(filename + content_sample)
        if ck in _cache:
            return _cache[ck]
        prompt = f"""提取书名和作者。
文件名:{filename}
内容:{content_sample[:500]}
返回:{{"title":"","author":"","confidence":90}}"""
        r = self._parse_json(await self._call_api(prompt, max_tokens=100))
        _put_cache(ck, r)
        return r

    async def extract_category(self, title: str, author: str = "", content_sample: str = "") -> Dict:
        prompt = f"""判断分类。书名:{title} 作者:{author}
内容:{content_sample[:300]}
返回:{{"category":"小说","confidence":90}}
可选:小说/文学/历史/哲学/科学/技术/经济/管理/教育/艺术/漫画/其他"""
        return self._parse_json(await self._call_api(prompt, max_tokens=50))

    async def extract_tags(self, title: str, author: str = "", content_sample: str = "") -> Dict:
        prompt = f"""提取3个标签。书名:{title} 作者:{author}
内容:{content_sample[:300]}
返回:{{"tags":["标签1","标签2","标签3"]}}"""
        return self._parse_json(await self._call_api(prompt, max_tokens=80))

    async def detect_chapters(self, text_sample: str) -> Dict:
        ck = _cache_key(text_sample)
        if ck in _cache:
            return _cache[ck]
        prompt = f"""识别章节标题，返回JSON。
{text_sample[:1500]}
{{"chapters":[{{"title":"","line":0}}]}}"""
        r = self._parse_json(await self._call_api(prompt, max_tokens=200))
        _put_cache(ck, r)
        return r

    async def fix_ocr_errors(self, text: str, context: str = "") -> str:
        ck = _cache_key(text)
        if ck in _cache:
            return _cache[ck]
        prompt = f"""修复错别字，只返回修复后文本:
{text[:1500]}"""
        r = await self._call_api(prompt, max_tokens=800)
        _put_cache(ck, r)
        return r.strip()

    async def merge_duplicates(self, chapters: List[Dict]) -> List[Dict]:
        if len(chapters) <= 2:
            return chapters
        titles = [ch.get("title", "") for ch in chapters[:30]]
        prompt = f"""合并重复章节，返回合并后标题列表:
{json.dumps(titles, ensure_ascii=False)}
返回:{{"merged":["标题1","标题2"]}}"""
        r = self._parse_json(await self._call_api(prompt, max_tokens=150))
        if isinstance(r, dict) and "merged" in r:
            merged_titles = r["merged"]
            return [ch for ch in chapters if ch.get("title") in merged_titles]
        return chapters

    async def generate_summary(self, content: str) -> str:
        prompt = f"""100字摘要:{content[:1000]}"""
        return (await self._call_api(prompt, max_tokens=150)).strip()

    # ── API layer ──

    async def _call_api(self, prompt: str, max_retries: int = 2,
                        max_tokens: int = 500) -> str:
        if not self.api_key:
            raise ValueError("AI API key not configured")

        data = {
            "model": self.model,
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.1,
            "max_tokens": max_tokens
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        last_error = None
        for attempt in range(max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=60.0) as client:
                    resp = await client.post(
                        f"{self.api_base}/chat/completions",
                        headers=headers, json=data)
                    if resp.status_code == 200:
                        return resp.json()["choices"][0]["message"]["content"]
                    elif resp.status_code == 429:
                        import asyncio
                        await asyncio.sleep(2 ** attempt * 2)
                        continue
                    else:
                        last_error = f"API {resp.status_code}"
            except httpx.TimeoutException:
                last_error = "timeout"
            except Exception as e:
                last_error = str(e)

        raise Exception(f"AI failed ({max_retries} retries): {last_error}")

    def _parse_json(self, text: str) -> Dict:
        try:
            if "```" in text:
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            return json.loads(text.strip())
        except:
            return {"error": "parse failed", "raw": text[:200]}


def _put_cache(key, value):
    if len(_cache) >= CACHE_MAX:
        # Remove oldest half
        keys = list(_cache.keys())
        for k in keys[:CACHE_MAX // 2]:
            del _cache[k]
    _cache[key] = value
