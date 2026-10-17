from pathlib import Path
import subprocess
import unittest


class PhotoshopHostTests(unittest.TestCase):
    def test_rpc_hresult_and_reference_reset(self):
        path=Path(__file__).resolve().parent/'photoshop_host.ps1'
        script=r'''
$ErrorActionPreference='Stop'
$text=[IO.File]::ReadAllText($args[0])
$prefix=$text.Substring(0,$text.IndexOf('while ($null -ne ($line'))
. ([scriptblock]::Create($prefix))
$exception=New-Object Runtime.InteropServices.COMException('Disconnected',-2147023174)
$record=New-Object Management.Automation.ErrorRecord($exception,'rpc',[Management.Automation.ErrorCategory]::ConnectionError,$null)
if (-not (Test-RpcServerUnavailable $record)) { throw 'RPC HRESULT not recognized' }
$other=New-Object Exception('ordinary JSX error')
$record=New-Object Management.Automation.ErrorRecord($other,'jsx',[Management.Automation.ErrorCategory]::NotSpecified,$null)
if (Test-RpcServerUnavailable $record) { throw 'Ordinary JSX error misclassified as RPC' }
$script:photoshop=New-Object Object
Clear-PhotoshopReference
if ($null -ne $script:photoshop) { throw 'Cached reference was not cleared' }
Clear-PhotoshopReference
'host helpers passed'
'''
        import tempfile
        with tempfile.TemporaryDirectory() as temp:
            check=Path(temp)/'check.ps1'
            check.write_text(script,encoding='ascii')
            result=subprocess.run(['powershell.exe','-NoLogo','-NoProfile','-STA','-File',str(check),str(path)],capture_output=True,text=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertIn('host helpers passed',result.stdout)


if __name__=='__main__':
    unittest.main()
