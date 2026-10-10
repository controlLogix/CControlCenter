$taskEvidence='C:/Users/RyanHelms/.cache/agentmux/p01-provider-auth-preflight.json'
$taskResult=[ordered]@{
 candidate=(git rev-parse HEAD).Trim()
 observedAt=[DateTimeOffset]::UtcNow.ToString('o')
 WindowsGrokAuthPresent=(Test-Path -LiteralPath 'C:/Users/RyanHelms/.grok/auth.json')
 ProcessXaiKeyPresent=[bool]$env:XAI_API_KEY
 UserXaiKeyPresent=[bool][Environment]::GetEnvironmentVariable('XAI_API_KEY','User')
 MachineXaiKeyPresent=[bool][Environment]::GetEnvironmentVariable('XAI_API_KEY','Machine')
 noProviderCalls=$true
 noAuthenticationChanges=$true
 limits=@('Presence only within recorded Windows default auth path and XAI_API_KEY scopes; no exhaustive credential search or authentication validation.','No credential values recorded. WSL default Grok auth absence observed separately.','Original four actual-provider runs remain unexecuted; client state/tool-path readiness is separate.')
}
$taskResult | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $taskEvidence -Encoding utf8
Write-Output "Recorded safe presence metadata at $taskEvidence"
