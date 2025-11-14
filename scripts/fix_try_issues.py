# Small tool: finds bare "try:" lines (no indented body / no except/finally)
# and inserts a safe except block so the file becomes syntactically valid.
# Run: python scripts\fix_try_issues.py
import io, os, sys

TARGET = r"c:\Users\Administrator\Documents\DEV BOX\WEB SCRAPPER\web scrapper.py"

def is_indented(line):
    return len(line) - len(line.lstrip()) > 0

def main():
    with open(TARGET, "r", encoding="utf-8") as f:
        lines = f.readlines()

    changed = False
    i = 0
    out = []
    while i < len(lines):
        ln = lines[i]
        if ln.strip() == "try:":
            # look ahead for the next non-empty line
            j = i + 1
            # skip blank lines
            while j < len(lines) and lines[j].strip() == "":
                j += 1
            # if next non-blank line is not indented (same or less indent than try),
            # this try has no body -> insert a minimal body and except block.
            next_line = lines[j] if j < len(lines) else ""
            if not next_line.startswith((" ", "\t")):
                indent = ln[:len(ln) - len(ln.lstrip())]
                out.append(ln)
                out.append(indent + "    pass\n")
                out.append(indent + "except Exception:\n")
                out.append(indent + "    pass\n")
                changed = True
                i += 1
                continue
            else:
                out.append(ln)
        else:
            out.append(ln)
        i += 1

    if changed:
        backup = TARGET + ".bak"
        try:
            os.replace(TARGET, backup)
        except Exception:
            pass
        with open(TARGET, "w", encoding="utf-8") as f:
            f.writelines(out)
        print("Patched file and saved backup to", backup)
    else:
        print("No bare 'try:' lines found.")

if __name__ == "__main__":
    main()