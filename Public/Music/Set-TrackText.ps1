function Set-TrackText {
    <#
    .SYNOPSIS
        Safely patches only Situation, Description, Measurement and Note.
    .DESCRIPTION
        Dry-run by default; -Apply is required to write. PatchPath is a UTF-8
        JSON array of records:
          {"path":"C:\\Music\\track.mp3",
           "expected_comment_sha256":"<64 hex characters>",
           "fields":{"Situation":"New scene","Note":null}}

        The expected hash is SHA256 of the exact raw comment encoded as UTF-8,
        without trimming, newline normalization or BOM. Every record requires
        it, including dry runs. Omitted fields are unchanged. Null or empty
        strings remove Description, Measurement or Note; Situation cannot be
        cleared. Values must be single paragraphs without "| Label:" section
        injection. Literal "|" inside prose or titles is allowed.
        Source and well-formed unknown sections are preserved verbatim.

        Measurement used to be called Evidence. Writing Measurement into a
        comment that still has an "Evidence:" section replaces that section
        in place under the new label; clearing Measurement removes either.

        Supports exactly one TXXX:comment or one COMM comment in ID3v2.3/2.4.
        Ambiguous/missing comments, multi-value text, malformed sections,
        unsupported tag flags and unrepresentable text encodings are refused.
        Original frame type, encoding, COMM language/description, other raw
        frames, ID3 version and all bytes following ID3 are preserved.

        Each changed file gets an exact .id3 backup and a .json metadata backup
        before writing. A write/delete-exclusive file handle covers reading,
        checking, backing up, writing and verification. Playback readers may
        stay open if they allow write sharing. Incompatible handles cause a
        reported failure; the command never closes or stops another process.
        The batch is NOT atomic: successful earlier files remain changed.
        A failed write is rolled back while the protected handle is still held.
        Rebuild Tracks.csv separately after a successful library-wide apply.
    .PARAMETER PatchPath
        UTF-8 JSON array; paths in records must be absolute MP3 paths.
    .PARAMETER BackupDirectory
        Existing or new backup directory. Dry runs create no backups.
    .PARAMETER ReportPath
        Optional new UTF-8 JSON report file (must not already exist).
        Results include path, status, before, after, errors and backup paths.
        Status is dry_run, unchanged, applied or error. On failure the function
        emits results, then throws; the optional report remains available.
    .PARAMETER Apply
        Explicitly enables writes and backups. Otherwise performs validation
        and reports proposed changes without modifying MP3 files.
    .EXAMPLE
        Set-TrackText -PatchPath .\patch.json -BackupDirectory .\backups
    .EXAMPLE
        Set-TrackText -PatchPath .\patch.json -BackupDirectory .\backups `
            -ReportPath .\applied.json -Apply
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$PatchPath,
        [Parameter(Mandatory)]
        [string]$BackupDirectory,
        [string]$ReportPath,
        [switch]$Apply
    )

    $ErrorActionPreference = 'Stop'
    $writer = Join-Path $PSScriptRoot '..\..\Tools\Music\write_comment.py'
    $request = @{
        patch_path = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($PatchPath)
        backup_directory = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($BackupDirectory)
        apply = [bool]$Apply
    }
    if ($ReportPath) {
        $request.report_path = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($ReportPath)
    }
    $utf8 = [System.Text.UTF8Encoding]::new($false)
    $start = [System.Diagnostics.ProcessStartInfo]::new()
    $start.FileName = (Get-Command python -CommandType Application | Select-Object -First 1).Source
    $start.Arguments = '"' + $writer + '" --request-stdin'
    $start.UseShellExecute = $false
    $start.CreateNoWindow = $true
    $start.RedirectStandardInput = $true
    $start.RedirectStandardOutput = $true
    $start.RedirectStandardError = $true
    $start.StandardOutputEncoding = $utf8
    $start.StandardErrorEncoding = $utf8
    $process = [System.Diagnostics.Process]::new()
    $process.StartInfo = $start
    try {
        [void]$process.Start()
        $stdout = $process.StandardOutput.ReadToEndAsync()
        $stderr = $process.StandardError.ReadToEndAsync()
        $bytes = $utf8.GetBytes(($request | ConvertTo-Json -Compress))
        $process.StandardInput.BaseStream.Write($bytes, 0, $bytes.Length)
        $process.StandardInput.Close()
        $process.WaitForExit()
        $text = $stdout.GetAwaiter().GetResult()
        $errorText = $stderr.GetAwaiter().GetResult()
        if ($text) {
            $report = $text | ConvertFrom-Json
            foreach ($result in $report.results) { $result }
        }
        if ($process.ExitCode -ne 0) {
            throw "Set-TrackText failed (exit $($process.ExitCode)). $errorText $text"
        }
        if (-not $text -or -not $report.ok) {
            throw 'Set-TrackText received no successful JSON report.'
        }
    }
    finally {
        $process.Dispose()
    }
}
