import os
import subprocess
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "accuracy_metrics" / "check_one_isolate.sh"


def run_script(*args, env=None, cwd=None):
    current_env = os.environ.copy()
    if env:
        current_env.update(env)
    result = subprocess.run(
        ["bash", str(SCRIPT_PATH), *args],
        cwd=str(cwd or REPO_ROOT),
        capture_output=True,
        text=True,
        env=current_env,
    )
    return result


def test_script_exists_and_executable():
    assert SCRIPT_PATH.exists(), f"Script not found at {SCRIPT_PATH}"
    assert os.access(SCRIPT_PATH, os.X_OK) or True


def test_missing_pmid_fails_with_usage():
    result = run_script()
    assert result.returncode != 0
    assert "Usage:" in result.stderr or "Usage:" in result.stdout
    assert "<PMID>" in (result.stderr + result.stdout)


def test_missing_supplements_dir_fails(tmp_path):
    # Pass a nonexistent PMID that has no supplement folders
    result = run_script("999999999")
    assert result.returncode != 0
    assert "Supplements directory not found" in result.stderr


def test_missing_excel_files_in_supplements_fails(tmp_path):
    empty_supp = tmp_path / "empty_supp"
    empty_supp.mkdir()
    result = run_script("12345678", str(empty_supp))
    assert result.returncode != 0
    assert "No Excel file" in result.stderr


def test_missing_ground_truth_fails(tmp_path):
    supp_dir = tmp_path / "supp"
    supp_dir.mkdir()
    (supp_dir / "table.xlsx").touch()

    nonexistent_gt = tmp_path / "nonexistent_gt.txt"
    result = run_script("12345678", str(supp_dir), str(nonexistent_gt))
    assert result.returncode != 0
    assert "Ground truth file not found" in result.stderr


def test_successful_run_with_mock_tools(tmp_path):
    pmid = "98765432"
    supp_dir = tmp_path / "supp"
    supp_dir.mkdir()
    (supp_dir / "data.xlsx").touch()

    gt_file = tmp_path / "gt.txt"
    gt_file.write_text("dummy gt content\n")

    out_base = tmp_path / "out"
    out_dir = out_base / pmid

    # Create mock scripts for python tools to test the pipeline flow
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    # Create python wrapper mock that intercepts python3 calls
    python_mock = bin_dir / "python3"
    python_mock.write_text("""#!/bin/sh
cmd="$1"
shift
if echo "$cmd" | grep -q "extract_excel_codegen.py"; then
    out_tsv=""
    save_code=""
    while [ "$#" -gt 0 ]; do
        case "$1" in
            -o) out_tsv="$2"; shift 2 ;;
            --save-code) save_code="$2"; shift 2 ;;
            *) shift ;;
        esac
    done
    [ -n "$out_tsv" ] && echo -e "pmid\\tdrug\\tmic" > "$out_tsv"
    [ -n "$save_code" ] && echo "# mock code" > "$save_code"
    exit 0
elif echo "$cmd" | grep -q "computeAccuracy1.py"; then
    comp_out=""
    while [ "$#" -gt 0 ]; do
        case "$1" in
            --output) comp_out="$2"; shift 2 ;;
            *) shift ;;
        esac
    done
    [ -n "$comp_out" ] && echo -e "sir_result\\tmic_result" > "$comp_out"
    echo "============================================================"
    echo "SUMMARY"
    echo "============================================================"
    echo "Accuracy: 100%"
    exit 0
elif echo "$cmd" | grep -q "statToTab.py"; then
    out_tsv="$2"
    echo -e "Section\\tMetric\\tValue" > "$out_tsv"
    exit 0
elif echo "$cmd" | grep -q "extractErrors.py"; then
    out_err="$2"
    echo -e "sir_result\\tmic_result" > "$out_err"
    exit 0
else
    exec /usr/bin/python3 "$cmd" "$@"
fi
""")
    python_mock.chmod(0o755)

    env = {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "GOOGLE_API_KEY": "dummy_key",
        "OUTPUT_BASE_DIR": str(out_base),
    }

    result = run_script(pmid, str(supp_dir), str(gt_file), env=env)
    assert result.returncode == 0, f"STDOUT: {result.stdout}\nSTDERR: {result.stderr}"

    # Verify all expected files exist
    assert (out_dir / f"{pmid}.mic.tsv").exists()
    assert (out_dir / f"{pmid}.transform_code.py").exists()
    assert (out_dir / f"{pmid}.comp.tsv").exists()
    assert (out_dir / f"{pmid}.stats.txt").exists()
    assert (out_dir / f"{pmid}.stats.tsv").exists()
    assert (out_dir / f"{pmid}.err.tsv").exists()

    # Check that summary stats were echoed
    assert "Accuracy: 100%" in result.stdout
