# Troubleshooting local development checks

This guide covers common problems when running the checks in the
[development guide](DEVELOPMENT.md#verification-before-a-pull-request).

## Bundled model metadata has an outdated source checksum

If `tests/suggestions/test_suggestion_text.py` fails on `preparation_sha256` or
`tokenizer_sha256`, compare the recorded hash in the corresponding model metadata
with the source file. Refactoring or formatting changes the hash even when the
intended model behavior is unchanged. A model copied from another checkout can
also have metadata for different source files.

Rebuild the affected model and regenerate its reports following the
[model command reference](DEVELOPMENT.md#command-reference), then
run `.\dev.ps1 check` again. The general model needs the verified local CLASSLA
archive; the Islamic layer uses the reviewed TSV already in the repository.
Do not edit metadata hashes by hand or weaken the checksum assertions.

## Debugging parallel test failures

Run `.\dev.ps1 test -Workers 1` to reproduce a failure in a single process.
For a specific module, use `.\dev.ps1 test -Workers 1 -TestPaths tests/tooling/test_dev_environment.py`.
The final `.\dev.ps1 check -Workers 1` still performs the complete verification.
If pytest reports an unrecognized `-n` argument, run `.\dev.ps1 setup` to install
the declared development dependencies. Do not install plugins into another
environment or remove coverage/packaging to make a final check pass.

## Pytest cannot access `pytest-of-<username>`

If many otherwise unrelated tests fail during setup with `PermissionError:
[WinError 5] Access is denied` for a path such as
`%LOCALAPPDATA%\Temp\pytest-of-<username>`, the test cases are not necessarily
failing. Pytest cannot create their temporary directories.

This can happen when tests are run under both a sandboxed development tool and
the normal Windows account. The sandbox may create pytest's shared temporary
directory with permissions that exclude the normal account. Confirm the owner
and access rules from PowerShell:

```powershell
$pytestTemp = Join-Path $env:LOCALAPPDATA "Temp\pytest-of-$env:USERNAME"
Get-Acl -LiteralPath $pytestTemp | Format-List Owner, AccessToString
```

After all pytest processes have stopped, remove only that generated pytest
directory from an elevated PowerShell window:

```powershell
$pytestTemp = Join-Path $env:LOCALAPPDATA "Temp\pytest-of-$env:USERNAME"
Remove-Item -LiteralPath $pytestTemp -Recurse -Force
```

Run `.\dev.ps1 check` again from a normal PowerShell window. Pytest recreates
the directory with permissions for the account running the check. The directory
contains test scratch data, not Pogled Assist settings or user data. Do not
remove the parent `%LOCALAPPDATA%\Temp` directory.

## Smart App Control blocks generated test executables

The Windows installer tests compile temporary, unsigned `PogledAssist.exe`
fixtures, and the package check builds an unsigned local application. Smart App
Control can block these development executables because they have neither a
trusted code-signing certificate nor an established reputation. Failures may
then appear under `tests/release/test_windows_installer.py` or during a package smoke
test even though compilation succeeded.

Check the Windows Code Integrity log before treating this as an installer
regression:

```powershell
Get-WinEvent `
    -LogName "Microsoft-Windows-CodeIntegrity/Operational" `
    -MaxEvents 100 |
    Where-Object {
        $_.Id -in 3033, 3077 -and
        $_.Message -match "PogledAssist|pytest|check-temp"
    } |
    Select-Object TimeCreated, Id, Message
```

Events `3033` and `3077` naming generated `PogledAssist.exe` files can support
this diagnosis. Record the outcome of any machine-level workaround with the
specific change and verification run, not as a lasting claim that `check` passes.
Turning Smart App Control off reduces a Windows protection layer. Review
[Microsoft's Smart App Control guidance](https://support.microsoft.com/windows/security/threat-malware-protection/smart-app-control-frequently-asked-questions)
before changing that system-wide setting.

## Installer tests report `Get-CimInstance: Access denied`

The installer deliberately stops if it cannot verify that the source app is
closed. The pytest installer harness supplies deterministic process records, so
its safety and rollback tests can run where CIM access is restricted. A direct
installer run still requires Windows process inspection; report an access-denied
failure separately from Smart App Control or a package regression.

## Packaging tests for unsupported Python versions

`test_package_rejects_newer_python_before_using_output_directory` runs on the
supported 64-bit Python 3.10 environment. It supplies a fake interpreter probe
that reports Python 3.12 and checks that packaging rejects it before changing
the output directory. No newer Python installation is needed for this test.
