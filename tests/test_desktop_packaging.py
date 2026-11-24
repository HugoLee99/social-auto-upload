import os
import unittest
from pathlib import Path
from unittest.mock import patch

import workbench_server


class DesktopPackagingTests(unittest.TestCase):
    def test_development_data_root_remains_project_root(self):
        with patch.dict(os.environ, {}, clear=False):
            self.assertEqual(workbench_server.default_data_root(), Path(workbench_server.__file__).resolve().parent)

    def test_explicit_data_root_wins(self):
        folder = Path.cwd() / "build" / "test-data-root"
        with patch.dict(os.environ, {"SAU_DATA_DIR": str(folder)}):
            self.assertEqual(workbench_server.default_data_root(), folder.resolve())

    def test_development_cli_uses_python_script(self):
        command = workbench_server.cli_command("douyin", "check", "--account", "creator")
        self.assertEqual(command[1], str(workbench_server.RESOURCE_ROOT / "sau_cli.py"))

    def test_frozen_windows_cli_uses_sibling_executable(self):
        with patch.object(workbench_server, "IS_FROZEN", True), \
             patch.object(workbench_server.sys, "platform", "win32"), \
             patch.object(workbench_server.sys, "executable", r"C:\Apps\DaydreamDispatch.exe"):
            command = workbench_server.cli_command("bilibili", "check", "--account", "creator")
        self.assertEqual(command[0], r"C:\Apps\DaydreamCLI.exe")


if __name__ == "__main__":
    unittest.main()
