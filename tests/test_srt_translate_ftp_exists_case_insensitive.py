import unittest


from srt_translate.mcp.ftp import FtpMcp, FtpEntry


class _FakeFtpMcp(FtpMcp):
    def __init__(self):
        pass

    def list(self, path: str):
        return [
            FtpEntry(path=f"{path}/Movie.AI.SRT", type="file", size=1, mtime=None),
        ]


class TestFtpExistsCaseInsensitive(unittest.TestCase):
    def test_exists_is_case_insensitive_on_basename(self):
        ftp = _FakeFtpMcp()
        self.assertTrue(ftp.exists("/Downloads/Movie.ai.srt"))

