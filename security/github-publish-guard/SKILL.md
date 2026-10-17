---
name: github-publish-guard
description: >-
  Mandatory pre-publish security, legal, trademark, and GitHub Terms of Service (ToS / Acceptable Use Policy) auditor. Trigger BEFORE any git push, gh repo create, gh release create, or making a repository public. Scans both the working tree and full git commit history for executables/binaries (.exe, .dll, .msi, .apk), binaries or repos named after third-party companies/trademarks, leaked secrets/tokens/cookies, personal data (PII) of third parties, confidential company/school reports, copyrighted media, and AI commit attribution, warning the user of any potential legal, trademark, or account-suspension risk before publishing.
---

# GitHub Publish Guard (ToS, Trademark, Binary & Secret Auditor)

This skill is a **blocking pre-flight gate** before publishing or pushing any repository to GitHub. Its purpose is to protect the repository owner from **account suspension, automated malware/impersonation flags, DMCA takedowns, trademark disputes, and data-leak incidents**.

---

## When to Trigger (MANDATORY)

Execute this skill **BEFORE**:
- Running `git push` (especially the first push of a repo or a branch with new files)
- Running `gh repo create` or `gh release create`
- Changing repository visibility to public (`gh repo edit --visibility public`)
- Whenever the user asks to "upload to GitHub", "publish the repo", or "audit before pushing"

---

## Step 1: Run the Automated Pre-Publish Audit Script

Run the bundled PowerShell audit script from the target repository root (or run equivalent git/ripgrep checks if on Linux/macOS):

```powershell
powershell -ExecutionPolicy Bypass -File "./scripts/audit-repo.ps1" -RepoPath "."
```

---

## Step 2: 7-Pillar Manual & Semantic Audit

Even if automated regexes pass, you MUST semantically verify all 7 pillars below:

### 1. Trademark, Company & Brand Name Check (Repo & Product Identity)
- **Rule**: NEVER use a third-party company, brand, institution, university, bank, or government agency name as a **repository name, package name, binary name, or product title** (e.g., `Moodle`, `Spotify`, `Netflix`, `YouTube`, `WhatsApp`, `Discord`, `Roblox`, `SRI`, `Nintendo`, `Microsoft`, real client company names).
- **Why**: Naming a repository or executable after a registered brand triggers trademark/impersonation takedowns and GitHub Trust & Safety flags.
- **Allowed Exception**: Descriptive integration module filenames inside the codebase (e.g., `moodle_client.py`, `spotify_csv_importer.js`) are fine as long as the repository and product name are 100% original (e.g., `mineral-tareas`, `MyMusicAnywhere`).

### 2. Zero Executables, Installers & Compiled Binaries (Working Tree + Git History)
- **Rule**: NEVER push compiled executables, installers, or binary bundles:
  - Forbidden extensions: `.exe`, `.dll`, `.msi`, `.apk`, `.aab`, `.dmg`, `.pkg`, `.deb`, `.rpm`, `.AppImage`, `.so`, `.dylib`, `.jar`, `.war`, `.bin`, `.iso`, `.scr`, `.bat` droppers, or `.zip`/`.7z`/`.rar` build archives.
  - **CRITICAL**: Check **both** the working tree AND the entire git commit history (`git log --all --full-history --name-only`). Deleting a `.exe` in a new commit does **not** remove it from `.git/objects`—GitHub still scans old commits!
  - **Company-Named Executables**: An `.exe` or `.apk` carrying a company or brand name (e.g., `CompanyApp.exe`, `MoodleSync.exe`) is an **immediate CRITICAL blocker** (high probability of automated phishing/malware flagging).

### 3. Zero Secrets, Tokens, Cookies & Infrastructure Credentials
- **Rule**: Audit tracked files and git history for:
  - `.env`, `.env.local`, `.env.production` (only `.env.example` with dummy placeholders is allowed)
  - Netscape `cookies.txt` / session dumps / browser profiles
  - Private keys (`.pem`, `.key`, `.pfx`, `.p12`, `id_rsa`, `id_ed25519`)
  - API tokens (`ghp_`, `gho_`, `github_pat_`, `sk-`, `AIza`, `xoxb-`, `AKIA`, Supabase `service_role` keys, JWT secrets, database URIs with passwords)
  - Hardcoded private server SSH usernames + IP addresses or internal ports

### 4. Zero Third-Party Personal Data (PII) & Confidential Reports
- **Rule**: NEVER publish:
  - Real names, national IDs (`cédulas`, `RUC`, `DNI`, `SSN`), phone numbers, personal emails, home addresses, student rosters, or grades of real people.
  - Security audits, pentest reports, academic papers, or business documents (`.pdf`, `.docx`, `.xlsx`, `.pptx`, `.md`) that name real third-party companies, clients, clinics, or institutions without explicit anonymization.
  - Production SQLite/SQL databases (`.sqlite`, `.db`, `.sql` dumps containing real user rows).

### 5. GitHub Acceptable Use Policies (AUP) & Terms of Service
- **Rule**: Verify the repository does not contain or promote:
  - Credential harvesting, phishing pages, keyloggers, C2 frameworks, or unconsented exploit payloads targeting live third-party infrastructure.
  - Abusive bots, mass-spam tools, fake engagement/star generators, or denial-of-service scripts.
  - Copyrighted commercial media files (`.mp3`, `.flac`, `.mp4`, `.mkv` songs, movies, or paid proprietary assets/fonts).

### 6. Git History & Commit Attribution Hygiene
- **Rule**:
  - Verify `git log` contains **zero** `Co-Authored-By:` or AI attribution trailers.
  - Ensure all commits follow Conventional Commits (`feat:`, `fix:`, `chore:`, `docs:`, `refactor:`).

### 7. Active GitHub Account Verification
- **Rule**: Run `gh auth status` before pushing:
  - Personal projects MUST use `Steimber` (`gh auth switch --user Steimber`).
  - Work/CRM projects MUST use `SteimberArteaga`.
  - `SteimberAZ` is deprecated and must never be used.

---

## Step 3: Mandatory Altercation Warning Protocol (Blocking)

If **ANY** check fails or looks doubtful:
1. **STOP IMMEDIATELY**. Do NOT run `git push` or `gh repo create`.
2. Present a clear **Alerta de Seguridad y Términos de GitHub** to the user in their active conversation language, structured as:
   - **Severidad**: `CRÍTICO (Bloqueante)` / `ALTO` / `ADVERTENCIA`
   - **Archivo / Commit afectado**: Exact path and whether it is in the working tree or git history.
   - **Riesgo de altercado**: Plain-language explanation of what could happen if pushed (e.g., *"Subir este `.exe` con nombre de empresa o nombrar el repositorio con una marca de terceros viola las políticas de impersonación/malware de GitHub y puede causar suspensión automática de la cuenta o reclamo legal/DMCA"*).
   - **Solución recomendada**: How to clean it before pushing (including rewriting history with a fresh orphan commit or `git filter-repo` if the file was already committed locally).
3. Wait for explicit user confirmation after remediation before pushing.
