[CmdletBinding()]
param(
    [switch]$SelfTest
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$compilerReferences = [System.AppContext]::GetData(
    'TRUSTED_PLATFORM_ASSEMBLIES'
).Split([System.IO.Path]::PathSeparator)
Add-Type -ReferencedAssemblies $compilerReferences -TypeDefinition @'
using System.Windows.Forms;

public sealed class SmartDeskControlForm : Form
{
    public bool AllowExit { get; set; }

    protected override void OnFormClosing(FormClosingEventArgs e)
    {
        if (!AllowExit)
        {
            e.Cancel = true;
            Hide();
            return;
        }

        base.OnFormClosing(e);
    }
}
'@

$projectRoot = $PSScriptRoot
$runtimeDir = Join-Path $projectRoot '.smartdesk-runtime'
$startScript = Join-Path $projectRoot 'start.bat'
$stopScript = Join-Path $projectRoot 'kill.bat'
$iconPath = Join-Path $projectRoot 'assets\SmartDeskControl.ico'
$ownsAppIcon = Test-Path -LiteralPath $iconPath -PathType Leaf
$appIcon = if ($ownsAppIcon) {
    [System.Drawing.Icon]::new($iconPath)
}
else {
    [System.Drawing.SystemIcons]::Application
}

function Start-HiddenBatch {
    param(
        [Parameter(Mandatory)]
        [string]$ScriptPath,

        [Parameter(Mandatory)]
        [string]$LogName,

        [hashtable]$EnvironmentVariables = @{}
    )

    if (-not (Test-Path -LiteralPath $ScriptPath -PathType Leaf)) {
        throw "找不到启动脚本：$ScriptPath"
    }

    [System.IO.Directory]::CreateDirectory($runtimeDir) | Out-Null
    $logPath = Join-Path $runtimeDir $LogName
    $processInfo = [System.Diagnostics.ProcessStartInfo]::new()
    $processInfo.FileName = $env:ComSpec
    $processInfo.Arguments = '/d /c ""{0}" <nul 1>>"{1}" 2>&1"' -f $ScriptPath, $logPath
    $processInfo.WorkingDirectory = $projectRoot
    $processInfo.UseShellExecute = $false
    $processInfo.CreateNoWindow = $true
    $processInfo.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Hidden

    foreach ($entry in $EnvironmentVariables.GetEnumerator()) {
        $processInfo.EnvironmentVariables[$entry.Key] = [string]$entry.Value
    }

    return [System.Diagnostics.Process]::Start($processInfo)
}

function Test-LocalPort {
    param([Parameter(Mandatory)][int]$Port)

    $client = [System.Net.Sockets.TcpClient]::new()
    try {
        $connectTask = $client.ConnectAsync('127.0.0.1', $Port)
        return $connectTask.Wait(250) -and $client.Connected
    }
    catch {
        return $false
    }
    finally {
        $client.Dispose()
    }
}

if ($SelfTest) {
    [pscustomobject]@{
        controller = 'SmartDesk Meeting Controller'
        startScriptExists = Test-Path -LiteralPath $startScript -PathType Leaf
        stopScriptExists = Test-Path -LiteralPath $stopScript -PathType Leaf
        iconExists = Test-Path -LiteralPath $iconPath -PathType Leaf
        backendOnline = Test-LocalPort -Port 8000
        frontendOnline = Test-LocalPort -Port 5173
    } | ConvertTo-Json -Compress
    exit 0
}

$createdNew = $false
$mutex = [System.Threading.Mutex]::new(
    $true,
    'Local\SmartDeskMeetingController',
    [ref]$createdNew
)

if (-not $createdNew) {
    [System.Windows.Forms.MessageBox]::Show(
        '会议控制窗口已经在运行，请检查任务栏右下角。',
        'SmartDesk 会议控制',
        [System.Windows.Forms.MessageBoxButtons]::OK,
        [System.Windows.Forms.MessageBoxIcon]::Information
    ) | Out-Null
    $mutex.Dispose()
    exit 0
}

$script:allowExit = $false
$script:hasShownTrayHint = $false
$script:controllerState = 'Stopped'
$script:operationStartedAt = $null
$script:operationProcess = $null
$script:operationProcessExitObservedAt = $null
$script:progressHideAt = $null
$script:errorClearAt = $null
$script:lastBackendOnline = $false
$script:lastFrontendOnline = $false

function Set-StatusLabel {
    param(
        [Parameter(Mandatory)][System.Windows.Forms.Label]$Label,
        [Parameter(Mandatory)][bool]$Online
    )

    if ($Online) {
        $Label.Text = '运行中'
        $Label.ForeColor = [System.Drawing.Color]::FromArgb(20, 125, 70)
    }
    else {
        $Label.Text = '未运行'
        $Label.ForeColor = [System.Drawing.Color]::FromArgb(125, 125, 125)
    }
}

function Set-ActionButtonsFromHealth {
    param(
        [Parameter(Mandatory)][bool]$BackendOnline,
        [Parameter(Mandatory)][bool]$FrontendOnline
    )

    if ($BackendOnline -and $FrontendOnline) {
        $script:startButton.Enabled = $false
        $script:stopButton.Enabled = $true
        $script:openButton.Enabled = $true
    }
    elseif ($BackendOnline -or $FrontendOnline) {
        $script:startButton.Enabled = $true
        $script:stopButton.Enabled = $true
        $script:openButton.Enabled = $FrontendOnline
    }
    else {
        $script:startButton.Enabled = $true
        $script:stopButton.Enabled = $false
        $script:openButton.Enabled = $false
    }
}

function Disable-ActionButtons {
    $script:startButton.Enabled = $false
    $script:stopButton.Enabled = $false
    $script:openButton.Enabled = $false
}

function Show-OperationProgress {
    param([Parameter(Mandatory)][int]$InitialValue)

    $script:progressBar.Value = [Math]::Max(0, [Math]::Min(100, $InitialValue))
    $script:progressBar.Visible = $true
    $script:progressPercentLabel.Text = "$($script:progressBar.Value)%"
    $script:progressPercentLabel.Visible = $true
}

function Hide-OperationProgress {
    $script:progressBar.Visible = $false
    $script:progressPercentLabel.Visible = $false
    $script:progressHideAt = $null
}

function Set-SteadyStateFromHealth {
    param(
        [Parameter(Mandatory)][bool]$BackendOnline,
        [Parameter(Mandatory)][bool]$FrontendOnline
    )

    if ($BackendOnline -and $FrontendOnline) {
        $script:controllerState = 'Running'
        $script:summaryLabel.Text = '会议系统已就绪'
        $script:summaryLabel.ForeColor = [System.Drawing.Color]::FromArgb(20, 125, 70)
    }
    elseif ($BackendOnline -or $FrontendOnline) {
        $script:controllerState = 'Partial'
        $script:summaryLabel.Text = '部分服务正在运行，请启动恢复或停止服务'
        $script:summaryLabel.ForeColor = [System.Drawing.Color]::FromArgb(190, 110, 0)
    }
    else {
        $script:controllerState = 'Stopped'
        $script:summaryLabel.Text = '会议系统已停止'
        $script:summaryLabel.ForeColor = [System.Drawing.Color]::FromArgb(90, 90, 90)
    }

    Set-ActionButtonsFromHealth -BackendOnline $BackendOnline -FrontendOnline $FrontendOnline
}

function Begin-ControllerOperation {
    param(
        [Parameter(Mandatory)]
        [ValidateSet('Starting', 'Stopping', 'OpeningPage')]
        [string]$State,

        [Parameter(Mandatory)][string]$Message,
        [Parameter(Mandatory)][System.Drawing.Color]$Color
    )

    $script:controllerState = $State
    $script:operationStartedAt = [DateTimeOffset]::UtcNow
    $script:operationProcess = $null
    $script:operationProcessExitObservedAt = $null
    $script:progressHideAt = $null
    $script:errorClearAt = $null
    $script:summaryLabel.Text = $Message
    $script:summaryLabel.ForeColor = $Color
    Disable-ActionButtons
    Show-OperationProgress -InitialValue 5
}

function Complete-ControllerOperation {
    param(
        [Parameter(Mandatory)]
        [ValidateSet('Running', 'Stopped')]
        [string]$FinalState
    )

    $script:controllerState = $FinalState
    $script:operationProcess = $null
    $script:operationProcessExitObservedAt = $null
    $script:progressBar.Value = 100
    $script:progressPercentLabel.Text = '100%'
    $script:progressHideAt = [DateTimeOffset]::UtcNow.AddMilliseconds(800)

    if ($FinalState -eq 'Running') {
        $script:summaryLabel.Text = '会议系统已就绪'
        $script:summaryLabel.ForeColor = [System.Drawing.Color]::FromArgb(20, 125, 70)
    }
    else {
        $script:summaryLabel.Text = '会议系统已停止'
        $script:summaryLabel.ForeColor = [System.Drawing.Color]::FromArgb(90, 90, 90)
    }

    Set-ActionButtonsFromHealth `
        -BackendOnline $script:lastBackendOnline `
        -FrontendOnline $script:lastFrontendOnline
}

function Set-ControllerOperationError {
    param(
        [Parameter(Mandatory)][string]$Message,
        [string]$LogName = ''
    )

    $script:controllerState = 'Error'
    $script:operationProcess = $null
    $script:operationProcessExitObservedAt = $null
    $script:errorClearAt = [DateTimeOffset]::UtcNow.AddSeconds(8)
    $script:summaryLabel.Text = if ($LogName) {
        "$Message，请查看 .smartdesk-runtime\$LogName"
    }
    else {
        $Message
    }
    $script:summaryLabel.ForeColor = [System.Drawing.Color]::FromArgb(180, 40, 40)
    Hide-OperationProgress
    Set-ActionButtonsFromHealth `
        -BackendOnline $script:lastBackendOnline `
        -FrontendOnline $script:lastFrontendOnline
}

function Test-OperationProcessEndedBeyondGrace {
    if ($null -eq $script:operationProcess) {
        return $false
    }

    try {
        if (-not $script:operationProcess.HasExited) {
            $script:operationProcessExitObservedAt = $null
            return $false
        }
    }
    catch {
        return $true
    }

    if ($null -eq $script:operationProcessExitObservedAt) {
        $script:operationProcessExitObservedAt = [DateTimeOffset]::UtcNow
        return $false
    }

    return (
        [DateTimeOffset]::UtcNow - $script:operationProcessExitObservedAt
    ).TotalSeconds -ge 2
}

function Update-ServiceStatus {
    $backendOnline = Test-LocalPort -Port 8000
    $frontendOnline = Test-LocalPort -Port 5173
    $script:lastBackendOnline = $backendOnline
    $script:lastFrontendOnline = $frontendOnline
    Set-StatusLabel -Label $script:backendStatus -Online $backendOnline
    Set-StatusLabel -Label $script:frontendStatus -Online $frontendOnline

    switch ($script:controllerState) {
        'Starting' {
            if ($backendOnline -and $frontendOnline) {
                Complete-ControllerOperation -FinalState 'Running'
            }
            elseif (Test-OperationProcessEndedBeyondGrace) {
                Set-ControllerOperationError `
                    -Message '启动失败' `
                    -LogName 'control-start.log'
            }
            return
        }
        'Stopping' {
            if (-not $backendOnline -and -not $frontendOnline) {
                Complete-ControllerOperation -FinalState 'Stopped'
            }
            elseif (Test-OperationProcessEndedBeyondGrace) {
                Set-ControllerOperationError `
                    -Message '停止失败，仍有服务在线' `
                    -LogName 'control-stop.log'
            }
            return
        }
        'OpeningPage' {
            return
        }
        'Error' {
            Set-ActionButtonsFromHealth `
                -BackendOnline $backendOnline `
                -FrontendOnline $frontendOnline
            if (
                $null -ne $script:errorClearAt -and
                [DateTimeOffset]::UtcNow -ge $script:errorClearAt
            ) {
                $script:errorClearAt = $null
                Set-SteadyStateFromHealth `
                    -BackendOnline $backendOnline `
                    -FrontendOnline $frontendOnline
            }
            return
        }
        default {
            Set-SteadyStateFromHealth `
                -BackendOnline $backendOnline `
                -FrontendOnline $frontendOnline
        }
    }
}

function Update-OperationProgress {
    $now = [DateTimeOffset]::UtcNow

    if ($null -ne $script:progressHideAt -and $now -ge $script:progressHideAt) {
        Hide-OperationProgress
    }

    if ($script:controllerState -notin @('Starting', 'Stopping', 'OpeningPage')) {
        return
    }

    $elapsedMilliseconds = ($now - $script:operationStartedAt).TotalMilliseconds
    $durationMilliseconds = switch ($script:controllerState) {
        'Starting' { 45000 }
        'Stopping' { 12000 }
        'OpeningPage' { 800 }
    }

    if ($script:controllerState -eq 'OpeningPage') {
        $progress = [Math]::Min(
            100,
            5 + [Math]::Floor(($elapsedMilliseconds / $durationMilliseconds) * 95)
        )
    }
    else {
        $progress = [Math]::Min(
            92,
            5 + [Math]::Floor(($elapsedMilliseconds / $durationMilliseconds) * 87)
        )
    }

    $script:progressBar.Value = [int]$progress
    $script:progressPercentLabel.Text = "$progress%"

    if ($script:controllerState -eq 'OpeningPage' -and $progress -ge 100) {
        $script:summaryLabel.Text = '会议页面已打开'
        $script:summaryLabel.ForeColor = [System.Drawing.Color]::FromArgb(20, 125, 70)
        $script:progressHideAt = $now.AddMilliseconds(400)
        Set-SteadyStateFromHealth `
            -BackendOnline $script:lastBackendOnline `
            -FrontendOnline $script:lastFrontendOnline
    }
}

function Show-ControlWindow {
    $script:form.Show()
    if ($script:form.WindowState -eq [System.Windows.Forms.FormWindowState]::Minimized) {
        $script:form.WindowState = [System.Windows.Forms.FormWindowState]::Normal
    }
    $script:form.Activate()
    $script:form.BringToFront()
}

function Hide-ControlWindow {
    $script:form.Hide()
    if (-not $script:hasShownTrayHint) {
        $script:trayIcon.ShowBalloonTip(
            2500,
            'SmartDesk 仍在后台运行',
            '右键托盘图标可重新打开控制窗口或结束程序。',
            [System.Windows.Forms.ToolTipIcon]::Info
        )
        $script:hasShownTrayHint = $true
    }
}

function Open-MeetingPage {
    Begin-ControllerOperation `
        -State 'OpeningPage' `
        -Message '正在打开会议页面…' `
        -Color ([System.Drawing.Color]::FromArgb(35, 90, 165))

    try {
        $processInfo = [System.Diagnostics.ProcessStartInfo]::new()
        $processInfo.FileName = 'http://127.0.0.1:5173'
        $processInfo.UseShellExecute = $true
        [System.Diagnostics.Process]::Start($processInfo) | Out-Null
    }
    catch {
        Set-ControllerOperationError -Message "打开会议页面失败：$($_.Exception.Message)"
    }
}

function Start-MeetingServices {
    Begin-ControllerOperation `
        -State 'Starting' `
        -Message '正在启动会议系统，请稍候…' `
        -Color ([System.Drawing.Color]::FromArgb(35, 90, 165))

    try {
        $script:operationProcess = Start-HiddenBatch -ScriptPath $startScript -LogName 'control-start.log' -EnvironmentVariables @{
            SMARTDESK_CONTROL_MODE = 'true'
            SMARTDESK_SKIP_BROWSER = 'true'
        }
    }
    catch {
        Set-ControllerOperationError `
            -Message "启动失败：$($_.Exception.Message)" `
            -LogName 'control-start.log'
    }
}

function Stop-MeetingServices {
    param([switch]$ExitAfterStop)

    Begin-ControllerOperation `
        -State 'Stopping' `
        -Message '正在停止会议系统…' `
        -Color ([System.Drawing.Color]::FromArgb(190, 80, 0))

    try {
        $script:operationProcess = Start-HiddenBatch -ScriptPath $stopScript -LogName 'control-stop.log' -EnvironmentVariables @{
            SKIP_PAUSE = '1'
        }

        if ($ExitAfterStop) {
            $script:operationProcess.WaitForExit(20000) | Out-Null
        }
    }
    catch {
        if (-not $ExitAfterStop) {
            Set-ControllerOperationError `
                -Message "停止失败：$($_.Exception.Message)" `
                -LogName 'control-stop.log'
        }
    }
}

$script:form = [SmartDeskControlForm]::new()
$script:form.Text = 'SmartDesk 会议控制'
$script:form.StartPosition = [System.Windows.Forms.FormStartPosition]::CenterScreen
$script:form.ClientSize = [System.Drawing.Size]::new(460, 330)
$script:form.FormBorderStyle = [System.Windows.Forms.FormBorderStyle]::FixedSingle
$script:form.MaximizeBox = $false
$script:form.Icon = $appIcon
$script:form.Font = [System.Drawing.Font]::new('Microsoft YaHei UI', 10)
$script:form.BackColor = [System.Drawing.Color]::White

$titleLabel = [System.Windows.Forms.Label]::new()
$titleLabel.Text = '会议系统控制'
$titleLabel.Font = [System.Drawing.Font]::new('Microsoft YaHei UI', 17, [System.Drawing.FontStyle]::Bold)
$titleLabel.AutoSize = $true
$titleLabel.Location = [System.Drawing.Point]::new(28, 24)
$script:form.Controls.Add($titleLabel)

$hintLabel = [System.Windows.Forms.Label]::new()
$hintLabel.Text = '关闭窗口只会隐藏到后台，不会中断会议。'
$hintLabel.AutoSize = $true
$hintLabel.ForeColor = [System.Drawing.Color]::FromArgb(105, 105, 105)
$hintLabel.Location = [System.Drawing.Point]::new(30, 65)
$script:form.Controls.Add($hintLabel)

$backendLabel = [System.Windows.Forms.Label]::new()
$backendLabel.Text = '后端服务'
$backendLabel.AutoSize = $true
$backendLabel.Location = [System.Drawing.Point]::new(31, 105)
$script:form.Controls.Add($backendLabel)

$script:backendStatus = [System.Windows.Forms.Label]::new()
$script:backendStatus.AutoSize = $true
$script:backendStatus.Font = [System.Drawing.Font]::new('Microsoft YaHei UI', 10, [System.Drawing.FontStyle]::Bold)
$script:backendStatus.Location = [System.Drawing.Point]::new(135, 105)
$script:form.Controls.Add($script:backendStatus)

$frontendLabel = [System.Windows.Forms.Label]::new()
$frontendLabel.Text = '前端页面'
$frontendLabel.AutoSize = $true
$frontendLabel.Location = [System.Drawing.Point]::new(251, 105)
$script:form.Controls.Add($frontendLabel)

$script:frontendStatus = [System.Windows.Forms.Label]::new()
$script:frontendStatus.AutoSize = $true
$script:frontendStatus.Font = [System.Drawing.Font]::new('Microsoft YaHei UI', 10, [System.Drawing.FontStyle]::Bold)
$script:frontendStatus.Location = [System.Drawing.Point]::new(355, 105)
$script:form.Controls.Add($script:frontendStatus)

$script:summaryLabel = [System.Windows.Forms.Label]::new()
$script:summaryLabel.AutoSize = $false
$script:summaryLabel.TextAlign = [System.Drawing.ContentAlignment]::MiddleCenter
$script:summaryLabel.Font = [System.Drawing.Font]::new('Microsoft YaHei UI', 11, [System.Drawing.FontStyle]::Bold)
$script:summaryLabel.Location = [System.Drawing.Point]::new(25, 137)
$script:summaryLabel.Size = [System.Drawing.Size]::new(410, 32)
$script:form.Controls.Add($script:summaryLabel)

$script:progressBar = [System.Windows.Forms.ProgressBar]::new()
$script:progressBar.Minimum = 0
$script:progressBar.Maximum = 100
$script:progressBar.Style = [System.Windows.Forms.ProgressBarStyle]::Continuous
$script:progressBar.Location = [System.Drawing.Point]::new(29, 177)
$script:progressBar.Size = [System.Drawing.Size]::new(360, 18)
$script:progressBar.Visible = $false
$script:form.Controls.Add($script:progressBar)

$script:progressPercentLabel = [System.Windows.Forms.Label]::new()
$script:progressPercentLabel.AutoSize = $false
$script:progressPercentLabel.TextAlign = [System.Drawing.ContentAlignment]::MiddleRight
$script:progressPercentLabel.Location = [System.Drawing.Point]::new(396, 174)
$script:progressPercentLabel.Size = [System.Drawing.Size]::new(38, 23)
$script:progressPercentLabel.Visible = $false
$script:form.Controls.Add($script:progressPercentLabel)

$script:startButton = [System.Windows.Forms.Button]::new()
$script:startButton.Text = '启动程序'
$script:startButton.Location = [System.Drawing.Point]::new(29, 220)
$script:startButton.Size = [System.Drawing.Size]::new(125, 42)
$script:startButton.BackColor = [System.Drawing.Color]::FromArgb(40, 120, 210)
$script:startButton.ForeColor = [System.Drawing.Color]::White
$script:startButton.FlatStyle = [System.Windows.Forms.FlatStyle]::Flat
$script:startButton.Add_Click({ Start-MeetingServices })
$script:form.Controls.Add($script:startButton)

$script:stopButton = [System.Windows.Forms.Button]::new()
$script:stopButton.Text = '停止程序'
$script:stopButton.Location = [System.Drawing.Point]::new(168, 220)
$script:stopButton.Size = [System.Drawing.Size]::new(125, 42)
$script:stopButton.Add_Click({
    $choice = [System.Windows.Forms.MessageBox]::Show(
        '确定停止会议服务吗？控制窗口会继续留在后台。',
        '停止会议服务',
        [System.Windows.Forms.MessageBoxButtons]::YesNo,
        [System.Windows.Forms.MessageBoxIcon]::Question
    )
    if ($choice -eq [System.Windows.Forms.DialogResult]::Yes) {
        Stop-MeetingServices
    }
})
$script:form.Controls.Add($script:stopButton)

$script:openButton = [System.Windows.Forms.Button]::new()
$script:openButton.Text = '打开会议页面'
$script:openButton.Location = [System.Drawing.Point]::new(307, 220)
$script:openButton.Size = [System.Drawing.Size]::new(125, 42)
$script:openButton.Add_Click({ Open-MeetingPage })
$script:form.Controls.Add($script:openButton)

$footerLabel = [System.Windows.Forms.Label]::new()
$footerLabel.Text = '完全退出：右键任务栏托盘图标，选择“结束程序”'
$footerLabel.AutoSize = $true
$footerLabel.ForeColor = [System.Drawing.Color]::FromArgb(105, 105, 105)
$footerLabel.Location = [System.Drawing.Point]::new(31, 287)
$script:form.Controls.Add($footerLabel)

$trayMenu = [System.Windows.Forms.ContextMenuStrip]::new()
$showMenuItem = $trayMenu.Items.Add('显示控制窗口')
$openMenuItem = $trayMenu.Items.Add('打开会议页面')
$trayMenu.Items.Add([System.Windows.Forms.ToolStripSeparator]::new()) | Out-Null
$exitMenuItem = $trayMenu.Items.Add('结束程序')

$script:trayIcon = [System.Windows.Forms.NotifyIcon]::new()
$script:trayIcon.Text = 'SmartDesk 会议控制'
$script:trayIcon.Icon = $appIcon
$script:trayIcon.ContextMenuStrip = $trayMenu
$script:trayIcon.Visible = $true

$showMenuItem.Add_Click({ Show-ControlWindow })
$openMenuItem.Add_Click({ Open-MeetingPage })
$exitMenuItem.Add_Click({
    $choice = [System.Windows.Forms.MessageBox]::Show(
        '结束程序会停止会议服务并退出控制窗口，是否继续？',
        '结束 SmartDesk',
        [System.Windows.Forms.MessageBoxButtons]::YesNo,
        [System.Windows.Forms.MessageBoxIcon]::Warning
    )
    if ($choice -eq [System.Windows.Forms.DialogResult]::Yes) {
        $script:form.Hide()
        Stop-MeetingServices -ExitAfterStop
        $script:allowExit = $true
        $script:form.AllowExit = $true
        $script:trayIcon.Visible = $false
        [System.Windows.Forms.Application]::Exit()
    }
})
$script:trayIcon.Add_DoubleClick({ Show-ControlWindow })

$script:form.Add_Resize({
    if ($script:form.WindowState -eq [System.Windows.Forms.FormWindowState]::Minimized) {
        Hide-ControlWindow
    }
})

$statusTimer = [System.Windows.Forms.Timer]::new()
$statusTimer.Interval = 1500
$statusTimer.Add_Tick({ Update-ServiceStatus })
$statusTimer.Start()

$progressTimer = [System.Windows.Forms.Timer]::new()
$progressTimer.Interval = 100
$progressTimer.Add_Tick({ Update-OperationProgress })
$progressTimer.Start()

try {
    Update-ServiceStatus
    [System.Windows.Forms.Application]::EnableVisualStyles()
    $script:form.Show()
    [System.Windows.Forms.Application]::Run()
}
finally {
    $statusTimer.Stop()
    $statusTimer.Dispose()
    $progressTimer.Stop()
    $progressTimer.Dispose()
    $script:trayIcon.Visible = $false
    $script:trayIcon.Dispose()
    $trayMenu.Dispose()
    $script:form.Dispose()
    if ($ownsAppIcon) {
        $appIcon.Dispose()
    }
    if ($createdNew) {
        try { $mutex.ReleaseMutex() } catch { }
    }
    $mutex.Dispose()
}
