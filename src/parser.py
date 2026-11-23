from __future__ import annotations

import json
import shlex
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

StepKind = Literal["RUN", "COPY"]


@dataclass
class BuildStep:
    """Represents a build step that creates or modifies filesystem entries."""

    kind: StepKind
    line_number: int
    raw: str
    command: list[str] | None = None
    src: Path | None = None
    dest: str | None = None


@dataclass
class ImageConfig:
    """Runtime metadata stored in the resulting image manifest."""

    env: dict[str, str] = field(default_factory=dict)
    workdir: str = "/"
    memory: str | None = None
    hostname: str | None = None
    cmd: list[str] | None = None


@dataclass
class ParsedBuildPlan:
    """Validated build plan produced from a pepito build file."""

    base: str
    context_dir: Path
    steps: list[BuildStep] = field(default_factory=list)
    config: ImageConfig = field(default_factory=ImageConfig)


class BuildFileError(Exception):
    """User-facing error raised when a pepito build file is invalid or unreadable."""


def _parse_command(raw_arg: str, line_no: int, field_name: str) -> list[str]:
    """
    Parse either a JSON string list (e.g. ["/bin/sh", "-c", "echo hi"])
    or a shell-style command string (e.g. /bin/sh -c "echo hi").
    """
    text = raw_arg.strip()
    if not text:
        raise BuildFileError(f"Line {line_no}: {field_name} cannot be empty.")

    if text.startswith("["):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise BuildFileError(
                f"Line {line_no}: invalid JSON array in {field_name} ({exc.msg})."
            ) from exc

        if (
            not isinstance(parsed, list)
            or not parsed
            or not all(isinstance(item, str) and item for item in parsed)
        ):
            raise BuildFileError(
                f"Line {line_no}: {field_name} JSON array must be a non-empty list of non-empty strings."
            )
        return parsed

    try:
        tokens = shlex.split(text)
    except ValueError as exc:
        raise BuildFileError(
            f"Line {line_no}: syntax error in {field_name} ({exc})."
        ) from exc

    if not tokens:
        raise BuildFileError(f"Line {line_no}: {field_name} cannot be empty.")
    return tokens


def parse_pepito_file(
    file_path: str | Path,
    context_dir: str | Path | None = None,
) -> ParsedBuildPlan:
    """Parse and validate a pepito build file into a ParsedBuildPlan."""
    build_file = Path(file_path).resolve()
    if not build_file.exists():
        raise BuildFileError(f"Build file not found: {build_file}")
    if not build_file.is_file():
        raise BuildFileError(f"Build path is not a regular file: {build_file}")

    project_dir = Path(context_dir).resolve() if context_dir else build_file.parent
    if not project_dir.exists() or not project_dir.is_dir():
        raise BuildFileError(f"Build context directory not found: {project_dir}")

    try:
        raw_lines = build_file.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise BuildFileError(
            f"Unable to read build file '{build_file}': {exc.strerror or exc}"
        ) from exc

    base: str | None = None
    steps: list[BuildStep] = []
    config = ImageConfig()

    for line_no, raw_line in enumerate(raw_lines, start=1):
        stripped = raw_line.strip()

        # Skip empty lines and comments
        if not stripped or stripped.startswith("#"):
            continue

        parts = stripped.split(maxsplit=1)
        instruction = parts[0].upper()
        arg = parts[1].strip() if len(parts) > 1 else ""

        if instruction in ("BASE", "FROM"):
            if base is not None:
                raise BuildFileError(
                    f"Line {line_no}: {instruction} can only be specified once."
                )
            if not arg:
                raise BuildFileError(
                    f"Line {line_no}: {instruction} requires a base name (e.g., alpine)."
                )
            base = arg

        elif instruction == "RUN":
            if base is None:
                raise BuildFileError(f"Line {line_no}: RUN must appear after BASE.")
            cmd_tokens = _parse_command(arg, line_no, "RUN")
            steps.append(
                BuildStep(
                    kind="RUN",
                    line_number=line_no,
                    raw=stripped,
                    command=cmd_tokens,
                )
            )

        elif instruction == "COPY":
            if base is None:
                raise BuildFileError(f"Line {line_no}: COPY must appear after BASE.")
            try:
                copy_args = shlex.split(arg)
            except ValueError as exc:
                raise BuildFileError(
                    f"Line {line_no}: invalid COPY arguments ({exc})."
                ) from exc

            if len(copy_args) != 2:
                raise BuildFileError(
                    f"Line {line_no}: COPY expects exactly <source> <destination> (got {len(copy_args)})."
                )

            src_raw, dest_path = copy_args
            src_path = (project_dir / src_raw).resolve()

            # Prevent escaping the project build context directory
            try:
                src_path.relative_to(project_dir)
            except ValueError as exc:
                raise BuildFileError(
                    f"Line {line_no}: COPY source '{src_raw}' escapes build context '{project_dir}'."
                ) from exc

            if not src_path.exists():
                raise BuildFileError(
                    f"Line {line_no}: COPY source does not exist: {src_path}"
                )

            if not dest_path.startswith("/"):
                raise BuildFileError(
                    f"Line {line_no}: COPY destination must be an absolute path (got '{dest_path}')."
                )

            steps.append(
                BuildStep(
                    kind="COPY",
                    line_number=line_no,
                    raw=stripped,
                    src=src_path,
                    dest=dest_path,
                )
            )

        elif instruction == "ENV":
            if "=" not in arg:
                raise BuildFileError(f"Line {line_no}: ENV expects KEY=VALUE format.")
            key, val = arg.split("=", maxsplit=1)
            key = key.strip()
            if not key:
                raise BuildFileError(
                    f"Line {line_no}: ENV variable name cannot be empty."
                )
            val = val.strip()
            if len(val) >= 2 and val[0] == val[-1] and val[0] in ('"', "'"):
                val = val[1:-1]
            config.env[key] = val

        elif instruction == "WORKDIR":
            if not arg or not arg.startswith("/"):
                raise BuildFileError(
                    f"Line {line_no}: WORKDIR must be an absolute path (e.g., /app)."
                )
            config.workdir = arg

        elif instruction == "MEMORY":
            if not arg:
                raise BuildFileError(
                    f"Line {line_no}: MEMORY requires a limit value (e.g., 256M)."
                )
            config.memory = arg

        elif instruction == "HOSTNAME":
            if not arg or any(ch.isspace() for ch in arg):
                raise BuildFileError(
                    f"Line {line_no}: HOSTNAME must be a single non-empty token."
                )
            config.hostname = arg

        elif instruction == "CMD":
            config.cmd = _parse_command(arg, line_no, "CMD")

        else:
            raise BuildFileError(
                f"Line {line_no}: unknown instruction '{instruction}'."
            )

    if base is None:
        raise BuildFileError("Missing required BASE instruction in build file.")

    return ParsedBuildPlan(
        base=base,
        context_dir=project_dir,
        steps=steps,
        config=config,
    )


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if not args or len(args) > 2:
        print(
            "Usage: python3 parser.py <path-to-pepito-file> [context-dir]",
            file=sys.stderr,
        )
        return 2

    file_arg = args[0]
    context_arg = args[1] if len(args) == 2 else None

    try:
        plan = parse_pepito_file(file_arg, context_arg)
    except BuildFileError as err:
        # Clean, user-facing error output without internal stack traces
        print(f"Error in build file: {err}", file=sys.stderr)
        return 1

    print(f"Base: {plan.base}")
    print(f"Context: {plan.context_dir}")
    print(f"Config: {plan.config}")
    print(f"Steps ({len(plan.steps)}):")
    for idx, step in enumerate(plan.steps, start=1):
        print(f"  [{idx}] ({step.kind} @ line {step.line_number}) {step.raw}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
