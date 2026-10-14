"""Put your GitHub username into the README, metadata, templates and links.

    python3 tools/set_github_user.py your-username
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOKEN = "YOUR-GITHUB-USERNAME"


def main():
    if len(sys.argv) != 2 or not sys.argv[1].strip():
        sys.exit(__doc__)
    user = sys.argv[1].strip()
    n = 0
    for d, dirs, files in os.walk(ROOT):
        dirs[:] = [x for x in dirs if x not in (".git", "dist", "vendor", "__pycache__")]
        for f in files:
            if f.endswith((".md", ".json", ".yml", ".yaml", ".toml", ".py")) and f != os.path.basename(__file__):
                p = os.path.join(d, f)
                s = open(p, encoding="utf-8").read()
                if TOKEN in s:
                    open(p, "w", encoding="utf-8").write(s.replace(TOKEN, user))
                    n += 1
                    print("updated", os.path.relpath(p, ROOT))
    print(f"{n} file(s) updated. The plugin identifier is now com.github.{user}.respin-zero")


if __name__ == "__main__":
    main()
