import csv
import json
import os.path
from collections import defaultdict
from dataclasses import fields, is_dataclass
from pprint import pprint
from typing import Any, Callable, List, Optional, Type


def to_uri(path: str, prefix="file://") -> str:
    if path.startswith(prefix):
        return path
    path = os.path.abspath(path)
    return f"{prefix}{path}"


def to_path(uri: str, prefix="file://") -> str:
    if uri.startswith(prefix):
        return uri[len(prefix) :]
    assert uri.startswith("/")
    return uri


def ppprint(msg: str, obj):
    print(f"{msg}:")
    pprint(obj)
    print(f"{msg}.\n\n")


def get_setbits(x):
    l = []
    i = 0
    while x:
        if x & 1 == 1:
            l += [i]
        i += 1
        x >>= 1
    return l


def annotate(text: str, annotations: list[tuple[int, int, int, str]]) -> str:
    # annotations: list [ lineno, col, len, annot]
    lines = text.splitlines()
    ann_map = defaultdict(list)

    # 收集每行的注释
    for lineno, col, tok_len, annot in annotations:
        if lineno < 0 or lineno >= len(lines):
            raise ValueError(f"Invalid line number: {lineno}")
        if col < 0 or col > len(lines[lineno]):
            raise ValueError(f"Invalid column on line {lineno}: {col}")
        if tok_len < 0 or col + tok_len > len(lines[lineno]):
            raise ValueError(f"Invalid token length on line {lineno}: {tok_len}")
        ann_map[lineno].append((col, tok_len, annot))

    output = []
    line_num_width = len(str(len(lines) - 1))

    for lineno, line in enumerate(lines):
        line_annotations = sorted(ann_map.get(lineno, []), key=lambda x: x[0])
        segments: list[tuple[str, Optional[str]]] = []
        cursor = 0

        # 拆分成 segments
        for col, tok_len, annot in line_annotations:
            if cursor < col:
                segments.append((line[cursor:col], None))
            segments.append((line[col : col + tok_len], annot))
            cursor = col + tok_len
        if cursor < len(line):
            segments.append((line[cursor:], None))

        rendered_line = ""
        rendered_annot = ""

        for text_seg, ann in segments:
            ann_str = f"^{ann}" if ann else ""
            seg_width = max(len(text_seg), len(ann_str))

            # 灰色高亮
            ann_str_gray = f"{ann_str}" if ann else ""

            rendered_line += text_seg.ljust(seg_width)
            rendered_annot += ann_str_gray.ljust(seg_width)

        # 添加行号
        prefix = f"{str(lineno).rjust(line_num_width)} | "
        output.append(prefix + rendered_line)
        if any(ann for _, ann in segments):
            output.append(
                "\x1b[90m" + " " * (len(prefix)) + rendered_annot.rstrip() + "\x1b[0m"
            )

    return "\n".join(output)


def dump_semantic_tokens_full(
    tokens, token_types, token_modifiers, textlines, print_raw=False
):
    print("dump_semantic_tokens_full")
    annots = []
    line, start = 0, 0
    for dLine, dStart, tokLen, tokType, tokModifier in [
        tokens[i : i + 5] for i in range(0, len(tokens), 5)
    ]:
        if print_raw:
            print(f"raw: ", dLine, dStart, tokLen, tokType, tokModifier)
        if dLine != 0:
            line += dLine
            start = dStart
        else:
            start += dStart
        spelling = textlines[line][start : start + tokLen]
        modifiers = get_setbits(tokModifier)
        modifiers = ",".join([token_modifiers[i] for i in modifiers])
        token_type_str = token_types[tokType]
        location = f"{line}:{start}:+{tokLen}"
        annots += [(line, start, tokLen, token_type_str)]
        print(f'  {location}: "{spelling}"')
        print(f"    {token_type_str:<12}, with {modifiers}")
    print("dump_semantic_tokens_full.\n\n")
    return annots


file_cache: dict[str, str] = {}
lines_cache: dict[str, list[str]] = {}


def readfile_whole(path: str) -> str:
    if path in file_cache:
        return file_cache[path]
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    file_cache[path] = content
    lines_cache[path] = content.splitlines()
    return content


def readfile_chunk_lc(path, start_lc, end_lc) -> str:
    readfile_whole(path)
    lines = lines_cache[path]
    start_line, start_col = start_lc
    end_line, end_col = end_lc
    chunk = []
    if start_line == end_line:
        chunk.append(lines[start_line][start_col:end_col])
        return "".join(chunk)
    chunk.append(lines[start_line][start_col:])
    chunk.extend(lines[start_line + 1 : end_line])
    chunk.append(lines[end_line][:end_col])
    return "\n".join(chunk)


def readfile_chunk_line(path, line) -> str:
    readfile_whole(path)
    lines = lines_cache[path]
    return lines[line]


def readfile_chunk_bytes(path, start_byte, end_byte) -> str:
    contents = readfile_whole(path)
    return contents[start_byte:end_byte]


def load_json(path: str):
    if os.path.exists(path):
        with open(path, "r") as fin:
            return json.load(fin)
    return None


def save_json(path: str, data) -> None:
    with open(path, "w") as fout:
        json.dump(data, fout, indent=2)


def write_dataclasses_to_csv(
    data: List[Any],
    file_path: str,
    dataclass_type: Optional[Type[Any]] = None,
    ignore_fields: Optional[List[str]] = None,
    node_filter: Optional[Callable[[Any], bool]] = None,
    delimiter: str = ",",
    quotechar: str = '"',
    quoting: int = csv.QUOTE_MINIMAL,
) -> None:
    """
    Writes a list of dataclass instances to a CSV file.

    Args:
        data (List[Any]): A list of dataclass instances. All instances
                          in the list should ideally be of the same dataclass type.
        file_path (str): The path to the output CSV file.
        dataclass_type (Optional[Type[Any]]): The dataclass type to use for
                                               determining headers. If None,
                                               it will infer from the first item in 'data'.
                                               Required if 'data' is empty.
        delimiter (str): The character used to separate fields. Defaults to ','.
        quotechar (str): The character used to quote fields containing special characters.
                         Defaults to '"'.
        quoting (int): The quoting style for fields. Defaults to csv.QUOTE_MINIMAL.

    Raises:
        ValueError: If `data` is empty and `dataclass_type` is not provided,
                    or if items in `data` are not dataclass instances.
        IOError: If there's an issue writing to the file.
    """
    if not data and dataclass_type is None:
        raise ValueError(
            "Cannot determine CSV headers: 'data' list is empty and 'dataclass_type' is not provided."
        )

    # Determine the dataclass type if not explicitly provided
    if dataclass_type is None:
        # Find the first actual dataclass instance in the list
        for item in data:
            if is_dataclass(item):
                dataclass_type = type(item)
                break
        if dataclass_type is None and data:  # If data is not empty but no dataclass
            raise ValueError(
                "No dataclass instances found in the provided 'data' list."
            )
        elif (
            dataclass_type is None and not data
        ):  # Should be caught by the first ValueError
            raise ValueError("Cannot determine dataclass type from empty 'data' list.")
    assert dataclass_type is not None

    if not is_dataclass(dataclass_type):
        raise ValueError(
            f"Provided dataclass_type '{dataclass_type.__name__}' is not a dataclass."
        )

    # Get field names (headers) from the dataclass
    field_names = [
        f.name for f in fields(dataclass_type) if f.name not in (ignore_fields or [])
    ]

    try:
        with open(file_path, "w", newline="", encoding="utf-8") as csvfile:
            writer = csv.writer(
                csvfile, delimiter=delimiter, quotechar=quotechar, quoting=quoting
            )

            # Write the header row
            writer.writerow(field_names)

            # Write data rows
            for item in data:
                if not is_dataclass(item):
                    print(f"Warning: Skipping non-dataclass item: {item}")
                    continue
                # Ensure the item is of the expected dataclass type or compatible
                if not isinstance(item, dataclass_type):
                    print(
                        f"Warning: Item {item} is not of expected type {dataclass_type.__name__}. Attempting to write anyway, but order might be off."
                    )
                    # If types are different, we might need to re-derive field_names for this specific item
                    # For simplicity, we'll stick to the initial field_names.
                    # A more robust solution might involve validating fields or dynamically getting fields for each item.
                if node_filter is not None and not node_filter(item):
                    continue
                row_values = []
                for field_name in field_names:
                    value = getattr(item, field_name, None)
                    # Handle list/tuple fields by converting them to a string representation
                    if isinstance(value, (list, tuple)):
                        row_values.append(
                            json.dumps(value)
                        )  # Use JSON to serialize lists/tuples
                    else:
                        row_values.append(str(value))
                writer.writerow(row_values)
        print(f"Successfully wrote data to {file_path}")
    except IOError as e:
        print(f"Error writing to file {file_path}: {e}")
        raise  # Re-raise the exception after printing


def normalize_semtoks_linecol(toks: list[int]) -> list[list[int]]:
    # line, col, tok_len, kind, token
    normtoks = []
    line, start = 0, 0
    for dLine, dStart, tokLen, tokType, tokModifier in [
        toks[i : i + 5] for i in range(0, len(toks), 5)
    ]:
        if dLine != 0:
            line += dLine
            start = dStart
        else:
            start += dStart
        normtoks.append([line, start, tokLen, tokType, tokModifier])
    return normtoks


def filter_semtoks_range(
    normtoks: list[list[int]], start: tuple[int, int], end: tuple[int, int]
) -> list[list[int]]:
    filtered = []
    for line, start_col, tok_len, tok_type, tok_modifier in normtoks:
        if (line, start_col) < start or (line, start_col + tok_len) > end:
            continue
        filtered.append([line, start_col, tok_len, tok_type, tok_modifier])
    return filtered


def leading_spaces(s: str) -> int:
    """Returns the number of leading spaces in a string."""
    return len(s) - len(s.lstrip(" "))
