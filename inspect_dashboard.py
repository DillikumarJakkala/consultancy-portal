from pathlib import Path

for rel in ["portal_core/views.py", "portal_core/urls.py"]:
    p = Path(rel)
    if p.exists():
        print(f"=== {rel} ===")
        print(p.read_text(encoding="utf-8", errors="replace"))

tpls = list(Path(".").rglob("*dashboard*.html"))
print("=== Dashboard templates ===")
for t in tpls:
    if ".venv" not in str(t):
        print(t)
