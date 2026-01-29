import sys
import logging
from unittest.mock import MagicMock, patch
from pathlib import Path

# Add src to path
SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from srt_translate.config import AppConfig, LlmConfig, PathsConfig, FtpConfig, SummaryConfig
from srt_translate.summary import generate_summary
from srt_translate.subtitle_acquisition import SubtitleSource

# Setup logging
logging.basicConfig(level=logging.INFO)

def test_manual_summary():
    # 1. Config
    cfg = MagicMock(spec=AppConfig)
    cfg.llm = LlmConfig(
        provider="ollama",
        base_url="http://localhost:11434",
        model="gemma3:latest",
        timeout_seconds=600, # Longer timeout for large context processing
        temperature=0.5
    )
    cfg.summary = SummaryConfig(
        enabled=True,
        max_chars=100000,
        workers=1
    )
    cfg.paths = PathsConfig(
        local_cache_dir=Path("./tests/temp_cache"),
        state_db_path=Path("./tests/temp_cache/state.db")
    )
    cfg.ftp = FtpConfig(host="mock", port=21, username="u", password="p", root_path="/")

    # 2. Source
    original_srt_path = Path("/Users/daibo/db90/tests/To.End.All.Wars.2001.1080p.BluRay.HEVC.x265.5.1-BONE.emb.srt")
    if not original_srt_path.exists():
        print(f"Error: {original_srt_path} not found")
        return

    # Use FULL content this time
    print(f"Using full SRT file size: {original_srt_path.stat().st_size} bytes")

    source = SubtitleSource(
        kind="emb",
        remote_path="/Downloads/test.srt",
        local_path=original_srt_path,
        quality=None,
        meta={}
    )

    # 3. Mock FTP
    with patch("srt_translate.summary.FtpMcp") as MockFtp:
        mock_ftp_instance = MockFtp.return_value
        mock_ftp_instance.__enter__.return_value = mock_ftp_instance
        mock_ftp_instance.exists.return_value = False 
        
        print("Starting summary generation...")
        
        # 4. Run
        video_id = "test_vid_full"
        generate_summary(
            cfg=cfg,
            video_id=video_id,
            video_remote_path="/Downloads/To.End.All.Wars.2001.mkv",
            source=source,
            force=True,
            dry_run=True
        )

    # 5. Check result
    expected_out = cfg.paths.local_cache_dir / "work" / video_id / "out" / "To.End.All.Wars.2001.md"
    if expected_out.exists():
        print(f"\nSUCCESS! Generated file: {expected_out}")
        print("-" * 40)
        print(expected_out.read_text(encoding="utf-8"))
        print("-" * 40)
    else:
        print(f"FAILURE: Output file not found at {expected_out}")

if __name__ == "__main__":
    test_manual_summary()
