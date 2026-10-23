# Troubleshooting local development checks

This guide covers common problems when running the checks in the [development guide](DEVELOPMENT.md#verification-before-a-pull-request).

## PowerShell analyzer setup fails

Setup, PR CI and release verification use the same [pinned analyzer installer](DEVELOPMENT.md#first-setup). It downloads from the official GitHub release, not PSGallery. A log naming `Get-PSRepository`, `Register-PSRepository` or `Save-Module` therefore belongs to an older installer or a different command. Check the run's source revision before changing repository registration or rerunning it.

For the current installer, keep the first download/checksum/module error and its attempt count. In a Windows checkout, reproduce the tool step without running the application:

```powershell
.\scripts\checks\install_powershell_analyzer.ps1 -Verbose
.\scripts\checks\check_powershell.ps1 -RequireAnalyzer
```

A valid cache skips the download; an incomplete module is replaced only after a new package passes validation. To investigate a cache-specific import failure, preserve the suspect version directory outside `.dev-tools\PSScriptAnalyzer`, then run those commands again to exercise installation without that cached version. Keep the cache and tool-step logs as evidence. Download failure, checksum mismatch and module import failure are different observations: retries address transient download errors, not a wrong hash or broken package. Do not change the expected hash to accept a failing download or bypass `-RequireAnalyzer`.

The CI tool-cache key includes the installer scripts, so a committed installer change creates a different key. A successful cache restore does not prove the analyzer step passed. Likewise, a Ruff failure before tool setup leaves analyzer installation untested in that run. Follow a focused repair with the complete check from the development guide.

## Bundled model metadata has an outdated source checksum

If `tests/suggestions/test_suggestion_text.py` fails on `preparation_sha256` or `tokenizer_sha256`, compare the recorded hash in the corresponding model metadata with the source file. Refactoring or formatting changes the hash even when the intended model behavior is unchanged. A model copied from another checkout can also have metadata for different source files.

Rebuild the affected model and regenerate its reports following the [model command reference](../language/bs/README.md#preparation-and-evaluation), then run `.\dev.ps1 check -Parallel` again. The general model needs the verified local CLASSLA archive; the Islamic layer uses the reviewed TSV already in the repository. Do not edit metadata hashes by hand or weaken the checksum assertions.

## Debugging parallel test failures

Run `.\dev.ps1 test -Workers 1` to reproduce a failure in a single process. For a specific module, use `.\dev.ps1 test -Workers 1 -TestPaths tests/tooling/test_dev_environment.py`. After fixing the failure, run the complete `.\dev.ps1 check -Parallel`; use sequential `.\dev.ps1 check` when diagnosing stage contention or another parallel-only failure. If pytest reports an unrecognized `-n` argument, run `.\dev.ps1 setup` to install the declared development dependencies. Do not install plugins into another environment or remove coverage/packaging to make a final check pass.

For a slow `check -Parallel`, inspect the paths printed when each stage starts. `application.log` and `infrastructure.log` include individual test names and the 30 slowest durations at completion. Their `.stderr.log` files contain process diagnostics. Read an active test log from another terminal with `Get-Content -LiteralPath '<printed-log-path>' -Tail 15 -Wait` (Ctrl+C stops the reader). Output may arrive in batches; a test name or elapsed-time status alone does not prove progress. Compare each test group with `package.log` and the final timing summary before increasing `-Workers`. The deferred installer tests and combined report are printed in the main terminal.

`-Workers 1` controls pytest workers; it does not disable the overlapping stages requested by `-Parallel`. Use plain `check` to isolate stage contention. Run only one check/package command per checkout, and keep source files unchanged until it finishes. CI uses separate jobs, rather than these local overlapping stages; see [verification modes](DEVELOPMENT.md#verification-modes).

For a CI test timeout, keep the job annotation and the last verbose test name, then inspect any thread dump in the log. The [CI diagnostic settings](DEVELOPMENT.md#final-verification-and-fast-selection) print stacks before the job deadline; the slowest-test summary appears only after the suite finishes. A progress percentage or a cancelled job without a dump cannot identify the stalled test. Reproduce coverage with `.\dev.ps1 coverage -Workers 1` before trying two workers; a passing local run does not establish the cause of a hosted-runner stall.

If different tests fail on different runs, keep both logs and look for shared worker/thread cleanup, Qt ownership, process detection, blocked sinks and machine contention before increasing timeouts. A producer test with a deliberately blocked sink must finish before the test releases that sink. Wait for the observable state or signal; an arbitrary sleep or weakened assertion does not establish the required ordering. For a skipped test, use the [conditional-test guide](DEVELOPMENT.md#conditional-tests) to identify where it can run before deciding whether its coverage is redundant.

## Restricted Windows verification sessions

A restricted agent session can run Python and collect tests while denying operations needed by the full check. Symptoms can include:

- `PermissionError: [WinError 5]` during atomic file replacement, followed by failed settings, learning, cache, or report assertions;
- connection failures to the local HTTP servers used by updater tests;
- package preparation failing when `msiexec.exe /a` returns `1601`.

These symptoms alone do not establish that the sandbox caused the failure. Preserve the failed stage logs under `dist/check-<id>/` and inspect the first underlying error. Re-run an affected test with the same checkout and `.venv`, using an authorized Windows session with the [required verification access](DEVELOPMENT.md#verification-before-a-pull-request). An agent should request the needed execution access through its tool's permission mechanism; a normal PowerShell session can also run the repository commands.

If the focused test passes, repeat the complete `.\dev.ps1 check -Parallel` in that session. Record its exit code, stage results, timings, and execution context. Investigate any remaining failures; a focused pass does not establish that every failure was environmental. A pass outside the sandbox does not prove that restricted execution now works.

Do not change application persistence, weaken assertions, skip installer tests, disable Windows protections, or remove temporary directories merely because these symptoms appear. Use the specific diagnostics below when access failures persist. If the required execution access is unavailable, report the blocked checks and their errors without claiming successful verification.

## Pytest cannot access `pytest-of-<username>`

If many otherwise unrelated tests fail during setup with `PermissionError: [WinError 5] Access is denied` for a path such as `%LOCALAPPDATA%\Temp\pytest-of-<username>`, the test cases are not necessarily failing. Pytest cannot create their temporary directories.

This can happen when tests are run under both a sandboxed development tool and the normal Windows account. The sandbox may create pytest's shared temporary directory with permissions that exclude the normal account. Confirm the owner and access rules from PowerShell:

```powershell
$pytestTemp = Join-Path $env:LOCALAPPDATA "Temp\pytest-of-$env:USERNAME"
Get-Acl -LiteralPath $pytestTemp | Format-List Owner, AccessToString
```

After all pytest processes have stopped, remove only that generated pytest directory from an elevated PowerShell window:

```powershell
$pytestTemp = Join-Path $env:LOCALAPPDATA "Temp\pytest-of-$env:USERNAME"
Remove-Item -LiteralPath $pytestTemp -Recurse -Force
```

Run `.\dev.ps1 check -Parallel` again from a normal PowerShell window. Pytest recreates the directory with permissions for the account running the check. The directory contains test scratch data, not Pogled Assist settings or user data. Do not remove the parent `%LOCALAPPDATA%\Temp` directory.

## Smart App Control blocks generated test executables

The Windows installer tests compile temporary, unsigned `PogledAssist.exe` fixtures, and the package check builds an unsigned local application. Smart App Control can block these development executables because they have neither a trusted code-signing certificate nor an established reputation. Failures may then appear under `tests/release/test_windows_installer.py` or during a package smoke test even though compilation succeeded.

Check the Windows Code Integrity log before treating this as an installer regression:

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

Events `3033` and `3077` naming generated `PogledAssist.exe` files can support this diagnosis. Record the outcome of any machine-level workaround with the specific change and verification run, not as a lasting claim that `check` passes. Turning Smart App Control off reduces a Windows protection layer. Review [Microsoft's Smart App Control guidance](https://support.microsoft.com/windows/security/threat-malware-protection/smart-app-control-frequently-asked-questions) before changing that system-wide setting.

## Installer tests report `Get-CimInstance: Access denied`

The installer deliberately stops if it cannot verify that the source app is closed. The pytest installer harness supplies deterministic process records, so its safety and rollback tests can run where CIM access is restricted. A direct installer run still requires Windows process inspection; report an access-denied failure separately from Smart App Control or a package regression.

## Packaging tests for unsupported Python versions

`test_package_rejects_newer_python_before_using_output_directory` runs on the supported 64-bit Python 3.10 environment. It supplies a fake interpreter probe that reports Python 3.12 and checks that packaging rejects it before changing the output directory. No newer Python installation is needed for this test.
