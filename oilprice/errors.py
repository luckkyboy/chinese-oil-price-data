from __future__ import annotations


class OilPriceError(Exception):
    """Base exception for oil price data pipeline errors."""


class BrowserFetchError(OilPriceError):
    def __init__(self, url: str, cause: Exception) -> None:
        super().__init__(f"browser fetch failed for {url}: {cause}")
        self.url = url
        self.cause = cause


class AttachmentFetchError(OilPriceError):
    def __init__(self, url: str, cause: Exception) -> None:
        super().__init__(f"attachment fetch failed for {url}: {cause}")
        self.url = url
        self.cause = cause


class TextExtractionError(OilPriceError):
    def __init__(self, path: str, cause: Exception) -> None:
        super().__init__(f"text extraction failed for {path}: {cause}")
        self.path = path
        self.cause = cause


class OcrError(OilPriceError):
    def __init__(self, path: str, cause: Exception) -> None:
        super().__init__(f"ocr failed for {path}: {cause}")
        self.path = path
        self.cause = cause
