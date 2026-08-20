"""
数据同步 CLI

用法：
    python -m quant.scripts.data_download incremental [--symbols 600519.SH,000001.SZ] [--adjust qfq] [--dry-run]
    python -m quant.scripts.data_download full        [--start 20000101] [--end 20260819]
    python -m quant.scripts.data_download calibrate   [--symbols ...] [--window 10]
    python -m quant.scripts.data_download status      [--symbols ...]

退出码：
    0 = 全部成功或按预期跳过
    1 = 存在 failed
    2 = 配置/参数错误
"""
import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

# 仅用于解析 config.yaml 路径（不依赖安装路径）
_BACKEND = Path(__file__).parent.parent.parent

from quant.config import load_config
from quant.data import DataSyncService
from quant.utils.logger import logger


def cmd_incremental(args: argparse.Namespace) -> int:
    """增量同步"""
    load_config(str(_BACKEND / "quant" / "config.yaml"))
    service = DataSyncService()
    symbols = args.symbols.split(",") if args.symbols else None
    report = service.run_incremental(symbols=symbols, adjust=args.adjust, dry_run=args.dry_run)
    _print_report(report)
    return 1 if report.failed > 0 else 0


def cmd_full(args: argparse.Namespace) -> int:
    """全量同步"""
    load_config(str(_BACKEND / "quant" / "config.yaml"))
    service = DataSyncService()
    symbols = args.symbols.split(",") if args.symbols else None
    report = service.run_full(
        symbols=symbols,
        start=args.start,
        end=args.end,
        adjust=args.adjust,
    )
    _print_report(report)
    return 1 if report.failed > 0 else 0


def cmd_calibrate(args: argparse.Namespace) -> int:
    """校准（对已有数据重新校准）"""
    load_config(str(_BACKEND / "quant" / "config.yaml"))
    from quant.data import DataCalibrator
    from quant.storage.database import Database
    from quant.config import get_config

    db = Database()
    calibrator = DataCalibrator()
    symbols = args.symbols.split(",") if args.symbols else get_config().get("data.stock_pool", [])
    if not symbols:
        logger.warning("标的池为空，请用 --symbols 指定")
        return 2

    logger.info(f"开始校准 {len(symbols)} 个标的")
    total_issues = 0
    for symbol in symbols:
        # 取最近 10 个自然日数据重新校准
        today = date.today()
        start = today - timedelta(days=args.window)
        df = db.get_stock_daily(symbol, start, today, "qfq")
        if df.empty:
            logger.warning(f"{symbol}: 库中无数据，跳过")
            continue
        _, report = calibrator.calibrate(df, symbol, "qfq")
        if report.issues:
            db.save_calibration_logs(report.issues)
            total_issues += len(report.issues)
        logger.info(f"{symbol}: {report.passed}/{report.total_rows} 通过，差异 {report.discrepancies}")

    logger.info(f"校准完成，共 {total_issues} 个差异")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    """查看同步状态"""
    load_config(str(_BACKEND / "quant" / "config.yaml"))
    from quant.storage.database import Database

    db = Database()
    symbols = args.symbols.split(",") if args.symbols else []
    if not symbols:
        from quant.config import get_config
        cfg = get_config()
        symbols = cfg.get("data.stock_pool", [])
        if not symbols:
            logger.error("标的池为空，请用 --symbols 指定")
            return 2

    print(f"{'标的':<12} {'复权':<6} {'最新交易日':<12} {'断点结束':<12} {'状态':<10}")
    print("-" * 60)
    for symbol in symbols:
        bp = db.get_latest_success_fetch(symbol, "qfq")
        latest = db.get_latest_trade_date(symbol, "qfq")
        status = "success" if bp else "无记录"
        bp_end = str(bp["end_date"]) if bp else "-"
        latest_str = str(latest) if latest else "-"
        print(f"{symbol:<12} {'qfq':<6} {latest_str:<12} {bp_end:<12} {status:<10}")
    return 0


def _print_report(report) -> None:
    """打印 BatchFetchReport"""
    print("\n=== 批量同步报告 ===")
    print(f"总数: {report.total}")
    print(f"成功: {report.success}  |  部分成功: {report.partial}  |  失败: {report.failed}")
    print(f"空数据: {report.empty}  |  Stale: {report.stale}  |  跳过: {report.skipped}")
    print(f"总行数: {report.total_rows}  |  耗时: {report.total_duration_ms}ms")
    if report.failures:
        print("\n失败清单:")
        for f in report.failures:
            print(f"  - {f.symbol}: {f.error}")
    if report.stale_symbols:
        print("\nStale 提示:")
        for s in report.stale_symbols:
            print(f"  - {s.symbol}: {s.message}")


def main() -> int:
    parser = argparse.ArgumentParser(description="数据同步 CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_inc = sub.add_parser("incremental", help="增量同步")
    p_inc.add_argument("--symbols", help="标的列表，逗号分隔")
    p_inc.add_argument("--adjust", default="qfq", help="复权类型")
    p_inc.add_argument("--dry-run", action="store_true", help="仅打印计划区间")

    p_full = sub.add_parser("full", help="全量同步")
    p_full.add_argument("--symbols", help="标的列表，逗号分隔")
    p_full.add_argument("--start", default=None, help="开始日期 YYYYMMDD")
    p_full.add_argument("--end", default=None, help="结束日期 YYYYMMDD")
    p_full.add_argument("--adjust", default="qfq", help="复权类型")

    p_cal = sub.add_parser("calibrate", help="重新校准")
    p_cal.add_argument("--symbols", help="标的列表，逗号分隔，默认取 stock_pool")
    p_cal.add_argument("--window", type=int, default=10, help="校准窗口（自然日）")

    p_stat = sub.add_parser("status", help="查看同步状态")
    p_stat.add_argument("--symbols", help="标的列表，逗号分隔")

    args = parser.parse_args()

    commands = {
        "incremental": cmd_incremental,
        "full": cmd_full,
        "calibrate": cmd_calibrate,
        "status": cmd_status,
    }

    return commands[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
