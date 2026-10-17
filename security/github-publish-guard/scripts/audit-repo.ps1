param(
    [string]$RepoPath = "."
)

$ErrorActionPreference = "SilentlyContinue"
Push-Location $RepoPath

Write-Host "=====================================================" -ForegroundColor Cyan
Write-Host "  GITHUB PUBLISH GUARD - PRE-FLIGHT REPOSITORY AUDIT " -ForegroundColor Cyan
Write-Host "=====================================================" -ForegroundColor Cyan

$folderName = Split-Path (Get-Location) -Leaf
Write-Host "`n[1/6] Checking Repository Name & Active GitHub Account..." -ForegroundColor Yellow
Write-Host "Repository Folder: $folderName"

$brandRegex = "(?i)\b(moodle|spotify|netflix|youtube|whatsapp|discord|roblox|nintendo|microsoft|google|apple|amazon|meta|facebook|instagram|tiktok|sri|pichincha|guayaquil|pacifico|produbanco)\b"
if ($folderName -match $brandRegex) {
    Write-Host "  [CRITICAL] Repository folder name '$folderName' matches a third-party brand/institution ('$($Matches[0])')!" -ForegroundColor Red
    Write-Host "             Never use a company or brand name as a repository or product name." -ForegroundColor Red
} else {
    Write-Host "  [OK] Repository folder name looks original." -ForegroundColor Green
}

$ghStatus = gh auth status 2>&1 | Out-String
if ($ghStatus -match "Logged in to github\.com account (\S+)[\s\S]*?Active account: true") {
    Write-Host "  [INFO] Active GitHub Account: $($Matches[1])" -ForegroundColor Cyan
}

Write-Host "`n[2/6] Scanning Working Tree for Executables, Binaries & Installers..." -ForegroundColor Yellow
$binaryExts = @(".exe", ".dll", ".msi", ".apk", ".aab", ".dmg", ".pkg", ".deb", ".rpm", ".so", ".dylib", ".jar", ".war", ".iso", ".bin", ".scr", ".mp3", ".mp4", ".mkv", ".flac", ".sqlite", ".db", ".pfx", ".p12", ".pem", ".key")
$trackedAndUntracked = git ls-files --cached --others --exclude-standard 2>$null
if (-not $trackedAndUntracked) {
    $trackedAndUntracked = Get-ChildItem -Recurse -File | Where-Object { $_.FullName -notmatch "\\(\.git|node_modules|\.next|dist|build)\\" } | ForEach-Object { $_.FullName }
}

$badFiles = @()
foreach ($f in $trackedAndUntracked) {
    $ext = [System.IO.Path]::GetExtension($f).ToLower()
    if ($binaryExts -contains $ext -or $f -match "(?i)(^\.env|\\/\.env|cookies\.txt|id_rsa|id_ed25519)") {
        if ($f -notmatch "\.env\.example$") {
            $badFiles += $f
        }
    }
}

if ($badFiles.Count -gt 0) {
    Write-Host "  [CRITICAL] Found forbidden binaries, media, database, or credential files in working tree:" -ForegroundColor Red
    $badFiles | ForEach-Object { Write-Host "    - $_" -ForegroundColor Red }
} else {
    Write-Host "  [OK] No forbidden binaries, media, or .env files in working tree." -ForegroundColor Green
}

Write-Host "`n[3/6] Scanning Full Git History for Previously Committed Binaries or Secrets..." -ForegroundColor Yellow
if (Test-Path ".git") {
    $historyFiles = git log --all --full-history --name-only --pretty=format:"" 2>$null | Sort-Object -Unique
    $badHistory = @()
    foreach ($hf in $historyFiles) {
        if (-not $hf) { continue }
        $ext = [System.IO.Path]::GetExtension($hf).ToLower()
        if ($binaryExts -contains $ext -or ($hf -match "(?i)(^\.env|\/\.env|cookies\.txt|id_rsa)" -and $hf -notmatch "\.env\.example$")) {
            $badHistory += $hf
        }
    }
    if ($badHistory.Count -gt 0) {
        Write-Host "  [CRITICAL] Found forbidden files in GIT COMMIT HISTORY (must scrub history before pushing!):" -ForegroundColor Red
        $badHistory | ForEach-Object { Write-Host "    - $_" -ForegroundColor Red }
    } else {
        Write-Host "  [OK] Git commit history is clean of binaries and .env files." -ForegroundColor Green
    }
} else {
    Write-Host "  [INFO] Not a git repository yet." -ForegroundColor Gray
}

Write-Host "`n[4/6] Scanning Tracked Text Files for Secrets, Tokens & Private Keys..." -ForegroundColor Yellow
$secretPattern = "(ghp_[A-Za-z0-9]{30,}|gho_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|sk-[A-Za-z0-9]{30,}|AIza[0-9A-Za-z\-_]{35}|AKIA[0-9A-Z]{16}|-----BEGIN (RSA|OPENSSH|EC|PRIVATE) KEY-----|[a-zA-Z0-9_.-]+@\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})"
$filesToScan = $trackedAndUntracked | Where-Object { Test-Path $_ }
$secretHits = @()
foreach ($file in $filesToScan) {
    $matches = Select-String -Path $file -Pattern $secretPattern -AllMatches
    if ($matches) {
        foreach ($m in $matches) {
            $secretHits += "$($file):$($m.LineNumber)"
        }
    }
}
if ($secretHits.Count -gt 0) {
    Write-Host "  [CRITICAL] Potential secret, token, or private server IP detected:" -ForegroundColor Red
    $secretHits | Select-Object -First 15 | ForEach-Object { Write-Host "    - $_" -ForegroundColor Red }
} else {
    Write-Host "  [OK] No hardcoded tokens, private keys, or server IPs found." -ForegroundColor Green
}

Write-Host "`n[5/6] Checking Commit History for AI Attribution (Co-Authored-By)..." -ForegroundColor Yellow
if (Test-Path ".git") {
    $aiCommits = git log --all --grep="Co-Authored-By" --oneline 2>$null
    if ($aiCommits) {
        Write-Host "  [CRITICAL] Found Co-Authored-By trailers in git history:" -ForegroundColor Red
        $aiCommits | ForEach-Object { Write-Host "    - $_" -ForegroundColor Red }
    } else {
        Write-Host "  [OK] Zero Co-Authored-By trailers in commit history." -ForegroundColor Green
    }
}

Write-Host "`n[6/6] Audit Complete." -ForegroundColor Cyan
Pop-Location
