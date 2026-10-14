"""Keep Vercel public files identical to the FastAPI storefront source."""
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
shutil.copy2(ROOT / "static/index.html", ROOT / "public/index.html")
shutil.copytree(ROOT / "static/assets", ROOT / "public/assets", dirs_exist_ok=True)
print("Storefront and shared assets synchronized.")
