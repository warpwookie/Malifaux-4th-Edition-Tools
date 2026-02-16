"""Fix encoding in validator.py open() calls."""
f = "scripts/validator.py"
t = open(f, encoding="utf-8").read()
t = t.replace(
    "with open(REFERENCE_PATH) as f:",
    'with open(REFERENCE_PATH, encoding="utf-8") as f:'
)
t = t.replace(
    "with open(input_file) as f:",
    'with open(input_file, encoding="utf-8") as f:'
)
t = t.replace(
    'with open(args.json_report, "w") as f:',
    'with open(args.json_report, "w", encoding="utf-8") as f:'
)
open(f, "w", encoding="utf-8").write(t)
print("Fixed 3 open() calls in validator.py")
