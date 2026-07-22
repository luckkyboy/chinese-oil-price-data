from __future__ import annotations


class OilPriceError(Exception):
    """Base exception for oil price data pipeline errors."""


class BrowserFetchError(OilPriceError):
    def __init__(self, url: str, cause: Exception) -> None:
        super().__init__(f"browser fetch failed for {url}: {cause}")
        self.url = url
        self.cause = cause


class BrowserHTTPError(OilPriceError):
    def __init__(self, url: str, status: int) -> None:
        super().__init__(f"browser fetch failed with HTTP {status} for {url}")
        self.url = url
        self.status = status


class ResponseTooLargeError(OilPriceError):
    def __init__(self, url: str, max_bytes: int, actual_bytes: int) -> None:
        super().__init__(
            f"response for {url} exceeds {max_bytes} bytes "
            f"(received {actual_bytes} bytes)"
        )
        self.url = url
        self.max_bytes = max_bytes
        self.actual_bytes = actual_bytes


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
