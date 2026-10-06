from __future__ import annotations
import difflib, hashlib, os, shutil, subprocess, sys, tempfile
from pathlib import Path
ROOT=Path(r"C:\Users\Adam\.local-ai-hub")
T06=Path(r"C:\Users\Adam\.codex\worktrees\t06-safe-commands\.local-ai-hub")
BASE=ROOT/"src"/"local_ai_hub"/"commands.py"
V7=T06/"handoff"/"T06-T09-validation-receipts-v7-root-namespace-current.patch"
V8=T06/"handoff"/"T06-T09-validation-receipts-v8-root-namespace-current.patch"

def main() -> int:
    original=BASE.read_bytes()
    with tempfile.TemporaryDirectory(prefix="t06-v8-build-") as temp:
        work=Path(temp); package=work/"src"/"local_ai_hub"
        shutil.copytree(ROOT/"src"/"local_ai_hub",package)
        applied=subprocess.run(["git","apply",str(V7)],cwd=work,capture_output=True,text=True)
        if applied.returncode: raise RuntimeError(applied.stderr or applied.stdout)
        source=package/"commands.py"; raw=source.read_bytes(); nl="\r\n" if b"\r\n" in raw else "\n"
        text=raw.decode().replace("\r\n","\n")
        old='''            tokens = [token.lower() for token in shlex.split(command, posix=(os.name != "nt"))]
            no_execution_options = {
                "-h", "--help", "--version", "-version", "-V",
                "--collect-only", "--co", "--fixtures", "--fixtures-per-test",
                "--list-tests", "--dry-run",
            }
            if any(
                token in no_execution_options
                or token.startswith(("--help=", "--version="))
                for token in tokens
            ) or any(token in {";", "&&", "||", "|", ">", "<"} for token in tokens):
                return
'''
        new='''            raw_tokens = shlex.split(command, posix=(os.name != "nt"))
            tokens = [token.lower() for token in raw_tokens]
            no_execution_options = {
                "-h", "--help", "--version", "-version", "-V",
                "--collect-only", "--co", "--fixtures", "--fixtures-per-test",
                "--list-tests", "--dry-run",
            }
            effective_raw_tokens = list(raw_tokens)
            for index, token in enumerate(raw_tokens):
                lower_token = token.lower()
                override = ""
                if lower_token in {"-o", "--override-ini"} and index + 1 < len(raw_tokens):
                    override = raw_tokens[index + 1]
                elif lower_token.startswith("--override-ini="):
                    override = token.split("=", 1)[1]
                if override.lower().startswith("addopts="):
                    effective_raw_tokens.extend(
                        shlex.split(override.split("=", 1)[1], posix=(os.name != "nt"))
                    )
            if any(token in no_execution_options for token in effective_raw_tokens) or any(
                token.lower().startswith(("--help=", "--version="))
                for token in effective_raw_tokens
            ) or any(token in {";", "&&", "||", "|", ">", "<"} for token in tokens):
                return
'''
        if old not in text: raise RuntimeError("v7 token admission block changed")
        text=text.replace(old,new,1); source.write_bytes(text.replace("\n",nl).encode())
        shutil.copy2(T06/"tests"/"test_t06_project_validation_receipts.py",work/"test_receipts.py")
        env=os.environ.copy(); env["PYTHONPATH"]=str(work/"src")
        result=subprocess.run([sys.executable,"-m","pytest","-q","-p","no:cacheprovider","--tb=short","test_receipts.py"],cwd=work,env=env,capture_output=True,text=True)
        print("pytest_exit="+str(result.returncode)); print((result.stdout+result.stderr)[-2400:])
        if result.returncode: return result.returncode
        lint=subprocess.run([sys.executable,"-m","pyflakes",str(source)],cwd=work,env=env,capture_output=True,text=True)
        print("pyflakes_commands_exit="+str(lint.returncode)); print((lint.stdout+lint.stderr)[-900:])
        if lint.returncode: return lint.returncode
        updated=source.read_bytes()
        patch="".join(difflib.unified_diff(original.decode().splitlines(True),updated.decode().splitlines(True),fromfile="a/src/local_ai_hub/commands.py",tofile="b/src/local_ai_hub/commands.py"))
        V8.write_text(patch,encoding="utf-8",newline="")
        check=work/"check"; (check/"src"/"local_ai_hub").mkdir(parents=True); shutil.copy2(BASE,check/"src"/"local_ai_hub"/"commands.py")
        checked=subprocess.run(["git","apply","--check",str(V8)],cwd=check,capture_output=True,text=True)
        print("git_apply_check_exit="+str(checked.returncode)); print("base_sha256="+hashlib.sha256(original).hexdigest()); print("result_sha256="+hashlib.sha256(updated).hexdigest()); print("patch_sha256="+hashlib.sha256(V8.read_bytes()).hexdigest())
        if checked.returncode: print(checked.stderr or checked.stdout)
        return checked.returncode

if __name__=="__main__": raise SystemExit(main())
