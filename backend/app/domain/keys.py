"""规范键与稳定标识。

设计原则：
1. 业务行不可变；同一逻辑对象的不同观测是不同 ``fact_id``。
2. 所有 ID 由内容派生（SHA-256），保证换机器、换进程、重跑都能得到同一 ID。
3. 键是 *逻辑键*，不是旧值 ID——增量更新时新增记录才有入边可挂。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, asdict
from decimal import Decimal
from typing import Any, Iterable, Mapping, Sequence


# --------------------------------------------------------------------------- #
# 规范化
# --------------------------------------------------------------------------- #

def canonical_json(obj: Any) -> str:
    """JSON Canonical 化：键排序、金额用字符串、集合排序、无多余空白。"""
    return json.dumps(_norm(obj), ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _norm(obj: Any) -> Any:
    if isinstance(obj, Mapping):
        return {str(k): _norm(v) for k, v in sorted(obj.items(), key=lambda kv: str(kv[0]))}
    if isinstance(obj, (list, tuple)):
        return [_norm(v) for v in obj]
    if isinstance(obj, (set, frozenset)):
        return sorted(_norm(v) for v in obj)
    if isinstance(obj, Decimal):
        return dec_str(obj)
    if isinstance(obj, bool):
        return obj
    if obj is None or isinstance(obj, (str, int, float)):
        return obj
    return str(obj)


def dec_str(value: Decimal | str | int | float) -> str:
    """Decimal → 十进制字符串（不用科学计数法，不丢精度）。"""
    d = value if isinstance(value, Decimal) else Decimal(str(value))
    s = format(d.normalize(), "f")
    if s in ("-0", "-0.0"):
        s = "0"
    return s


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def short_id(full: str, n: int = 10) -> str:
    return full[:n]


def content_id(prefix: str, payload: Any) -> str:
    return f"{prefix}:{sha256_hex(canonical_json(payload))[:32]}"


# --------------------------------------------------------------------------- #
# FactKey
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class FactKey:
    """事实键。币种与定义属于键的一部分：它们不同就不是同一个事实。"""

    entity_id: str
    field_code: str
    period_start: str          # YYYY-MM-DD
    period_end: str            # YYYY-MM-DD
    period_kind: str           # FY（流量） | POINT（期末余额）
    consolidation: str         # consolidated | parent
    currency: str              # CNY
    business_scope: str        # total | segment:beer | segment:other
    definition_id: str         # 字段口径版本，见 config/metrics

    def canonical(self) -> str:
        return "|".join(
            [
                self.entity_id,
                self.field_code,
                f"{self.period_start}~{self.period_end}",
                self.period_kind,
                self.consolidation,
                self.currency,
                self.business_scope,
                self.definition_id,
            ]
        )

    @property
    def key(self) -> str:
        return f"fk:{sha256_hex(self.canonical())[:24]}"

    def describe(self) -> dict[str, str]:
        return asdict(self)

    @classmethod
    def parse(cls, canonical: str) -> "FactKey":
        parts = canonical.split("|")
        if len(parts) != 8:
            raise ValueError(f"非法 FactKey: {canonical}")
        s, e = parts[2].split("~")
        return cls(parts[0], parts[1], s, e, parts[3], parts[4], parts[5], parts[6], parts[7])


def fact_version_id(
    key: FactKey,
    document_id: str,
    bytes_sha256: str,
    location_id: str,
    raw_value: str,
    basis_tag: str,
) -> str:
    """事实版本 ID：键 + 文档版本 + 锚点 + 原始值。任一变化即为新版本。"""
    return content_id(
        "fact",
        {
            "fk": key.canonical(),
            "doc": document_id,
            "sha": bytes_sha256,
            "loc": location_id,
            "raw": raw_value,
            "basis": basis_tag,
        },
    )


def metric_result_id(
    metric_key: str, formula_id: str, formula_version: int, input_ids: Sequence[str], status: str, value_text: str | None
) -> str:
    return content_id(
        "metric",
        {
            "mk": metric_key,
            "fid": formula_id,
            "fv": formula_version,
            "inputs": sorted(input_ids),
            "status": status,
            "value": value_text,
        },
    )


def claim_version_id(claim_key: str, template: str, slots: Mapping[str, str], refs: Sequence[str],
                     text: str, verdict: str = "") -> str:
    """审核结论也进哈希：同一段文字被判 WARN 还是 PASS，是不同的结论版本。"""
    return content_id("claim", {"ck": claim_key, "tpl": template, "slots": dict(slots),
                                "refs": sorted(refs), "text": text, "verdict": verdict})


def section_content_hash(content: Any) -> str:
    return sha256_hex(canonical_json(content))


def edge_key(src: str, relation: str, dst: str, scope: str, period: str) -> str:
    return content_id("edge", {"src": src, "rel": relation, "dst": dst, "scope": scope, "period": period})


def report_fingerprint(
    *,
    parser_version: str,
    extractor_version: str,
    model_config: Mapping[str, str],
    prompt_version: str,
    rules_version: str,
    evidence_ids: Iterable[str],
    as_of: str,
    workflow_version: str,
) -> str:
    return sha256_hex(
        canonical_json(
            {
                "parser": parser_version,
                "extractor": extractor_version,
                "model": dict(model_config),
                "prompt": prompt_version,
                "rules": rules_version,
                "evidence": sorted(evidence_ids),
                "as_of": as_of,
                "workflow": workflow_version,
            }
        )
    )


def metric_key(entity_id: str, metric_code: str, fiscal_year: int, scope: str = "FY") -> str:
    return f"{entity_id}/{scope}{fiscal_year}/{metric_code}"
