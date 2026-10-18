"""Convert a retail World of Warcraft addon so it loads on Classic clients."""

import re
import shutil
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from . import apidb

SHIM_TEMPLATE = (Path(__file__).parent / "shim.lua").read_text(encoding="utf-8")
SHIM_FILENAME = "ClassicCompat.lua"
LIB_DIR_NAMES = {"libs", "lib", "libraries", "embeds", "externals"}
EVENT_METHODS = ("RegisterEvent", "RegisterUnitEvent", "UnregisterEvent")


def _parse_shim(src):
    """Return ({namespace: {fill names}}, {global names}) declared in shim.lua."""
    namespaces, current, indent = {}, None, ""
    for line in src.splitlines():
        m = re.match(r'(\s*)namespace\("(\w+)"', line)
        if m:
            indent = m.group(1)
            current = namespaces.setdefault(m.group(2), set())
            continue
        if current is None:
            continue
        if line == indent + "})":
            current = None
        else:
            m = re.match(re.escape(indent) + r"\t(\w+) = ", line)
            if m:
                current.add(m.group(1))
    globals_ = set(re.findall(r'^\s*global\("(\w+)"', src, re.M))
    return namespaces, globals_


SHIM_NAMESPACES, SHIM_GLOBALS = _parse_shim(SHIM_TEMPLATE)
# Source name -> key in the shim table.
REWRITE_TARGETS = {name: name for name in SHIM_NAMESPACES}
REWRITE_TARGETS.update({name: name for name in SHIM_GLOBALS})
REWRITE_TARGETS["Enum.TooltipDataType"] = "TooltipDataType"


# --------------------------------------------------------------------------
# Lua lexing: just enough to tell code apart from strings and comments.
# --------------------------------------------------------------------------

_LONG_OPEN = re.compile(r"\[(=*)\[")


def lua_segments(src):
    """Split Lua source into (kind, text) pieces; kind is code/string/comment."""
    out, i, n, start = [], 0, len(src), 0

    def flush(upto):
        if upto > start:
            out.append(("code", src[start:upto]))

    while i < n:
        c = src[i]
        if c == "-" and src.startswith("--", i):
            flush(i)
            m = _LONG_OPEN.match(src, i + 2)
            if m:
                close = "]" + m.group(1) + "]"
                end = src.find(close, m.end())
                end = n if end < 0 else end + len(close)
            else:
                end = src.find("\n", i)
                end = n if end < 0 else end
            out.append(("comment", src[i:end]))
            i = start = end
        elif c in "\"'":
            flush(i)
            j = i + 1
            while j < n and src[j] != c and src[j] != "\n":
                j += 2 if src[j] == "\\" else 1
            end = min(j + 1, n)
            out.append(("string", src[i:end]))
            i = start = end
        elif c == "[" and _LONG_OPEN.match(src, i):
            m = _LONG_OPEN.match(src, i)
            flush(i)
            close = "]" + m.group(1) + "]"
            end = src.find(close, m.end())
            end = n if end < 0 else end + len(close)
            out.append(("string", src[i:end]))
            i = start = end
        else:
            i += 1
    flush(n)
    return out


def mask_lua(src):
    """Same length as src; comments become spaces, strings become 'S'.

    Newlines are kept so offsets and line numbers line up with the original.
    """
    parts = []
    for kind, text in lua_segments(src):
        if kind == "code":
            parts.append(text)
        else:
            fill = " " if kind == "comment" else "S"
            parts.append(re.sub(r"[^\n]", fill, text))
    return "".join(parts)


def string_literals(src):
    """Yield (offset, value) for simple quoted string literals."""
    pos = 0
    for kind, text in lua_segments(src):
        if kind == "string" and text[:1] in "\"'":
            yield pos, text[1:-1]
        pos += len(text)


def line_of(text, offset):
    return text.count("\n", 0, offset) + 1


def apply_edits(src, edits):
    for start, end, repl in sorted(edits, reverse=True):
        src = src[:start] + repl + src[end:]
    return src


# --------------------------------------------------------------------------
# Lua rewriting
# --------------------------------------------------------------------------

_LOCAL_STMT = re.compile(r"^[ \t]*local[ \t]+([\w \t,]+?)[ \t]*=[ \t]*([\w \t.,]+?)[ \t;]*$", re.M)


def _name_pattern(name):
    return re.compile(r"(?<![\w.:])" + re.escape(name) + r"(?![\w])")


def _shadowed_names(masked, targets):
    """Targets the file declares as its own locals/params (so must not touch).

    `local X = X` and `local X = _G.X` alias the global rather than shadow
    it; those get their right-hand side rewritten instead. Any other
    declaration means we leave that name alone everywhere in the file.
    """
    params = [re.findall(r"\w+", m.group(1)) for m in re.finditer(r"\bfunction\b[^(\n]*\(([^)]*)\)", masked)]
    loops = [re.findall(r"\w+", m.group(1)) for m in re.finditer(r"\bfor\s+([\w\s,]+?)\s+in\b", masked)]
    aliases = []
    for m in _LOCAL_STMT.finditer(masked):
        names = [s.strip() for s in m.group(1).split(",")]
        exprs = [s.strip() for s in m.group(2).split(",")]
        aliases += [n for n, e in zip(names, exprs) if e in (n, "_G." + n)]

    shadow = set()
    for name in targets:
        if "." in name:
            continue
        decls = len(re.findall(r"\blocal\s+(?:function\s+)?(?:\w+\s*,\s*)*" + re.escape(name) + r"\b", masked))
        decls += sum(name in p for p in params) + sum(name in l for l in loops)
        if decls > aliases.count(name):
            shadow.add(name)
    return shadow


def rewrite_api_names(src, shim_global, skip=()):
    """Point shimmed API names at the addon's private shim table."""
    masked = mask_lua(src)
    shadow = _shadowed_names(masked, REWRITE_TARGETS) | set(skip)
    edits, used = [], set()
    for name, key in REWRITE_TARGETS.items():
        repl = f"{shim_global}.{key}"
        patterns = [re.compile(r"(?<![\w.:])_G\." + re.escape(name) + r"(?![\w])")]
        # `_G.X` always means the global, even where the file has a local X.
        if name not in shadow:
            patterns.append(_name_pattern(name))
        for pat in patterns:
            for m in pat.finditer(masked):
                before = masked[max(0, m.start() - 200):m.start()]
                after = masked[m.end():m.end() + 10]
                # Left side of `local X = ...` / `local function X`.
                if re.search(r"\blocal\s+(?:function\s+)?(?:\w+\s*,\s*)*$", before):
                    continue
                # Table constructor key: `{ X = 1 }`.
                if re.match(r"\s*=(?!=)", after) and re.search(r"[{,;]\s*$", before):
                    continue
                edits.append((m.start(), m.end(), repl))
                used.add(name)
    return apply_edits(src, edits), used, shadow & set(REWRITE_TARGETS)


_EVENT_CALL = re.compile(
    r"(?<![\w.:])([A-Za-z_]\w*(?:\s*\.\s*[A-Za-z_]\w*)*)\s*:\s*("
    + "|".join(EVENT_METHODS) + r")\s*\(\s*(\))?"
)


def rewrite_event_calls(src, shim_global):
    """obj:RegisterEvent(e, ...) -> SHIM.RegisterEvent(obj, e, ...)."""
    masked = mask_lua(src)
    edits = []
    for m in _EVENT_CALL.finditer(masked):
        obj, method, empty = m.group(1), m.group(2), m.group(3)
        # Skip `function Obj:RegisterEvent(...)` definitions.
        if obj.startswith(shim_global) or re.search(r"\bfunction\s*$", masked[max(0, m.start() - 20):m.start()]):
            continue
        obj = re.sub(r"\s+", "", obj)
        repl = f"{shim_global}.{method}({obj})" if empty else f"{shim_global}.{method}({obj}, "
        edits.append((m.start(), m.end(), repl))
    return apply_edits(src, edits), len(edits)


def rewrite_lua(src, shim_global):
    src, used, shadow = rewrite_api_names(src, shim_global)
    src, n_events = rewrite_event_calls(src, shim_global)
    return src, used, shadow, n_events


# --------------------------------------------------------------------------
# Scanning for things that can't be fixed automatically
# --------------------------------------------------------------------------

@dataclass
class Finding:
    file: str
    line: int
    kind: str
    name: str
    availability: str
    note: str = ""


def scan_lua(src, relpath, targets, line_offset=0):
    findings = []
    masked = mask_lua(src)
    shadow = _shadowed_names(masked, SHIM_NAMESPACES)

    def relevant(avail):
        return any(apidb.missing_in(avail, t) for t in targets)

    for table, kind in ((apidb.RETAIL_NAMESPACES, "namespace"), (apidb.RETAIL_GLOBALS, "function")):
        for name, avail in table.items():
            if not relevant(avail):
                continue
            for m in _name_pattern(name).finditer(masked):
                findings.append(Finding(relpath, line_of(masked, m.start()) + line_offset, kind, name, avail))

    # Shimmed namespaces where the addon calls a function the shim doesn't cover.
    for ns, fills in SHIM_NAMESPACES.items():
        if ns in shadow:
            continue
        for m in re.finditer(r"(?<![\w.:])" + ns + r"\.(\w+)", masked):
            fn = m.group(1)
            if fn not in fills:
                findings.append(Finding(
                    relpath, line_of(masked, m.start()) + line_offset, "unshimmed", f"{ns}.{fn}", "unknown",
                    "works only if this Classic client has it"))

    for offset, value in string_literals(src):
        avail = apidb.RETAIL_EVENTS.get(value)
        if avail and relevant(avail):
            findings.append(Finding(relpath, line_of(src, offset) + line_offset, "event", value, avail,
                                    "registration is skipped at runtime on clients without it"))
    return findings


# --------------------------------------------------------------------------
# XML
# --------------------------------------------------------------------------

_XML_SCRIPT = re.compile(r"(<(On\w+|Script)\b[^>]*?(?<!/)>)(.*?)(</\2\s*>)", re.S)


def rewrite_xml(src, shim_global, relpath, targets):
    used, n_events, findings = set(), 0, []

    def fix(m):
        nonlocal n_events
        body = m.group(3)
        cdata = re.fullmatch(r"(\s*<!\[CDATA\[)(.*)(\]\]>\s*)", body, re.S)
        head, code, tail = (cdata.group(1), cdata.group(2), cdata.group(3)) if cdata else ("", body, "")
        new, u, _shadow, n = rewrite_lua(code, shim_global)
        used.update(u)
        n_events += n
        line = line_of(src, m.start(3))
        findings.extend(scan_lua(code, relpath, targets, line_offset=line - 1))
        return m.group(1) + head + new + tail + m.group(4)

    src = _XML_SCRIPT.sub(fix, src)
    for m in re.finditer(r'\b(?:inherits|mixin)\s*=\s*"([^"]+)"', src):
        for name in re.split(r"\s*,\s*", m.group(1)):
            avail = apidb.RETAIL_XML_TEMPLATES.get(name)
            if avail and any(apidb.missing_in(avail, t) for t in targets):
                findings.append(Finding(relpath, line_of(src, m.start()), "template", name, avail))
    return src, used, n_events, findings


# --------------------------------------------------------------------------
# TOC files
# --------------------------------------------------------------------------

# "Camelot" is WoW Forever.
_FLAVOR_SUFFIX = re.compile(r"[_-](Mainline|Standard|Camelot|Classic|Vanilla|TBC|BCC|Wrath|WOTLKC|Cata|Mists)$", re.I)


def toc_base_name(path):
    return _FLAVOR_SUFFIX.sub("", Path(path).stem)


def pick_source_toc(addon_dir, name=None):
    """The modern-API TOC to convert from.

    WoW Forever (<Name>_Camelot.toc) comes first: it uses the retail API but
    is set in the original Azeroth, so its file list is the closest to what
    Classic needs. Then retail (<Name>_Mainline.toc), then <Name>.toc.
    """
    name = name or addon_dir.name
    tocs = {p.name.lower(): p for p in addon_dir.glob("*.toc")}
    for cand in (f"{name}_camelot.toc", f"{name}-camelot.toc",
                 f"{name}_mainline.toc", f"{name}-mainline.toc", f"{name}.toc"):
        if cand.lower() in tocs:
            return tocs[cand.lower()]
    for p in tocs.values():
        if toc_base_name(p).lower() == name.lower():
            return p
    return None


def addon_name_for(addon_dir):
    """Folder name if a TOC matches it, else the name the TOCs agree on.

    Downloads from GitHub often sit in a folder like `Addon-main`; WoW needs
    the folder to be named after the TOC, so the output uses the TOC's name.
    """
    if pick_source_toc(addon_dir):
        return addon_dir.name
    tocs = list(addon_dir.glob("*.toc"))
    names = {toc_base_name(p) for p in tocs}
    if len(names) <= 1:
        return names.pop() if names else None
    # e.g. Foo.toc + Foo_SomeNewFlavor.toc
    base = min(names, key=len)
    if all(n == base or n.startswith(base + "_") for n in names):
        return base
    return None


def build_flavor_toc(toc_text, interface):
    """Retarget a TOC: new Interface line, drop retail-only load gating."""
    out, notes, saw_interface = [], [], False
    for line in toc_text.splitlines():
        if re.match(r"##\s*Interface\s*:", line, re.I):
            out.append(f"## Interface: {interface}")
            saw_interface = True
            continue
        if re.match(r"##\s*AllowLoadGameType\s*:", line, re.I):
            notes.append(f"removed `{line.strip()}` (would block loading on Classic)")
            continue
        out.append(line)
    if not saw_interface:
        out.insert(0, f"## Interface: {interface}")
    return "\n".join(out) + "\n", notes


def add_shim_to_toc(toc_text):
    """Insert the shim as the first file the TOC loads."""
    lines = toc_text.splitlines()
    if any(l.strip().replace("\\", "/").endswith(SHIM_FILENAME) for l in lines):
        return toc_text
    insert_at = len(lines)
    for i, line in enumerate(lines):
        s = line.strip()
        if s and not s.startswith("#"):
            insert_at = i
            break
    else:
        # Only metadata: put it after the last header line.
        insert_at = max((i + 1 for i, l in enumerate(lines) if l.strip().startswith("#")), default=0)
    lines.insert(insert_at, SHIM_FILENAME)
    return "\n".join(lines) + "\n"


def toc_file_entries(toc_text):
    for line in toc_text.splitlines():
        s = line.strip()
        if s and not s.startswith("#"):
            yield s.split("#", 1)[0].strip()


# --------------------------------------------------------------------------
# Whole-addon conversion
# --------------------------------------------------------------------------

@dataclass
class AddonResult:
    name: str
    out_dir: Path
    tocs_written: list = field(default_factory=list)
    files_rewritten: int = 0
    event_calls: int = 0
    apis_shimmed: set = field(default_factory=set)
    shadowed: dict = field(default_factory=dict)
    findings: list = field(default_factory=list)
    notes: list = field(default_factory=list)


def _read_text(path):
    data = path.read_bytes()
    for enc in ("utf-8-sig", "latin-1"):
        try:
            return data.decode(enc), enc
        except UnicodeDecodeError:
            continue


def _copy_file(src, dst):
    # Plain read/write: shutil's native fast paths (CopyFile2 on Windows) are
    # missing under Wine, and file metadata doesn't matter for addons.
    with open(src, "rb") as fin, open(dst, "wb") as fout:
        shutil.copyfileobj(fin, fout)
    return dst


def _is_lib(rel):
    return any(part.lower() in LIB_DIR_NAMES for part in rel.parts[:-1])


def shim_global_name(addon_name):
    return "ClassicCompat_" + re.sub(r"\W", "_", addon_name)


def convert_addon(src_dir, out_dir, targets, interfaces, rewrite_libs=False):
    src_dir, out_dir = Path(src_dir), Path(out_dir)
    name = out_dir.name
    result = AddonResult(name, out_dir)
    shim_global = shim_global_name(name)

    if out_dir.exists():
        shutil.rmtree(out_dir)
    shutil.copytree(src_dir, out_dir, ignore=shutil.ignore_patterns(".*"), copy_function=_copy_file)

    for path in sorted(out_dir.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in (".lua", ".xml"):
            continue
        rel = path.relative_to(out_dir)
        relstr = rel.as_posix()
        text, enc = _read_text(path)
        lib = _is_lib(rel)
        if lib and not rewrite_libs:
            continue
        if path.suffix.lower() == ".lua":
            new, used, shadow, n_events = rewrite_lua(text, shim_global)
            result.findings.extend(scan_lua(text, relstr, targets))
            if shadow:
                result.shadowed[relstr] = sorted(shadow)
        else:
            new, used, n_events, findings = rewrite_xml(text, shim_global, relstr, targets)
            result.findings.extend(findings)
        result.apis_shimmed |= used
        result.event_calls += n_events
        if new != text:
            path.write_text(new, encoding="utf-8" if enc == "utf-8-sig" else enc, newline="")
            result.files_rewritten += 1

    (out_dir / SHIM_FILENAME).write_text(SHIM_TEMPLATE.replace("__SHIM__", shim_global), encoding="utf-8", newline="\n")

    source_toc = pick_source_toc(out_dir, name)
    if source_toc is None:
        result.notes.append("No TOC file named after the folder was found; nothing will load. "
                            "Is this the addon folder?")
        return result
    base_text, _ = _read_text(source_toc)

    # Every TOC needs the shim, since the rewritten code depends on it.
    for toc in out_dir.glob("*.toc"):
        t, enc = _read_text(toc)
        toc.write_text(add_shim_to_toc(t), encoding="utf-8", newline="\n")

    for target in targets:
        existing = [out_dir / f"{name}{a}.toc" for a in apidb.TARGET_TOC_ALIASES[target]]
        existing = [p for p in existing if p.exists()]
        if existing:
            result.notes.append(f"The addon already ships {existing[0].name} for {target}, so it already "
                                f"supports that client; kept the author's TOC (plus the shim).")
            continue
        suffix, _ = apidb.TARGETS[target]
        dest = out_dir / f"{name}{suffix}.toc"
        new_toc, notes = build_flavor_toc(add_shim_to_toc(base_text), interfaces[target])
        dest.write_text(new_toc, encoding="utf-8", newline="\n")
        result.tocs_written.append(dest.name)
        result.notes.extend(f"{dest.name}: {n}" for n in notes)

        for entry in toc_file_entries(new_toc):
            if "[Family]" in entry:
                _resolve_family_file(out_dir, entry, result)

    if re.search(r"WOW_PROJECT_ID|WOW_PROJECT_MAINLINE|IsRetail|isRetail", _all_lua(out_dir)):
        result.notes.append("The addon already checks which game flavor it runs on (WOW_PROJECT_ID "
                            "or similar). Those branches will now take the Classic path; review them.")
    return result


def _resolve_family_file(out_dir, entry, result):
    """`File_[Family].lua` loads File_Classic.lua on Classic; copy it from Mainline if absent."""
    rel = entry.replace("\\", "/")
    classic = out_dir / rel.replace("[Family]", "Classic")
    mainline = out_dir / rel.replace("[Family]", "Mainline")
    if not classic.exists() and mainline.exists():
        _copy_file(mainline, classic)
        result.notes.append(f"Copied {mainline.relative_to(out_dir)} to {classic.relative_to(out_dir)} "
                            "for the TOC's [Family] entry.")


def _all_lua(d):
    return "\n".join(_read_text(p)[0] for p in d.rglob("*.lua") if p.name != SHIM_FILENAME)


# --------------------------------------------------------------------------
# Input discovery and output packaging
# --------------------------------------------------------------------------

def find_addon_dirs(root):
    """[(folder, addon name)] for every folder holding an addon's TOC."""
    root = Path(root)
    found = []
    for d in [root, *sorted(p for p in root.rglob("*") if p.is_dir())]:
        if any(d.is_relative_to(f) for f, _ in found):
            continue
        name = addon_name_for(d)
        if name:
            found.append((d, name))
    return found


def extract_zip(zip_path, dest):
    dest = Path(dest)
    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.infolist():
            target = (dest / member.filename).resolve()
            if not target.is_relative_to(dest.resolve()):
                raise ValueError(f"Unsafe path in zip: {member.filename}")
        zf.extractall(dest)


def zip_dir(src_root, zip_path, folders):
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for folder in folders:
            for p in sorted(folder.rglob("*")):
                if p.is_file():
                    zf.write(p, p.relative_to(src_root).as_posix())


def write_report(results, targets, path):
    lines = ["# Classic conversion report", "",
             f"Targets: {', '.join(targets)}", ""]
    for r in results:
        lines += [f"## {r.name}", ""]
        lines.append(f"- TOC files written: {', '.join(r.tocs_written) or 'none'}")
        lines.append(f"- Files rewritten: {r.files_rewritten}")
        lines.append(f"- Event (un)registrations made safe: {r.event_calls}")
        lines.append(f"- Modern APIs routed through the shim: {', '.join(sorted(r.apis_shimmed)) or 'none'}")
        lines.append("")
        if r.notes:
            lines += ["### Notes", ""] + [f"- {n}" for n in r.notes] + [""]
        if r.shadowed:
            lines += ["### Not rewritten (the file defines its own local with that name)", ""]
            lines += [f"- `{f}`: {', '.join(names)}" for f, names in sorted(r.shadowed.items())] + [""]
        if r.findings:
            lines += ["### Needs manual attention", "",
                      "These use features Classic probably doesn't have. The code will error or do "
                      "nothing there unless it checks first (`if C_Foo then ... end`).", "",
                      "| File | Line | Kind | Name | Missing in | Note |", "|---|---|---|---|---|---|"]
            for f in sorted(r.findings, key=lambda f: (f.file, f.line, f.name)):
                avail = {"all": "all Classic", "vanilla": "Classic Era"}.get(f.availability, "?")
                lines.append(f"| {f.file} | {f.line} | {f.kind} | `{f.name}` | {avail} | {f.note} |")
            lines.append("")
        else:
            lines += ["No known retail-only API usage found.", ""]
    Path(path).write_text("\n".join(lines), encoding="utf-8")


class NoAddonFound(Exception):
    pass


def convert_path(src, out, targets, interfaces, rewrite_libs=False):
    """Convert every addon in `src` (folder or .zip) into `out` (folder or .zip).

    Returns (results, report path).
    """
    src, out = Path(src), Path(out)
    as_zip = out.suffix.lower() == ".zip"
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        if src.suffix.lower() == ".zip":
            extract_zip(src, tmp / "in")
            src_root = tmp / "in"
        else:
            src_root = src
        addons = find_addon_dirs(src_root)
        if not addons:
            raise NoAddonFound(f"No addon found in {src} (looked for a folder with a matching .toc file).")

        out_root = tmp / "out" if as_zip else out
        out_root.mkdir(parents=True, exist_ok=True)
        results = [convert_addon(d, out_root / name, targets, interfaces, rewrite_libs) for d, name in addons]

        report = out.with_name(out.stem + "-report.md") if as_zip else out / "CONVERSION_REPORT.md"
        write_report(results, targets, report)
        if as_zip:
            zip_dir(out_root, out, [r.out_dir for r in results])
    return results, report
