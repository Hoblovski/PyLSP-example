from pprint import pprint
from collections import defaultdict
import os.path


def to_uri(path: str, prefix="file://") -> str:
    if path.startswith(prefix):
        return path
    path = os.path.abspath(path)
    return f"{prefix}{path}"


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
    lines = text.splitlines()
    ann_map = defaultdict(list)

    # 收集每行的注释
    for line, col, tok_len, ann in annotations:
        if line < 0 or line >= len(lines):
            raise ValueError(f"Invalid line number: {line}")
        if col < 0 or col > len(lines[line]):
            raise ValueError(f"Invalid column on line {line}: {col}")
        if tok_len < 0 or col + tok_len > len(lines[line]):
            raise ValueError(f"Invalid token length on line {line}: {tok_len}")
        ann_map[line].append((col, tok_len, ann))

    output = []
    line_num_width = len(str(len(lines) - 1))

    for lineno, line in enumerate(lines):
        line_annotations = sorted(ann_map.get(lineno, []), key=lambda x: x[0])
        segments = []
        cursor = 0

        # 拆分成 segments
        for col, tok_len, ann in line_annotations:
            if cursor < col:
                segments.append((line[cursor:col], None))
            segments.append((line[col : col + tok_len], ann))
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
