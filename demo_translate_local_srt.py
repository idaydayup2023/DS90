import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from srt_translate.config import ensure_dirs, load_config
from srt_translate.mcp.llm_mcp import build_llm_mcp
from srt_translate.translation import to_ai_srt_content, translate_srt_to_bilingual


def main() -> int:
    p = argparse.ArgumentParser(prog="demo_translate_local_srt")
    p.add_argument("--config", required=True)
    p.add_argument("--in", dest="in_path", required=True)
    p.add_argument("--out", dest="out_path", required=True)
    args = p.parse_args()

    cfg = load_config(args.config)
    ensure_dirs(cfg)

    srt_content = Path(args.in_path).read_text(encoding="utf-8", errors="replace")
    llm = build_llm_mcp(cfg.llm.provider, cfg.llm.base_url, timeout_seconds=cfg.llm.timeout_seconds)
    result = translate_srt_to_bilingual(
        llm=llm,
        model=cfg.llm.model,
        srt_content=srt_content,
        batch_size=cfg.translation.batch_size,
        max_retries=cfg.translation.max_retries,
        temperature=cfg.llm.temperature,
    )
    Path(args.out_path).write_text(to_ai_srt_content(result), encoding="utf-8")
    if result.failed_indices:
        sys.stderr.write(f"failed indices: {result.failed_indices}\n")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
