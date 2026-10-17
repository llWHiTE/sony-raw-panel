$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$utf8 = New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding = $utf8
[Console]::OutputEncoding = $utf8
$script:photoshop = $null
$script:rpcDisconnectedMessage = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('0KHQvtC10LTQuNC90LXQvdC40LUg0YEgUGhvdG9zaG9wINC/0L7RgtC10YDRj9C90L46IFJQQy3RgdC10YDQstC10YAg0L3QtdC00L7RgdGC0YPQv9C10L0uIFBob3Rvc2hvcCDQsdGL0Lsg0LfQsNC60YDRi9GCINC40LvQuCDQv9C10YDQtdC30LDQv9GD0YnQtdC9LiDQlNC+0LbQtNC40YLQtdGB0Ywg0L/QvtC70L3QvtCz0L4g0LfQsNC/0YPRgdC60LAgUGhvdG9zaG9wINC4INC/0L7QstGC0L7RgNC40YLQtSDQutC+0LzQsNC90LTRgy4g0J7Qv9C10YDQsNGG0LjRjyDQvdC1INCx0YvQu9CwINC/0L7QstGC0L7RgNC10L3QsCDQsNCy0YLQvtC80LDRgtC40YfQtdGB0LrQuC4='))
$script:connectionLostMessage = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('0KHQvtC10LTQuNC90LXQvdC40LUg0YEgUGhvdG9zaG9wINC/0L7RgtC10YDRj9C90L4uINCX0LDQv9GD0YHRgtC40YLQtSBQaG90b3Nob3Ag0Lgg0L/QvtCy0YLQvtGA0LjRgtC1INC60L7QvNCw0L3QtNGDLg=='))

function Clear-PhotoshopReference {
    if ($null -ne $script:photoshop) {
        try { [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($script:photoshop) } catch {}
        $script:photoshop = $null
    }
}

function Test-RpcServerUnavailable {
    param([System.Management.Automation.ErrorRecord]$ErrorRecord)

    $exception = $ErrorRecord.Exception
    while ($null -ne $exception) {
        if ($exception.HResult -eq -2147023174 -or $exception.Message -match '0x800706BA|RPC server is unavailable') {
            return $true
        }
        $exception = $exception.InnerException
    }
    return $false
}

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
        catch {
            $rpcUnavailable = Test-RpcServerUnavailable $_
            Clear-PhotoshopReference
            if ($rpcUnavailable) { throw $script:rpcDisconnectedMessage }
            throw $script:connectionLostMessage
        }
        $script = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($request.script))
        try { $value = $photoshop.DoJavaScript($script) }
        catch {
            $rpcUnavailable = Test-RpcServerUnavailable $_
            # A failed JSX invocation may have completed partially, so only the caller can retry it.
            Clear-PhotoshopReference
            if ($rpcUnavailable) { throw $script:rpcDisconnectedMessage }
            throw
        }
        $response = @{ok=$true; running=$true; value=[string]$value} | ConvertTo-Json -Compress
        [Console]::WriteLine($response)
    } catch {
        $response = @{ok=$false; error=$_.Exception.Message} | ConvertTo-Json -Compress
        [Console]::WriteLine($response)
    }
}
Clear-PhotoshopReference
