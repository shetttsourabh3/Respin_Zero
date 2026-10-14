import json
import os

from conftest import mod

AP = mod("aiproviders")


def tools(tmp_path, personal=None):
    AP.PERSONAL_TOOLS = str(tmp_path / "ai_tools.json")
    if personal is not None:
        (tmp_path / "ai_tools.json").write_text(json.dumps({"tools": personal}))
    return {p.id: p for p in AP.detect(all_tools=True)}


def test_bundled_list_is_vendor_neutral(tmp_path):
    t = tools(tmp_path)
    assert {"claude", "codex", "llm", "ollama", "local-server"} <= set(t)


def test_personal_tool_runs_without_shell(tmp_path, stub_bin):
    stub_bin("mytool", "import sys, json, os\n"
             "data = sys.stdin.read()\n"
             "open(os.environ['OUT'], 'w').write(json.dumps({'argv': sys.argv[1:], 'cwd': os.getcwd(), 'n': len(data)}))\n"
             "print('{\"findings\": [], \"summary\": \"ok\"}')\n")
    os.environ["OUT"] = str(tmp_path / "seen.json")
    t = tools(tmp_path, [{"id": "mine", "command": ["mytool", "--x"], "model_args": ["-m", "{model}"],
                          "files": "text", "billing": "company"}, {"id": "ollama", "disabled": True}])
    assert "ollama" not in t and t["mine"].installed
    r = t["mine"].review("instructions", "data; rm -rf /", model="m1")
    seen = json.load(open(tmp_path / "seen.json"))
    assert seen["argv"] == ["--x", "-m", "m1"] and "kicad-ai-" in seen["cwd"]
    assert '"summary": "ok"' in r.text and r.model == "m1" and r.billing == "company"


def test_local_server_only_on_this_computer(tmp_path):
    p = AP.LocalServer({"id": "x", "base_url": "http://example.com:1234/v1"}, "test")
    assert not p.installed
