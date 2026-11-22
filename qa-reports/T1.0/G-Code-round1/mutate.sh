#!/bin/bash
# usage: mutate.sh <file> <python-replace-old> <new> <label>
cd "$(dirname "$0")/mut"
f=$1; cp "$f" "$f.bak"
../venv/Scripts/python - "$f" "$2" "$3" <<'PY'
import sys
f,o,n=sys.argv[1:]
t=open(f,encoding='utf-8',newline='').read()
assert t.count(o)==1, (f, o, t.count(o))
open(f,'w',encoding='utf-8',newline='').write(t.replace(o,n))
PY
r=$(timeout 120 ../venv/Scripts/python -W ignore -m unittest tests.qa_reference.test_reference 2>&1 | tail -1)
mv "$f.bak" "$f"
echo "$4 => $r"
