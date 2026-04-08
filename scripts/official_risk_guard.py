import re
from dataclasses import dataclass


WHITESPACE_RE = re.compile(r"\s+")
DETAIL_LIMIT = 220
TOAST_SELECTORS = (
    "div.d-toast",
    "[class*='toast']",
    "[class*='Toast']",
    "[role='alert']",
    "[class*='message']",
)

OFFICIAL_RISK_PHRASES = (
    "访问频繁，请稍后再试",
    "访问频次异常",
    "安全限制",
    "请切换可靠网络环境后重试",
)


def normalize_text(value: str) -> str:
    return WHITESPACE_RE.sub(" ", str(value or "")).strip()


def truncate_detail(text: str, limit: int = DETAIL_LIMIT) -> str:
    compact = normalize_text(text)
    if len(compact) <= limit:
        return compact
    return compact[: max(limit - 1, 0)].rstrip("，。；,; ") + "…"


@dataclass
class RiskDetectionResult:
    is_risk: bool
    matched_phrase: str = ""
    detail: str = ""
    source: str = ""

    def to_dict(self) -> dict:
        return {
            "is_risk": self.is_risk,
            "matched_phrase": self.matched_phrase,
            "detail": self.detail,
            "source": self.source,
        }


class OfficialRiskDetectedError(RuntimeError):
    def __init__(
        self,
        matched_phrase: str,
        detail: str = "",
        *,
        source: str = "",
        context: str = "",
    ) -> None:
        self.matched_phrase = normalize_text(matched_phrase)
        self.detail = truncate_detail(detail or matched_phrase)
        self.source = normalize_text(source)
        self.context = normalize_text(context)

        message = f"检测到官方风控提示：{self.matched_phrase}"
        if self.context:
            message = f"{self.context} -> {message}"
        if self.detail and self.detail != self.matched_phrase:
            message += f" | {self.detail}"
        if self.source:
            message += f" [{self.source}]"
        super().__init__(message)

    def to_dict(self) -> dict:
        return {
            "risk_signal": True,
            "risk_phrase": self.matched_phrase,
            "risk_detail": self.detail,
            "risk_source": self.source,
            "risk_context": self.context,
        }


@dataclass
class RiskStopTracker:
    stop_after: int = 3
    consecutive_risk_hits: int = 0
    total_risk_hits: int = 0
    stopped_due_to_risk: bool = False
    last_risk_phrase: str = ""
    last_risk_detail: str = ""

    def __post_init__(self) -> None:
        if int(self.stop_after) <= 0:
            raise ValueError("risk stop threshold must be greater than 0")
        self.stop_after = int(self.stop_after)

    def record_risk(self, matched_phrase: str, detail: str = "") -> dict:
        self.total_risk_hits += 1
        self.consecutive_risk_hits += 1
        self.last_risk_phrase = normalize_text(matched_phrase)
        self.last_risk_detail = truncate_detail(detail or matched_phrase)
        self.stopped_due_to_risk = self.consecutive_risk_hits >= self.stop_after
        return self.snapshot()

    def record_success(self) -> dict:
        self.consecutive_risk_hits = 0
        self.stopped_due_to_risk = False
        return self.snapshot()

    def snapshot(self) -> dict:
        return {
            "risk_stop_after": self.stop_after,
            "consecutive_risk_hits": self.consecutive_risk_hits,
            "total_risk_hits": self.total_risk_hits,
            "stopped_due_to_risk": self.stopped_due_to_risk,
            "risk_phrase": self.last_risk_phrase,
            "risk_detail": self.last_risk_detail,
        }


def detect_official_risk_in_text(text: str, *, source: str = "") -> RiskDetectionResult:
    compact_text = truncate_detail(text, limit=DETAIL_LIMIT * 2)
    if not compact_text:
        return RiskDetectionResult(False, source=source)

    for phrase in OFFICIAL_RISK_PHRASES:
        if phrase in compact_text:
            return RiskDetectionResult(
                True,
                matched_phrase=phrase,
                detail=truncate_detail(compact_text),
                source=source,
            )

    if "访问频繁" in compact_text and "稍后再试" in compact_text:
        return RiskDetectionResult(
            True,
            matched_phrase="访问频繁，请稍后再试",
            detail=truncate_detail(compact_text),
            source=source,
        )

    return RiskDetectionResult(False, source=source)


def _page_text_candidates(page) -> list[tuple[str, str]]:
    candidates: list[tuple[str, str]] = []

    try:
        body_text = page.locator("body").inner_text(timeout=2_000)
        if body_text:
            candidates.append(("body", body_text))
    except Exception:
        pass

    try:
        toast_payloads = page.evaluate(
            """
            (selectors) => {
                const seen = new Set();
                const rows = [];
                for (const selector of selectors) {
                    const nodes = Array.from(document.querySelectorAll(selector));
                    for (const node of nodes) {
                        const style = window.getComputedStyle(node);
                        const rect = node.getBoundingClientRect();
                        const visible = (
                            !!style &&
                            style.display !== "none" &&
                            style.visibility !== "hidden" &&
                            rect.width > 0 &&
                            rect.height > 0
                        );
                        if (!visible) continue;
                        const text = (node.innerText || node.textContent || "").replace(/\\s+/g, " ").trim();
                        if (!text || seen.has(text)) continue;
                        seen.add(text);
                        rows.push({ source: selector, text });
                    }
                }
                return rows;
            }
            """,
            list(TOAST_SELECTORS),
        )
        if isinstance(toast_payloads, list):
            for item in toast_payloads:
                if not isinstance(item, dict):
                    continue
                text = normalize_text(item.get("text", ""))
                if text:
                    candidates.append((f"toast:{item.get('source', '')}", text))
    except Exception:
        pass

    return candidates


def detect_official_risk(page) -> RiskDetectionResult:
    for source, text in _page_text_candidates(page):
        detected = detect_official_risk_in_text(text, source=source)
        if detected.is_risk:
            return detected
    return RiskDetectionResult(False)


def raise_if_official_risk(page, *, context: str = "") -> None:
    detected = detect_official_risk(page)
    if not detected.is_risk:
        return
    raise OfficialRiskDetectedError(
        detected.matched_phrase,
        detected.detail,
        source=detected.source,
        context=context,
    )
