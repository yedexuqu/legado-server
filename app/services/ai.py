"""AI service — wraps AICorrector with config-from-DB loading."""

import logging

logger = logging.getLogger(__name__)


class AIService:
    """Manages AI corrector as a single shared instance."""

    def __init__(self):
        from ..ai.corrector import AICorrector
        self._corrector = AICorrector()

    async def init(self, db):
        """Load AI config from database."""
        await self._corrector.load_from_db(db)

    @property
    def corrector(self):
        return self._corrector

    @property
    def api_key(self):
        return self._corrector.api_key

    # Delegate common methods for convenience
    async def detect_chapters(self, text_sample):
        return await self._corrector.detect_chapters(text_sample)

    async def fix_ocr_errors(self, text, context=""):
        return await self._corrector.fix_ocr_errors(text, context)
