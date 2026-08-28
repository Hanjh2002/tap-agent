import sys
from pathlib import Path
from tap.tools.bash import BashTool


def test_bash_survives_invalid_bytes_without_crashing(tmp_path):
    """Byte không-decode-được KHÔNG làm crash tool (bug cp1252 gốc)."""
    tool = BashTool(project_root=tmp_path)
    # sys.executable: portable (Windows 'python.exe', Linux 'python3') — không hard-code
    payload = "import sys; sys.stdout.buffer.write(b'\\x9d\\x8f hello')"
    cmd = f'"{sys.executable}" -c "{payload}"'
    result = tool._run(tool.args_model(command=cmd))
    assert result.ok is True            # exit 0, KHÔNG crash
    assert "hello" in result.output     # phần ASCII sống sót
    assert "\ufffd" in result.output    # byte lạ -> replacement char


def test_bash_normal_ascii_output_works(tmp_path):
    """Output ASCII bình thường vẫn nguyên (portable, không phụ thuộc codepage)."""
    tool = BashTool(project_root=tmp_path)
    result = tool._run(tool.args_model(command="echo hello world"))
    assert result.ok is True
    assert "hello world" in result.output
    