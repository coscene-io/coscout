$ErrorActionPreference = "Stop"

$SERVER_URL = ""
$PROJECT_SLUG = ""
$USE_LOCAL = ""
$BETA = 0
$DISABLE_SYSTEMD = 0
$MOD = "default"

function IsWindows
{
    return $env:OS -match "Windows"
}
if (!(IsWindows))
{
    Write-Host "This script is only for Windows."
    exit 1
}

$ARCH = ""
switch ($env:PROCESSOR_ARCHITECTURE)
{
    "AMD64" {
        $ARCH = "x86_64"
    }
    default {
        Write-Host "Unsupported architecture: $ARCH, only support x86_64"
        exit 1
    }
}

function Help
{
    Write-Host @"
usage: install.ps1 [OPTIONS]
    --help               Show this message
    --server_url         Api server url, e.g. https://api.coscene.cn
    --project_slug       The slug of the project to upload to
    --beta               Use beta version
    --use_local          Use local binary file zip path e.g. C:\Documents\cos.zip
    --disable_systemd    Disable systemd service installation
    --mod                Select the mod to install - gs, default (default is 'default')
"@
}

function GetUserInput
{
    param (
        [string]$VariableName,
        [string]$Prompt,
        [string]$InputValue
    )
    while (-not$InputValue)
    {
        $InputValue = Read-Host -Prompt $Prompt
    }
    Set-Variable -Name $VariableName -Value $InputValue
}

foreach ($arg in $args)
{
    switch -Regex ($arg)
    {
        "--help" {
            help
            exit 0
        }
        "--server_url=(.*)" {
            $SERVER_URL = $Matches[1]
        }
        "--project_slug=(.*)" {
            $PROJECT_SLUG = $Matches[1]
        }
        "--beta" {
            $BETA = 1
        }
        "--use_local=(.*)" {
            $USE_LOCAL = $Matches[1]
        }
        "--disable_systemd" {
            $DISABLE_SYSTEMD = 1
        }
        "--mod=(.*)" {
            if ($Matches[1] -in "gs", "default") {
                $MOD = $Matches[1]
            } else {
                Write-Host "Invalid mod input, gs、default (default is 'default')"
                exit 1
            }
        }
        default {
            Write-Host "unknown option: $ARG"
            help
            exit 1
        }
    }
}
GetUserInput "SERVER_URL" "Please input server url: " $SERVER_URL
GetUserInput "PROJECT_SLUG" "Please input project slug: " $PROJECT_SLUG
Write-Host "Using server url: $SERVER_URL"
Write-Host "Using project slug: $PROJECT_SLUG"

# set default base url
$LATEST_BASE_URL = "https://download.coscene.cn/coscout/windows/$ARCH/latest"
$BETA_BASE_URL = "https://download.coscene.cn/coscout/windows/$ARCH/beta"
$DEFAULT_BASE_URL = $LATEST_BASE_URL
$DEFAULT_BINARY_URL = "$LATEST_BASE_URL/cos"
if ($BETA -eq 1)
{
    $DEFAULT_BINARY_URL = "$BETA_BASE_URL/cos"
    $DEFAULT_BASE_URL = $BETA_BASE_URL
}

# create binary folder
$COS_SHELL_BASE = "$env:ALLUSERSPROFILE\coscene\cos\bin"
New-Item -ItemType Directory -Force -Path $COS_SHELL_BASE

# create config folder
$COS_CONFIG_DIR = "$env:ALLUSERSPROFILE\coscene\cos\config"
New-Item -ItemType Directory -Force -Path $COS_CONFIG_DIR

Write-Host "Creating config file..."
$CONFIG_FILE = "$COS_CONFIG_DIR\config.yaml"
$LOCAL_CONFIG_FILE = "$COS_CONFIG_DIR\local.yaml"
$DEFAULT_IMPORT_CONFIG = "cos://organizations/current/configMaps/device.collector"
$DEFAULT_CODE_URL = "cos://organizations/current/configMaps/device.errorCode"
# Creating config.yaml file
@"
api:
  server_url: $SERVER_URL
  project_slug: $PROJECT_SLUG
updater:
  artifact_base_url: $DEFAULT_BASE_URL
  binary_path: $COS_SHELL_BASE\cos.exe
event_code:
  enabled: true
  code_json_url: $DEFAULT_CODE_URL
mod:
  name: $MOD
  conf:
    enabled: true
__import__:
  - $DEFAULT_IMPORT_CONFIG
  - file:///$COS_CONFIG_DIR\local.yaml
__reload__:
  reload_interval_in_secs: 60
"@ | Set-Content -Path $CONFIG_FILE
Write-Host "Created config file: $CONFIG_FILE"

if (-not(Test-Path $LOCAL_CONFIG_FILE))
{
    "{}" | Set-Content -Path $LOCAL_CONFIG_FILE
    Write-Host "Created local config file: $LOCAL_CONFIG_FILE"
}

# region binary
function CheckBinary($binary)
{
    Write-Host -NoNewline "  - Checking $binary executable ... "
    try
    {
        $output = & "$COS_SHELL_BASE\$binary" --version
        Write-Host $output
    }
    catch
    {
        Write-Host "Error: $_"
    }
}

if (Test-Path "$COS_SHELL_BASE\cos.exe")
{
    Write-Host "Previously installed version:"
    CheckBinary "cos.exe"
}

if ($USE_LOCAL)
{
    if (!($USE_LOCAL.EndsWith(".zip")))
    {
        Write-Host "ERROR: The file specified is not a zip archive. Exiting."
        exit 1
    }
    Write-Host "Extracting $USE_LOCAL..."
    $TEMP_DIR = New-Item -ItemType Directory -Path "$env:TEMP\cos_binaries" -Force
    Expand-Archive -Path $USE_LOCAL -DestinationPath $TEMP_DIR.FullName
    $TMP_FILE = "$TEMP_DIR.FullName\$ARCH\cos.exe"
    if (!(Test-Path $TMP_FILE))
    {
        Write-Host "ERROR: Failed to download cos binary. Exiting."
        exit 1
    }
    $REMOTE_SHA256 = Get-Content "$TEMP_DIR.FullName\$ARCH\cos.sha256"
}
else
{
    Write-Host "Downloading new cos binary..."
    $TMP_FILE = New-TemporaryFile
    Register-EngineEvent PowerShell.Exiting -Action {
        if (Test-Path $TMP_FILE)
        {
            Remove-Item $TMP_FILE -Force
        }
    }
    Invoke-WebRequest -Uri "$DEFAULT_BINARY_URL.exe" -OutFile $TMP_FILE
    $fileResponse = Invoke-WebRequest -Uri "$DEFAULT_BINARY_URL.sha256" -UseBasicParsing
    $REMOTE_SHA256 = [System.Text.Encoding]::UTF8.GetString($fileResponse.Content).Trim()
}

$LOCAL_SHA256 = (Get-FileHash -Algorithm SHA256 $TMP_FILE).Hash
if ($REMOTE_SHA256 -eq $LOCAL_SHA256)
{
    Write-Host "SHA256 verified. Proceeding."
}
else
{
    Write-Host "Error: SHA256 mismatch. Exiting."
    exit 1
}
Write-Host "Installed new cos version:"
$destBinFile = Join-Path -Path $COS_SHELL_BASE -ChildPath "cos.exe"

# winsw service file
$winswFile = Join-Path -Path $COS_SHELL_BASE -ChildPath "winsw.exe"
$serviceConfigFilePath = "$COS_CONFIG_DIR\cos-service.xml"

if (Test-Path $destBinFile) {
    Start-Process -FilePath $winswFile -ArgumentList "stop $serviceConfigFilePath" -Wait
    Remove-Item $destBinFile -Force
}
Move-Item -Path $TMP_FILE -Destination $destBinFile -Force
Set-ItemProperty -Path $destBinFile -Name IsReadOnly -Value $false
CheckBinary "cos.exe"
# endregion

if ($DISABLE_SYSTEMD -eq 0)
{
    try
    {
        Write-Host "Creating cos windows service..."
        if (-not(Test-Path $winswFile))
        {
            Write-Host "Downloading winsw..."
            $winswUrl = "https://download.coscene.cn/coscout/WinSW-x86.exe"
            Invoke-WebRequest -Uri $winswUrl -OutFile $winswFile
        }

        @"
<service>
  <id>cos</id>
  <name>CoScene</name>
  <description>CoScene uploader service</description>
  <executable>$destBinFile</executable>
  <arguments>daemon</arguments>
  <log mode="roll-by-size">
    <sizeThreshold>10240</sizeThreshold>
    <keepFiles>3</keepFiles>
  </log>
  <serviceaccount>
    <username>LocalSystem</username>
  </serviceaccount>
</service>
"@ | Set-Content -Path $serviceConfigFilePath
        Start-Process -FilePath $winswFile -ArgumentList "install $serviceConfigFilePath" -Wait
        Start-Process -FilePath $winswFile -ArgumentList "start $serviceConfigFilePath" -Wait
        Write-Host "Done."
    }
    catch
    {
        Write-Host "Failed to create Windows service: `n$_"
    }
}
else
{
    Write-Host "Skipping windows service installation, just install cos binary..."
}
