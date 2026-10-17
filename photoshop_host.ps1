$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$utf8 = New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding = $utf8
[Console]::OutputEncoding = $utf8
$photoshop = $null
while ($null -ne ($line = [Console]::ReadLine())) {
    try {
        $request = $line | ConvertFrom-Json
        if ($request.action -eq 'quit') { break }
        if (-not $photoshop) {
            try { $photoshop = [Runtime.InteropServices.Marshal]::GetActiveObject('Photoshop.Application') }
            catch {
                if ($request.start) {
                    if (-not $request.photoshop -or -not (Test-Path -LiteralPath $request.photoshop -PathType Leaf)) {
                        throw 'Photoshop not found. Start Photoshop manually, then retry in Sony RAW Panel.'
                    }
                    [void](Start-Process -FilePath $request.photoshop -PassThru)
                    $deadline = [DateTime]::UtcNow.AddSeconds(90)
                    while (-not $photoshop -and [DateTime]::UtcNow -lt $deadline) {
                        Start-Sleep -Milliseconds 500
                        try { $photoshop = [Runtime.InteropServices.Marshal]::GetActiveObject('Photoshop.Application') } catch {}
                    }
                    if (-not $photoshop) {
                        throw 'Photoshop scripting unavailable. Finish starting Photoshop manually and retry. Photoshop must support COM/JSX scripting.'
                    }
                }
                else {
                    [Console]::WriteLine('{"ok":true,"running":false}')
                    continue
                }
            }
        }
        try { $null = $photoshop.Version }
        catch { $photoshop = $null; throw 'Photoshop was closed. Repeat the command after starting Photoshop.' }
        $script = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($request.script))
        $value = $photoshop.DoJavaScript($script)
        $response = @{ok=$true; running=$true; value=[string]$value} | ConvertTo-Json -Compress
        [Console]::WriteLine($response)
    } catch {
        $response = @{ok=$false; error=$_.Exception.Message} | ConvertTo-Json -Compress
        [Console]::WriteLine($response)
    }
}
if ($photoshop) { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($photoshop) }
