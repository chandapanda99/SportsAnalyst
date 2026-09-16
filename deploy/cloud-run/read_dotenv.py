"""Read one value from a dotenv file without executing the file as shell code."""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def parse_value(raw: str, *, path: Path, line_number: int) -> str:
    value = raw.strip()
    if not value:
        return ""
    if value[0] in {"'", '"'}:
        quote = value[0]
        end = value.rfind(quote)
        trailing = value[end + 1 :].strip()
        if end == 0 or (trailing and not trailing.startswith("#")):
            raise ValueError(f"{path}:{line_number}: invalid quoted dotenv value")
        try:
            parsed = ast.literal_eval(value[: end + 1])
        except (SyntaxError, ValueError) as error:
            raise ValueError(f"{path}:{line_number}: invalid quoted dotenv value") from error
        if not isinstance(parsed, str):
            raise ValueError(f"{path}:{line_number}: dotenv value must be text")
        return parsed
    return re.split(r"\s+#", value, maxsplit=1)[0].rstrip()


def read_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, separator, raw_value = line.partition("=")
        key = key.strip()
        if not separator or not KEY.fullmatch(key):
            raise ValueError(f"{path}:{line_number}: invalid dotenv assignment")
        values[key] = parse_value(raw_value, path=path, line_number=line_number)
    return values


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: read_dotenv.py FILE KEY", file=sys.stderr)
        return 64
    path = Path(sys.argv[1])
    if not path.is_file():
        print(f"dotenv file not found: {path}", file=sys.stderr)
        return 66
    key = sys.argv[2]
    try:
        values = read_dotenv(path)
    except (OSError, UnicodeError, ValueError) as error:
        print(error, file=sys.stderr)
        return 65
    if key not in values:
        print(f"{key} is not defined in {path}", file=sys.stderr)
        return 67
    sys.stdout.write(values[key])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
