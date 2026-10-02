"""C/C++ tokenizer and small token-list utilities (join, match, split, params, bases)."""
from __future__ import annotations

import re

WORD = ("id", "num", "str", "chr")

class Tok:
    __slots__ = ("t", "s", "line", "end", "after", "kind")

    def __init__(self, t, s, line, end=None, after=False, kind=""):
        self.t, self.s, self.line = t, s, line
        self.end = end if end is not None else line
        self.after, self.kind = after, kind

    def __repr__(self):
        return f"{self.t}:{self.s!r}@{self.line}"


TWO_CHAR = {"::", "->", "==", "!=", "<=", ">=", "&&", "||", "+=", "-=", "*=",
            "/=", "|=", "&=", "^=", "%=", "<<", "++", "--"}
IDRE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
RAW_PREFIX = {"R", "LR", "uR", "UR", "u8R"}


def strip_block(body: str, after: bool) -> str:
    s = body[3:]
    if s.endswith("*/"):
        s = s[:-2]
    if after and s.startswith("<"):
        s = s[1:]
    lines = s.split("\n")
    if len(lines) == 1:
        return lines[0].strip()
    first, rest = lines[0], lines[1:]
    nonblank = [l for l in rest if l.strip()]
    if nonblank and all(re.match(r"^\s*\*", l) for l in nonblank):
        rest = [re.sub(r"^\s*\*[ ]?", "", l) for l in rest]
    else:
        rest = textwrap.dedent("\n".join(rest)).split("\n")
    return "\n".join([first.strip()] + rest).strip("\n")


def scan_number(text: str, i: int) -> int:
    n, j = len(text), i
    hexa = text[i:i + 2].lower() == "0x"
    while j < n:
        c = text[j]
        if c.isalnum() or c in "_.":
            j += 1
        elif c == "'" and j + 1 < n and text[j + 1].isalnum():
            j += 1
        elif c in "+-" and j > i and text[j - 1] in "eEpP" and (not hexa or text[j - 1] in "pP"):
            j += 1
        else:
            break
    return j


def tokenize(text: str):
    toks = []
    i, n, line = 0, len(text), 1
    line_start = True
    while i < n:
        c = text[i]
        if c == "\n":
            line += 1
            i += 1
            line_start = True
            continue
        if c in " \t\r\f\v":
            i += 1
            continue
        # ---- preprocessor
        if c == "#" and line_start:
            j, buf, start_line = i, [], line
            while j < n:
                ch = text[j]
                if ch == "\\" and text[j + 1:j + 2] == "\n":
                    j += 2; line += 1; buf.append(" "); continue
                if ch == "\\" and text[j + 1:j + 3] == "\r\n":
                    j += 3; line += 1; buf.append(" "); continue
                if ch == "\n":
                    break
                if ch == "/" and text[j + 1:j + 2] in ("/", "*"):
                    break
                buf.append(ch)
                j += 1
            toks.append(Tok("pp", "".join(buf).strip(), start_line))
            i = j
            continue
        line_start = False
        # ---- comments
        if c == "/" and text[i + 1:i + 2] == "/":
            j = text.find("\n", i)
            j = n if j < 0 else j
            body = text[i:j]
            m = re.match(r"//([/!])(<?)", body)
            if m and not body.startswith("////"):
                after = bool(m.group(2))
                content = body[m.end():]
                if content.startswith(" "):
                    content = content[1:]
                prev = toks[-1] if toks else None
                if (prev is not None and prev.t == "doc" and prev.kind == "line"
                        and prev.end == line - 1 and prev.after == after):
                    prev.s += "\n" + content
                    prev.end = line
                else:
                    toks.append(Tok("doc", content, line, line, after, "line"))
            i = j
            continue
        if c == "/" and text[i + 1:i + 2] == "*":
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
            body = text[i:j]
            nl = body.count("\n")
            if ((body.startswith("/**") and not body.startswith("/**/")
                 and not body.startswith("/***")) or body.startswith("/*!")):
                after = body[3:4] == "<"
                toks.append(Tok("doc", strip_block(body, after), line, line + nl, after, "block"))
            line += nl
            i = j
            continue
        # ---- identifiers / raw strings
        if c.isalpha() or c == "_":
            m = IDRE.match(text, i)
            w, j = m.group(), m.end()
            if w in RAW_PREFIX and text[j:j + 1] == '"':
                k = text.find("(", j)
                if k > 0:
                    delim = text[j + 1:k]
                    e = text.find(")" + delim + '"', k)
                    e = n if e < 0 else e + len(delim) + 2
                    toks.append(Tok("str", '"..."', line))
                    line += text[i:e].count("\n")
                    i = e
                    continue
                
            toks.append(Tok("id", w, line))
            i = j
            continue
        # ---- numbers
        if c.isdigit() or (c == "." and text[i + 1:i + 2].isdigit()):
            j = scan_number(text, i)
            toks.append(Tok("num", text[i:j], line))
            i = j
            continue
        # ---- strings / chars
        if c in "\"'":
            j = i + 1
            while j < n and text[j] != c and text[j] != "\n":
                j += 2 if text[j] == "\\" else 1
            j = min(j + 1, n)
            toks.append(Tok("str" if c == '"' else "chr", text[i:j], line))
            i = j
            continue
        # ---- punctuation
        if text.startswith("...", i):
            toks.append(Tok("p", "...", line))
            i += 3
            continue
        two = text[i:i + 2]
        if two in TWO_CHAR:
            toks.append(Tok("p", two, line))
            i += 2
            continue
        toks.append(Tok("p", c, line))
        i += 1

    return toks


# --------------------------------------------------------------------------
# token printing / helpers
# --------------------------------------------------------------------------

BIN = {"=", "==", "!=", "<=", ">=", "||", "+=", "-=", "*=", "/=", "|=", "&=", "^=",
       "%=", "<<", "?", "|", "^", "%", "/", "+", "-", ":", "->"}
UNARY_PREV = {"=", "(", ",", "{", "?", ":", "return", "<", "[", "==", "!=", "<=", ">="}


def _space(pp, p, c):
    if p.t in WORD and c.t in WORD:
        return True
    if p.s == ",":
        return True
    if p.s in BIN or c.s in BIN:
        if p.s in ("-", "+") and (pp is None or pp.s in UNARY_PREV):
            return False
        return True
    if p.s in ("*", "&", "&&", ">", ")", "]", "...") and c.t in WORD:
        return True
    if p.s == ")" and c.s == "{":
        return True
    return False


def join(toks) -> str:
    out, pp, p = [], None, None
    for c in toks:
        if p is not None and _space(pp, p, c):
            out.append(" ")
        out.append(c.s)
        pp, p = p, c
    return "".join(out)


def match(toks, i):
    """index of the bracket closing toks[i] (any of ( [ {), or None"""
    pairs = {"(": ")", "[": "]", "{": "}"}
    op = toks[i].s
    if op not in pairs:
        return None
    cl, d = pairs[op], 0
    for j in range(i, len(toks)):
        s = toks[j].s if toks[j].t == "p" else ""
        if s == op:
            d += 1
        elif s == cl:
            d -= 1
            if d == 0:
                return j
    return None


def split_top(toks, sep=","):
    """split on `sep` at nesting depth 0 (parens, brackets, braces, angles)"""
    out, cur, d, ad = [], [], 0, 0
    for k, x in enumerate(toks):
        if x.t == "p":
            if x.s in ("(", "[", "{"):
                d += 1
            elif x.s in (")", "]", "}"):
                d -= 1
            elif x.s == "<" and d == 0 and k > 0 and toks[k - 1].t == "id":
                ad += 1
            elif x.s == ">" and d == 0 and ad > 0:
                ad -= 1
            elif x.s == sep and d == 0 and ad == 0:
                out.append(cur)
                cur = []
                continue
        cur.append(x)
    out.append(cur)
    return out


def strip_attrs(toks):
    out, attrs, i, n = [], [], 0, len(toks)
    while i < n:
        x = toks[i]
        if x.s == "[" and i + 1 < n and toks[i + 1].s == "[":
            j = i + 2
            while j + 1 < n and not (toks[j].s == "]" and toks[j + 1].s == "]"):
                j += 1
            attrs.append(join(toks[i + 2:j]))
            i = j + 2
            continue
        if x.t == "id" and x.s in ("__attribute__", "__declspec", "alignas", "_Alignas") \
                and i + 1 < n and toks[i + 1].s == "(":
            j = match(toks, i + 1)
            if j is not None:
                if x.s == "__attribute__":
                    attrs.append(join(toks[i + 2:j]))
                i = j + 1
                continue
        out.append(x)
        i += 1
    return out, attrs


SPEC_FLAGS = {"static", "virtual", "inline", "constexpr", "consteval", "constinit",
              "explicit", "extern", "friend", "mutable", "thread_local", "register"}
NOT_FUNC = {"decltype", "sizeof", "alignof", "alignas", "noexcept", "requires",
            "static_assert", "defined", "typeof", "__typeof__", "offsetof",
            "__attribute__", "_Alignas", "_Static_assert"}
BUILTIN_T = {"int", "char", "short", "long", "unsigned", "signed", "float", "double",
             "bool", "void", "auto", "wchar_t", "char8_t", "char16_t", "char32_t"}
QUAL_W = {"const", "volatile", "unsigned", "signed", "struct", "class", "enum", "union",
          "typename", "long", "short", "register"}
STMT_WORDS = {"return", "goto", "using", "delete", "throw", "if", "for", "while", "case",
              "break", "continue", "else", "do", "switch", "try"}
ATTR_MACROS = {"alignas", "__attribute__", "__declspec", "_Alignas"}


def name_span(toks, end):
    """toks[end] is the last identifier of a (possibly qualified) name.
    returns (start_index, qualifier_list, name_parts)"""
    start = end
    parts = [toks[end].s]
    quals = []
    if start > 0 and toks[start - 1].s == "~":
        start -= 1
        parts.insert(0, "~")
    while start >= 2 and toks[start - 1].s == "::":
        q = start - 2
        if toks[q].s == ">":
            d = 0
            while q >= 0:
                if toks[q].s == ">":
                    d += 1
                elif toks[q].s == "<":
                    d -= 1
                if d == 0:
                    break
                q -= 1
            q -= 1
        if q < 0 or toks[q].t != "id":
            break
        quals.insert(0, toks[q].s)
        start = q
    return start, quals, parts


def parse_params(toks):
    if not toks:
        return []
    params = []
    for seg in split_top(toks, ","):
        if not seg:
            continue
        seg, _ = strip_attrs(seg)
        default = None
        for k, x in enumerate(seg):
            if x.s == "=" and x.t == "p":
                # only the first depth-0 '=' (split_top-like scan)
                d = 0
                ok = True
                for y in seg[:k]:
                    if y.s in ("(", "[", "{"):
                        d += 1
                    elif y.s in (")", "]", "}"):
                        d -= 1
                if d == 0 and ok:
                    default = join(seg[k + 1:])
                    seg = seg[:k]
                    break
        if not seg:
            continue
        if len(seg) == 1 and seg[0].s == "void" and len(toks) == 1:
            return []
        if len(seg) == 1 and seg[0].s == "...":
            params.append({"name": "", "type": "...", "default": None})
            continue
        name, arr = "", []
        h = list(seg)
        while h and h[-1].s == "]":
            d, idx = 0, len(h) - 1
            while idx >= 0:
                if h[idx].s == "]":
                    d += 1
                elif h[idx].s == "[":
                    d -= 1
                if d == 0:
                    break
                idx -= 1
            arr = h[max(idx, 0):] + arr
            h = h[:max(idx, 0)]
        # function pointer  T (*name)(args)
        fp = None
        for k in range(len(h) - 3):
            if h[k].s == "(" and h[k + 1].s in ("*", "&") and h[k + 2].t == "id" and h[k + 3].s == ")":
                fp = k + 2
                break
        if fp is not None:
            name = h[fp].s
            typ = join(h[:fp] + h[fp + 1:] + arr)
        else:
            if (len(h) >= 2 and h[-1].t == "id" and h[-1].s not in BUILTIN_T
                    and h[-2].s not in ("::", "<")
                    and not all(y.t == "id" and y.s in QUAL_W for y in h[:-1])):
                name = h[-1].s
                h = h[:-1]
            typ = join(h + arr)
        params.append({"name": name, "type": typ, "default": default})
    return params


def parse_bases(toks, kw):
    out = []
    if not toks:
        return out
    for seg in split_top(toks, ","):
        if not seg:
            continue
        acc = "private" if kw == "class" else "public"
        virt = False
        rest = []
        for x in seg:
            if x.t == "id" and x.s in ("public", "protected", "private"):
                acc = x.s
            elif x.t == "id" and x.s == "virtual":
                virt = True
            else:
                rest.append(x)
        if rest:
            b = {"name": join(rest), "access": acc}
            if virt:
                b["virtual"] = True
            out.append(b)
    return out


# --------------------------------------------------------------------------
# Doxygen comment parser
# --------------------------------------------------------------------------
