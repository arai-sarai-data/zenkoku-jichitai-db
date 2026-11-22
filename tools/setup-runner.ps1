# zenkoku-jichitai-db 用の GitHub Actions Runner(日本国内からの収集役)を、このPCに入れるスクリプト。
# 使い方(PowerShell に1行貼り付け):
#   irm https://raw.githubusercontent.com/arai-sarai-data/zenkoku-jichitai-db/main/tools/setup-runner.ps1 | iex
# 管理者権限は不要。入れる場所: %USERPROFILE%\actions-runner-mfdb
# 自動起動: スタートアップフォルダに起動用ファイルを置く(ログオン時に最小化で起動)
$ErrorActionPreference = 'Stop'
$ver  = '2.338.2'
$hash = 'A1F17AA987FC8158BC7521D284912267A0D01B7C2C4684B33C86783B5E8221CC'
$dir  = Join-Path $env:USERPROFILE 'actions-runner-mfdb'
New-Item -ItemType Directory -Force $dir | Out-Null
Set-Location $dir
$zip = "actions-runner-win-x64-$ver.zip"
if (-not (Test-Path (Join-Path $dir 'config.cmd'))) {
    Write-Host "[1/4] GitHub公式の Runner をダウンロードしています..."
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -Uri "https://github.com/actions/runner/releases/download/v$ver/$zip" -OutFile $zip -UseBasicParsing
    if ((Get-FileHash $zip -Algorithm SHA256).Hash -ne $hash) { throw 'ダウンロードしたファイルの検証に失敗しました(ハッシュ不一致)。中止します。' }
    Write-Host "[2/4] 展開しています..."
    Expand-Archive $zip -DestinationPath $dir -Force
    Remove-Item $zip
}
Write-Host ""
Write-Host "[3/4] 登録します。GitHubの画面の「./config.cmd --url ... --token XXXXX」の XXXXX 部分を貼り付けて Enter を押してください。"
$token = (Read-Host 'トークン').Trim()
& .\config.cmd --unattended --url https://github.com/arai-sarai-data/zenkoku-jichitai-db --token $token `
    --name ("japan-" + $env:COMPUTERNAME) --labels japan --work _work --replace
if ($LASTEXITCODE -ne 0) { throw '登録に失敗しました。トークンの期限(1時間)が切れていないか確認してください。' }
Write-Host "[4/4] ログオン時に自動で起動するよう設定し、今すぐ起動します..."
$startup = [Environment]::GetFolderPath('Startup')
$launcher = Join-Path $startup 'github-runner-zenkoku-jichitai-db.cmd'
Set-Content -Path $launcher -Encoding Ascii -Value "@echo off`r`ncd /d `"$dir`"`r`nstart `"`" /min cmd /c run.cmd"
Start-Process -FilePath 'cmd.exe' -ArgumentList '/c', 'run.cmd' -WorkingDirectory $dir -WindowStyle Minimized
Write-Host ""
Write-Host "完了しました。最小化された黒い画面(run.cmd)が収集役です。閉じずにそのままにしてください。"
Write-Host "やめたいとき: $launcher を削除し、$dir フォルダで .\config.cmd remove を実行します。"
