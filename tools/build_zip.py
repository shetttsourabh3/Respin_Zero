"""Build the Plugin and Content Manager zip in dist/ and print the sha256 and sizes for the repository entry."""
import hashlib
import json
import os
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIP_DIRS = {"__pycache__", "datasheets", ".cache"}


def main():
    meta = json.load(open(os.path.join(ROOT, "metadata.json")))
    ver = meta["versions"][0]["version"]
    os.makedirs(os.path.join(ROOT, "dist"), exist_ok=True)
    out = os.path.join(ROOT, "dist", f"respin_zero-{ver}.zip")
    size = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(os.path.join(ROOT, "metadata.json"), "metadata.json")
        for top in ("plugins", "resources"):
            for d, dirs, files in os.walk(os.path.join(ROOT, top)):
                dirs[:] = [x for x in dirs if x not in SKIP_DIRS]
                for f in files:
                    if f.endswith((".pyc", ".zip")):
                        continue
                    p = os.path.join(d, f)
                    z.write(p, os.path.relpath(p, ROOT))
                    size += os.path.getsize(p)
    sha = hashlib.sha256(open(out, "rb").read()).hexdigest()
    print(f"{out}\n  download_size {os.path.getsize(out)}\n  install_size  {size}\n  download_sha256 {sha}")


if __name__ == "__main__":
    main()
