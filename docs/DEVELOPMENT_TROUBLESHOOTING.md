# Troubleshooting local development checks

This guide covers common problems when running the checks in the
[development guide](DEVELOPMENT.md#verification-before-a-pull-request).

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

## One expected skip with Python 3.10

On the supported 64-bit Python 3.10 release environment, pytest skips
`test_package_rejects_newer_python_before_using_output_directory`. That test
only applies when the active interpreter is newer than Python 3.10. A single
skip for this reason is expected and does not make `.\dev.ps1 check` fail.
