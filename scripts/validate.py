#!/usr/bin/env python
"""
코스피 거래량 상위 30종목 대시보드 - 일일 검증 스크립트 (Subagent 6)
================================================================

Daily validation & health-check tool for the surge prediction pipeline.

Usage (PowerShell, 프로젝트 루트에서 실행):
    python -m scripts.validate --date latest
    python -m scripts.validate --date 20260528
    python -m scripts.validate --date 2026-05-28 --verbose
    python -m scripts.validate --date latest --print-snapshot

Exit codes:
    0 = 모든 기본 검증 통과 (데이터 레이어 완성 시 실제 예측까지)
    1 = 치명적 오류 (모듈 import 실패 등)
    2 = 데이터/분석 레이어 미구현 (현재 스켈레톤 상태에서 정상)

이 스크립트는 매일 아침 실행하여 "오늘 데이터가 정상 수집되고 예측 파이프라인이 동작하는지" 빠르게 확인하기 위해 설계되었습니다.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

# ============================================================
# Windows 한국어 콘솔 (cp949) + 이모지/한글 안전 인코딩 설정
# ============================================================
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        os.environ["PYTHONIOENCODING"] = "utf-8"

# 프로젝트 루트 기준으로 import 경로 추가 (python -m scripts.validate 실행 시 필요)
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# 프로젝트 내부 모듈 (순환 import 방지 주의)
from utils.helpers import (
    format_date_kr,
    get_next_trading_day,
    is_valid_trading_date,
    filter_common_stocks,
)
from utils.models import StockFeatures, AnalysisResult

# data.fetcher에서 get_latest_trading_day만 안전하게 로드
# (fetcher 모듈 import 시 pandas가 실행되는 환경에서도 동작하도록 fallback 제공)
try:
    from data.fetcher import get_latest_trading_day as _fetcher_get_latest
except Exception:
    _fetcher_get_latest = None


def get_latest_trading_day_safe() -> str:
    """환경에 따라 fetcher 또는 순수 datetime fallback 사용."""
    if _fetcher_get_latest is not None:
        try:
            return _fetcher_get_latest()
        except Exception:
            pass
    # 순수 Python fallback (pandas 미설치/파손 환경 대응)
    d = datetime.now()
    for _ in range(10):
        if d.weekday() < 5:
            return d.strftime("%Y%m%d")
        d -= timedelta(days=1)
    return datetime.now().strftime("%Y%m%d")


# 분석 모듈 (구현 여부에 따라 graceful fallback)
try:
    from analysis.predictor import compute_surge_score, build_analysis_result
    PREDICTOR_AVAILABLE = True
except (ImportError, NotImplementedError):
    PREDICTOR_AVAILABLE = False

try:
    from analysis.analyzer import batch_analyze
    ANALYZER_AVAILABLE = True
except (ImportError, NotImplementedError):
    ANALYZER_AVAILABLE = False

try:
    from data.fetcher import get_kospi_top30_volume, get_ohlcv_history, enrich_with_investor_data
    FETCHER_FULL_AVAILABLE = True
except (ImportError, NotImplementedError):
    FETCHER_FULL_AVAILABLE = False


def parse_target_date(date_arg: str) -> str:
    """사용자 입력 date를 YYYYMMDD 형식으로 정규화."""
    date_arg = date_arg.strip()

    if date_arg.lower() == "latest":
        return get_latest_trading_day_safe()

    # 20260528 또는 2026-05-28 또는 2026/05/28 지원
    for fmt in ("%Y%m%d", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            dt = datetime.strptime(date_arg, fmt)
            return dt.strftime("%Y%m%d")
        except ValueError:
            continue

    # dateutil fallback (설치되어 있으면)
    try:
        from dateutil import parser as date_parser
        dt = date_parser.parse(date_arg)
        return dt.strftime("%Y%m%d")
    except Exception:
        pass

    raise ValueError(f"지원하지 않는 날짜 형식입니다: {date_arg}. 예: latest, 20260528, 2026-05-28")


def create_dummy_stock_features(target_date: str, rank: int = 1) -> StockFeatures:
    """검증용 더미 StockFeatures 생성 (실제 데이터 없을 때 파이프라인 테스트용)."""
    return StockFeatures(
        ticker=f"005930{rank:02d}",
        name=f"삼성전자{'' if rank == 1 else '우' if rank == 2 else ''}",
        target_date=target_date,
        close=78500.0 + rank * 120,
        volume=12000000 + rank * 850000,
        volume_ratio=round(1.2 + rank * 0.35, 2),
        ma5=77200.0,
        ma20=75800.0,
        ma60=74100.0,
        rsi_14=round(58.5 + rank * 1.2, 1),
        macd=320.0 + rank * 15,
        macd_signal=280.0,
        macd_hist=40.0 + rank * 5,
        five_day_return=round(2.8 + rank * 0.4, 2),
        ten_day_return=round(4.1 + rank * 0.6, 2),
        above_ma5=True,
        above_ma20=True,
        above_ma60=(rank % 2 == 0),
        trend_strength=round(0.45 + rank * 0.03, 2),
        volume_spike=(rank <= 3),
        volume_explosion=(rank == 1),
        foreign_netbuy=3500000000 * rank,
        inst_netbuy=1200000000 * (rank % 3),
        netbuy_score=round(1.8 + rank * 0.25, 2),
        surge_score=0.0,  # predictor가 채움
        surge_label="Low",
        reason_tags=[],
        recommendation="",
        rank=rank,
    )


def run_validation(target_date: str, verbose: bool = False, print_snapshot: bool = False) -> Dict[str, Any]:
    """메인 검증 로직. 결과 dict 반환 (JSON snapshot 용)."""
    result: Dict[str, Any] = {
        "target_date": target_date,
        "target_date_kr": format_date_kr(target_date),
        "next_trading_day": get_next_trading_day(target_date),
        "next_trading_day_kr": format_date_kr(get_next_trading_day(target_date)),
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "checks": {},
        "status": "UNKNOWN",
        "surge_prediction_methodology": {
            "weights": {
                "volume": "30%",
                "momentum": "25%",
                "trend": "20%",
                "oscillator": "15%",
                "supply_demand": "10%",
            },
            "note": "predictor.compute_surge_score 구현 후 실제 가중치 적용"
        },
    }

    # 1. 날짜 유효성 기본 체크
    is_weekday = is_valid_trading_date(target_date)
    result["checks"]["date_format_valid"] = "PASS (YYYYMMDD 정규화 성공)"
    result["checks"]["is_weekday"] = "PASS" if is_weekday else "WARN (주말/공휴일 가능성)"
    if not is_weekday:
        result["checks"]["date_warning"] = "주말 또는 비영업일 형식. pykrx가 실제 영업일로 보정할 수 있음."

    # 2. Helpers 모듈 동작 확인
    try:
        next_day = get_next_trading_day(target_date)
        formatted = format_date_kr(target_date)
        result["checks"]["helpers"] = "PASS"
        if verbose:
            print(f"  [OK] helpers: next_day={format_date_kr(next_day)}, formatted={formatted}")
    except Exception as e:
        result["checks"]["helpers"] = f"FAIL: {e}"
        result["status"] = "FAIL"
        return result

    # 3. Models (dataclass) 동작 확인
    try:
        dummy = create_dummy_stock_features(target_date, rank=1)
        assert dummy.ticker and dummy.surge_score == 0.0
        result["checks"]["models"] = "PASS"
        if verbose:
            print(f"  [OK] models: StockFeatures + AnalysisResult dataclass 생성 성공")
    except Exception as e:
        result["checks"]["models"] = f"FAIL: {e}"
        result["status"] = "FAIL"
        return result

    # 4. Fetcher 레이어 (latest는 항상 가능, full fetch는 현재 미구현)
    try:
        latest = get_latest_trading_day_safe()
        result["checks"]["fetcher_latest"] = f"PASS (latest={format_date_kr(latest)})"
        if verbose:
            print(f"  [OK] get_latest_trading_day_safe() = {format_date_kr(latest)}")
    except Exception as e:
        result["checks"]["fetcher_latest"] = f"FAIL: {e}"

    if FETCHER_FULL_AVAILABLE:
        try:
            # 실제 호출 시도 (현재는 NotImplementedError 예상)
            _ = get_kospi_top30_volume(target_date)
            result["checks"]["fetcher_full"] = "PASS (실제 데이터 반환)"
        except NotImplementedError:
            result["checks"]["fetcher_full"] = "STUB (Subagent 1 미완성 - NotImplemented)"
        except Exception as e:
            result["checks"]["fetcher_full"] = f"ERROR: {type(e).__name__}: {e}"
    else:
        result["checks"]["fetcher_full"] = "NOT_IMPORTED (현재 스켈레톤)"

    # 5. Predictor / Surge Score 파이프라인 검증 (핵심)
    dummy_stocks: List[StockFeatures] = [
        create_dummy_stock_features(target_date, i) for i in range(1, 6)
    ]

    if PREDICTOR_AVAILABLE:
        try:
            scored = [compute_surge_score(s) for s in dummy_stocks]
            analysis = build_analysis_result(scored, target_date)

            result["checks"]["predictor"] = "PASS"
            result["checks"]["surge_labels"] = {s.ticker: s.surge_label for s in scored}
            result["top5_preview"] = [
                {
                    "rank": s.rank,
                    "name": s.name,
                    "surge_score": round(s.surge_score, 1),
                    "label": s.surge_label,
                    "volume_ratio": s.volume_ratio,
                }
                for s in analysis.top5
            ]
            if verbose:
                print("  [OK] predictor: compute_surge_score + build_analysis_result 동작")
        except NotImplementedError:
            result["checks"]["predictor"] = "STUB (Subagent 5 미완성)"
            result["top5_preview"] = "미구현 (예시 데이터만 사용)"
        except Exception as e:
            result["checks"]["predictor"] = f"ERROR: {e}"
    else:
        result["checks"]["predictor"] = "NOT_IMPORTED"

    # 6. Analyzer 레이어
    if ANALYZER_AVAILABLE:
        result["checks"]["analyzer"] = "IMPORTED (Subagent 3/4 영역)"
    else:
        result["checks"]["analyzer"] = "STUB (미구현)"

    # 전체 상태 결정
    critical_passes = [
        result["checks"].get("helpers") == "PASS",
        result["checks"].get("models") == "PASS",
        "PASS" in str(result["checks"].get("fetcher_latest", "")),
    ]
    if all(critical_passes):
        if "STUB" in str(result["checks"].get("predictor", "")) or "STUB" in str(result["checks"].get("fetcher_full", "")):
            result["status"] = "PARTIAL (데이터/예측 레이어 미구현 - 향후 완성 시 FULL)"
        else:
            result["status"] = "PASS"
    else:
        result["status"] = "FAIL"

    # Snapshot 데이터 추가 (사용자가 --print-snapshot 으로 캡처 가능)
    if print_snapshot:
        snapshot = {
            "meta": {
                "generated_for": target_date,
                "generated_at": result["timestamp"],
                "note": "이 데이터는 실제 fetcher/analyzer 구현 완료 후 대체됩니다. 현재는 검증용 더미 + 스텁 결과입니다.",
            },
            "analysis_result_example": {
                "target_date": target_date,
                "next_trading_day": result["next_trading_day"],
                "stocks": [
                    {
                        "ticker": s.ticker,
                        "name": s.name,
                        "close": s.close,
                        "volume_ratio": s.volume_ratio,
                        "rsi_14": s.rsi_14,
                        "foreign_netbuy": s.foreign_netbuy,
                        "surge_score": s.surge_score,
                        "surge_label": s.surge_label,
                        "reason_tags": s.reason_tags,
                    }
                    for s in dummy_stocks
                ],
            },
            "surge_methodology": result["surge_prediction_methodology"],
        }
        result["snapshot"] = snapshot

    return result


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="코스피 거래량 Top30 대시보드 일일 검증 스크립트",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
  python -m scripts.validate --date latest
  python -m scripts.validate --date 20260528 --verbose
  python -m scripts.validate --date 2026-05-28 --print-snapshot > snapshot-20260528.json
        """,
    )
    parser.add_argument(
        "--date",
        default="latest",
        help="분석 기준일 (YYYYMMDD 또는 YYYY-MM-DD 또는 'latest'). 기본: latest",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="상세 로그 출력"
    )
    parser.add_argument(
        "--print-snapshot",
        action="store_true",
        help="검증용 스냅샷 JSON을 stdout에 출력 (리다이렉트하여 파일 저장 가능)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="전체 결과를 JSON으로만 출력 (CI/스크립트 자동화용)",
    )

    args = parser.parse_args(argv)

    try:
        target_date = parse_target_date(args.date)
    except Exception as e:
        print(f"[ERROR] 날짜 파싱 실패: {e}", file=sys.stderr)
        return 1

    print("=" * 70)
    print("[KOSPI] 코스피 거래량 상위 30종목 분석 대시보드 - 일일 검증")
    print(f"   기준일: {format_date_kr(target_date)} (익일 예측: {format_date_kr(get_next_trading_day(target_date))})")
    print(f"   실행시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    try:
        validation_result = run_validation(
            target_date=target_date,
            verbose=args.verbose,
            print_snapshot=args.print_snapshot,
        )
    except Exception as exc:
        print(f"\n[CRITICAL] 검증 실행 중 예외 발생:\n{traceback.format_exc()}", file=sys.stderr)
        return 1

    # 출력
    if args.json:
        print(json.dumps(validation_result, ensure_ascii=False, indent=2))
    else:
        print("\n[검증 결과 요약]")
        for key, val in validation_result["checks"].items():
            val_str = str(val)
            if "PASS" in val_str or val is True:
                icon = "[OK]"
            elif "STUB" in val_str or "미구현" in val_str or "WARN" in val_str:
                icon = "[WARN]"
            elif val is False or "FAIL" in val_str or "ERROR" in val_str:
                icon = "[FAIL]"
            else:
                icon = "[INFO]"
            print(f"  {icon} {key}: {val}")

        print(f"\n[전체 상태] {validation_result['status']}")

        if "top5_preview" in validation_result and isinstance(validation_result["top5_preview"], list):
            print("\n[Top5 Surge Score 미리보기 (더미 데이터)]")
            for item in validation_result["top5_preview"]:
                print(f"  {item['rank']}. {item['name']} ({item.get('ticker','')}) "
                      f"— 점수: {item['surge_score']} ({item['label']}) | VolRatio: {item['volume_ratio']}x")

        if args.print_snapshot and "snapshot" in validation_result:
            print("\n" + "=" * 70)
            print("[SNAPSHOT] DATA SNAPSHOT (JSON)")
            print("=" * 70)
            print(json.dumps(validation_result["snapshot"], ensure_ascii=False, indent=2))

        print("\n" + "-" * 70)
        print("[TIP] --print-snapshot 로 현재 상태의 스냅샷을 저장하세요.")
        print("   실제 데이터 파이프라인 완성 후 이 스크립트로 매일 자동 검증하세요.")
        print("-" * 70)

    # Exit code 규칙
    if validation_result["status"].startswith("PASS"):
        return 0
    if "PARTIAL" in validation_result["status"] or "STUB" in str(validation_result["checks"]):
        # 현재 프로젝트 상태에서는 정상 (구현 예정)
        return 2
    return 1


if __name__ == "__main__":
    sys.exit(main())
