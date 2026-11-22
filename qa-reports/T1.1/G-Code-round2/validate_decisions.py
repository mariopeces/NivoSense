"""Validate s2_decision objects against T0.4's schema (plan/t04-qa). Usage: schema.json file..."""
import json, sys
from jsonschema import Draft202012Validator, FormatChecker
v = Draft202012Validator(json.load(open(sys.argv[1], encoding="utf-8")), format_checker=FormatChecker())
bad = 0
for p in sys.argv[2:]:
    errs = list(v.iter_errors(json.load(open(p, encoding="utf-8"))))
    bad += bool(errs)
    print(("OK   " if not errs else "FAIL ") + p.replace("\\", "/").split("/")[-1], "; ".join(e.message for e in errs))
print(f"{len(sys.argv) - 2 - bad}/{len(sys.argv) - 2} valid")
