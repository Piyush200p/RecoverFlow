# start-server.ps1
# PowerShell script to boot up the entire RecoverFlow application stack.

# 1. Start Docker Desktop and wait for it
Write-Host "Checking Docker status..." -ForegroundColor Cyan
try {
    $dockerCheck = docker ps 2>&1
} catch {
    $dockerCheck = $null
}

if ($null -eq $dockerCheck -or $dockerCheck -notmatch "CONTAINER ID" -or $dockerCheck -match "not recognized") {
    Write-Host "Docker is not running. Starting Docker Desktop..." -ForegroundColor Yellow
    if (Test-Path "C:\Program Files\Docker\Docker\Docker Desktop.exe") {
        Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe"
        Write-Host "Waiting for Docker daemon to become responsive..." -ForegroundColor Yellow
        while ($true) {
            Start-Sleep -Seconds 5
            try {
                $check = docker ps 2>&1
                if ($check -notmatch "error during connect") {
                    break
                }
            } catch {}
            Write-Host "." -NoNewline
        }
        Write-Host "`nDocker daemon is ready." -ForegroundColor Green
    } else {
        Write-Error "Docker Desktop.exe not found at standard path. Please start Docker manually."
        exit 1
    }
} else {
    Write-Host "Docker daemon is already active." -ForegroundColor Green
}

# 2. Ensure docker compose services are running
Write-Host "Ensuring backend containers are running..." -ForegroundColor Cyan
docker compose up -d

# 3. Clean and Start Cloudflare Tunnel
Write-Host "Starting Cloudflare Tunnel..." -ForegroundColor Cyan
if (Test-Path "D:\Project\recovery_app\cloudflared.log") { Remove-Item "D:\Project\recovery_app\cloudflared.log" -Force }
if (Test-Path "D:\Project\recovery_app\cloudflared_err.log") { Remove-Item "D:\Project\recovery_app\cloudflared_err.log" -Force }

Start-Process -FilePath "D:\Project\recovery_app\recover-flow\node_modules\@shopify\cli\bin\cloudflared.exe" -ArgumentList "tunnel", "--url", "http://localhost:62443", "--protocol", "http2" -RedirectStandardOutput "D:\Project\recovery_app\cloudflared.log" -RedirectStandardError "D:\Project\recovery_app\cloudflared_err.log"

# Wait for tunnel URL generation
Write-Host "Extracting Cloudflare tunnel URL..." -ForegroundColor Yellow
$tunnelUrl = $null
for ($i = 0; $i -lt 15; $i++) {
    Start-Sleep -Seconds 1
    if (Test-Path "D:\Project\recovery_app\cloudflared_err.log") {
        $log = Get-Content -Path "D:\Project\recovery_app\cloudflared_err.log"
        $line = $log | Where-Object { $_ -match "https://.*\.trycloudflare\.com" }
        if ($line) {
            if ($line -match "https://[a-zA-Z0-9\-]+\.trycloudflare\.com") {
                $tunnelUrl = $matches[0]
                break
            }
        }
    }
}

if (-not $tunnelUrl) {
    Write-Error "Failed to extract Cloudflare tunnel URL within 15 seconds. Check cloudflared_err.log."
    exit 1
}

Write-Host "Tunnel URL: $tunnelUrl" -ForegroundColor Green

# 4. Update shopify.app.toml with new URL
Write-Host "Updating shopify.app.toml with new tunnel URL..." -ForegroundColor Cyan
$tomlPath = "D:\Project\recovery_app\recover-flow\shopify.app.toml"
if (Test-Path $tomlPath) {
    $content = Get-Content -Path $tomlPath -Raw
    # Update application_url
    $content = $content -replace 'application_url\s*=\s*"https://[a-zA-Z0-9\-]+\.trycloudflare\.com"', "application_url = `"$tunnelUrl`""
    # Update redirect_urls
    $content = $content -replace 'https://[a-zA-Z0-9\-]+\.trycloudflare\.com/auth/callback', "$tunnelUrl/auth/callback"
    $content = $content -replace 'https://[a-zA-Z0-9\-]+\.trycloudflare\.com/auth"', "$tunnelUrl/auth`""
    $content = $content -replace 'https://[a-zA-Z0-9\-]+\.trycloudflare\.com/api/auth', "$tunnelUrl/api/auth"
    Set-Content -Path $tomlPath -Value $content
    Write-Host "Updated shopify.app.toml successfully." -ForegroundColor Green
} else {
    Write-Warning "shopify.app.toml not found. Skipping auto-update."
}

# 5. Start Shopify dev server in the foreground
Write-Host "Starting Shopify dev server..." -ForegroundColor Cyan
$env:NODE_OPTIONS = "--dns-result-order=ipv4first --require ./dns_override.cjs"
$env:SHOPIFY_CLI_STACKTRACE = "1"
Set-Location -Path "D:\Project\recovery_app\recover-flow"
npx shopify app dev --tunnel-url "${tunnelUrl}:62443"
