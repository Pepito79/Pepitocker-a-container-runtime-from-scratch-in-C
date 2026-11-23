from __future__ import annotations

import io
import unittest
from contextlib import redirect_stderr
from pathlib import Path

from parser import BuildFileError, main, parse_pepito_file


class TestPepitoParser(unittest.TestCase):
    def setUp(self) -> None:
        # Create a temporary project directory for each test
        self.tmp_ctx = Path(self._testMethodName + "_ctx").resolve()
        self.tmp_ctx.mkdir(parents=True, exist_ok=True)
        (self.tmp_ctx / "app.py").write_text("print('hello')\n", encoding="utf-8")
        (self.tmp_ctx / "requirements.txt").write_text("flask\n", encoding="utf-8")

    def tearDown(self) -> None:
        # Clean up temporary directory and any files created inside it
        if self.tmp_ctx.exists():
            for child in sorted(self.tmp_ctx.rglob("*"), reverse=True):
                if child.is_file() or child.is_symlink():
                    child.unlink()
                elif child.is_dir():
                    child.rmdir()
            self.tmp_ctx.rmdir()

    def _write_build_file(self, content: str) -> Path:
        build_file = self.tmp_ctx / "Pepitockerfile"
        build_file.write_text(content, encoding="utf-8")
        return build_file

    def test_valid_build_file_with_json_and_shell_commands(self) -> None:
        build_file = self._write_build_file(
            """
            # Comment line
            BASE alpine

            ENV APP_ENV="prod"
            ENV DEBUG=0
            WORKDIR /app
            MEMORY 512M
            HOSTNAME worker-node

            COPY requirements.txt /app/requirements.txt
            RUN apk add --no-cache python3
            COPY app.py /app/app.py
            CMD ["/usr/bin/python3", "/app/app.py"]
            """
        )

        plan = parse_pepito_file(build_file, context_dir=self.tmp_ctx)

        self.assertEqual(plan.base, "alpine")
        self.assertEqual(plan.context_dir, self.tmp_ctx)
        self.assertEqual(plan.config.env, {"APP_ENV": "prod", "DEBUG": "0"})
        self.assertEqual(plan.config.workdir, "/app")
        self.assertEqual(plan.config.memory, "512M")
        self.assertEqual(plan.config.hostname, "worker-node")
        self.assertEqual(plan.config.cmd, ["/usr/bin/python3", "/app/app.py"])

        self.assertEqual(len(plan.steps), 3)
        self.assertEqual(plan.steps[0].kind, "COPY")
        self.assertEqual(
            plan.steps[0].src, (self.tmp_ctx / "requirements.txt").resolve()
        )
        self.assertEqual(plan.steps[0].dest, "/app/requirements.txt")

        self.assertEqual(plan.steps[1].kind, "RUN")
        self.assertEqual(plan.steps[1].command, ["apk", "add", "--no-cache", "python3"])

        self.assertEqual(plan.steps[2].kind, "COPY")
        self.assertEqual(plan.steps[2].src, (self.tmp_ctx / "app.py").resolve())
        self.assertEqual(plan.steps[2].dest, "/app/app.py")

    def test_missing_base_raises_user_error(self) -> None:
        build_file = self._write_build_file("ENV FOO=bar\nCMD echo hi\n")

        with self.assertRaises(BuildFileError) as ctx:
            parse_pepito_file(build_file)

        self.assertIn("Missing required BASE", str(ctx.exception))

    def test_step_before_base_raises_user_error(self) -> None:
        build_file = self._write_build_file(
            """
            COPY app.py /app/app.py
            BASE alpine
            """
        )

        with self.assertRaises(BuildFileError) as ctx:
            parse_pepito_file(build_file)

        self.assertIn("Line 2: COPY must appear after BASE.", str(ctx.exception))

    def test_copy_escaping_context_raises_user_error(self) -> None:
        build_file = self._write_build_file(
            """
            BASE alpine
            COPY ../outside.txt /app/outside.txt
            """
        )

        with self.assertRaises(BuildFileError) as ctx:
            parse_pepito_file(build_file, context_dir=self.tmp_ctx)

        self.assertIn("escapes build context", str(ctx.exception))

    def test_copy_missing_source_raises_user_error(self) -> None:
        build_file = self._write_build_file(
            """
            BASE alpine
            COPY does_not_exist.txt /app/does_not_exist.txt
            """
        )

        with self.assertRaises(BuildFileError) as ctx:
            parse_pepito_file(build_file, context_dir=self.tmp_ctx)

        self.assertIn("COPY source does not exist", str(ctx.exception))

    def test_invalid_workdir_raises_user_error(self) -> None:
        build_file = self._write_build_file(
            """
            BASE alpine
            WORKDIR relative/path
            """
        )

        with self.assertRaises(BuildFileError) as ctx:
            parse_pepito_file(build_file)

        self.assertIn("WORKDIR must be an absolute path", str(ctx.exception))

    def test_cli_main_prints_clean_error_to_stderr_and_exits_1(self) -> None:
        build_file = self._write_build_file(
            """
            BASE alpine
            UNKNOWN_DIRECTIVE foo
            """
        )

        stderr_buf = io.StringIO()
        with redirect_stderr(stderr_buf):
            exit_code = main([str(build_file), str(self.tmp_ctx)])

        self.assertEqual(exit_code, 1)
        output = stderr_buf.getvalue()
        self.assertIn("Error in build file:", output)
        self.assertIn("unknown instruction 'UNKNOWN_DIRECTIVE'", output)
        self.assertNotIn("Traceback", output)


if __name__ == "__main__":
    unittest.main(verbosity=2)
