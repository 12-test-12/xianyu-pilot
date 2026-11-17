# QQ NT accessibility selectors are documented by treers2/qq-operations.
$ErrorActionPreference = 'Stop'
$inputData = [Console]::In.ReadToEnd() | ConvertFrom-Json
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes, System.Windows.Forms
Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class XianyuQQWindow {
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr window);
    [DllImport("user32.dll")] public static extern bool ShowWindowAsync(IntPtr window, int action);
    [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr window);
    [DllImport("user32.dll")] public static extern uint GetClipboardSequenceNumber();
    [DllImport("user32.dll")] public static extern void mouse_event(uint flags, uint x, uint y, uint data, UIntPtr extra);
}
'@

$descendants = [Windows.Automation.TreeScope]::Descendants
$walker = [Windows.Automation.TreeWalker]::ControlViewWalker

function Find-Control($root, $property, $value) {
    $condition = [Windows.Automation.PropertyCondition]::new($property, $value)
    $root.FindAll($descendants, $condition) | Where-Object { -not $_.Current.IsOffscreen -and $_.Current.IsEnabled }
}

function Find-Class($root, $class) {
    Find-Control $root ([Windows.Automation.AutomationElement]::ClassNameProperty) $class
}

function Find-Type($root, $type) {
    Find-Control $root ([Windows.Automation.AutomationElement]::ControlTypeProperty) $type
}

function Get-ValuePattern($element) {
    $pattern = $null
    if ($element.TryGetCurrentPattern([Windows.Automation.ValuePattern]::Pattern, [ref]$pattern)) { $pattern }
}

function Read-Editor($editor) {
    $text = $null
    if ($editor.TryGetCurrentPattern([Windows.Automation.TextPattern]::Pattern, [ref]$text)) {
        $content = $text.DocumentRange.GetText(600).TrimEnd("`r", "`n")
        if ($content) { return $content }
    }
    $value = Get-ValuePattern $editor
    if ($value) { return [string]$value.Current.Value }
    if ($text) { return '' }
}

function Test-Within($child, $parent) {
    for ($depth = 0; $child -and $depth -lt 12; $depth++) {
        if ($child.Equals($parent)) { return $true }
        $child = $walker.GetParent($child)
    }
    return $false
}

function Test-SearchResult($node) {
    $inSearch = $false
    for ($depth = 0; $node -and $depth -lt 8; $depth++) {
        $name = $node.Current.Name
        $class = $node.Current.ClassName
        if ($name -match '^(\u7fa4\u804a|\u6d88\u606f\u8bb0\u5f55|\u7f51\u7edc\u641c\u7d22)' -or $class -match '(?i)search.*(group|message|network)') { return $false }
        if ($name -match '^(\u8054\u7cfb\u4eba|\u597d\u53cb)$' -or $class -match '(?i)search.*(result|list|panel|item|container)') { $inSearch = $true }
        $node = $walker.GetParent($node)
    }
    return $inSearch
}

function Paste-Editor($editor, $window, [string]$text) {
    $editor.SetFocus()
    if ([XianyuQQWindow]::GetForegroundWindow() -ne $window -or
        -not (Test-Within ([Windows.Automation.AutomationElement]::FocusedElement) $editor) -or
        (Read-Editor $editor) -cne '') { return $false }
    $previous = [Windows.Forms.Clipboard]::GetDataObject()
    $saved = $null
    if ($null -ne $previous) {
        $saved = [System.Windows.Forms.DataObject]::new()
        foreach ($format in $previous.GetFormats()) {
            try {
                $data = $previous.GetData($format, $true)
                if ($null -ne $data) { $saved.SetData($format, $data) }
            } catch {}
        }
    }
    [Windows.Forms.Clipboard]::SetText($text)
    $sequence = [XianyuQQWindow]::GetClipboardSequenceNumber()
    try {
        if ([XianyuQQWindow]::GetForegroundWindow() -ne $window -or
            -not (Test-Within ([Windows.Automation.AutomationElement]::FocusedElement) $editor)) { return $false }
        [Windows.Forms.SendKeys]::SendWait('^v')
        Start-Sleep -Milliseconds 220
        return $true
    } finally {
        if ([XianyuQQWindow]::GetClipboardSequenceNumber() -eq $sequence) {
            if ($null -eq $saved -or $saved.GetFormats().Length -eq 0) { [Windows.Forms.Clipboard]::Clear() }
            else { [Windows.Forms.Clipboard]::SetDataObject($saved, $true) }
        }
    }
}

function Open-QQDraft {
    $processes = @(Get-Process -Name QQ -ErrorAction SilentlyContinue)
    if (-not $processes.Count) { return 'qq_closed' }
    $foreground = [XianyuQQWindow]::GetForegroundWindow()
    $panels = @([Windows.Automation.AutomationElement]::RootElement.FindAll(
        [Windows.Automation.TreeScope]::Children, [Windows.Automation.Condition]::TrueCondition
    ) | Where-Object { $_.Current.Name -ceq 'QQ' -and $_.Current.ProcessId -in $processes.Id -and $_.Current.NativeWindowHandle })
    $active = @($panels | Where-Object { [IntPtr]$_.Current.NativeWindowHandle -eq $foreground })
    if ($active.Count -eq 1) { $panel = $active[0] }
    elseif ($panels.Count -eq 1) { $panel = $panels[0] }
    else { return 'qq_unavailable' }

    $handle = [IntPtr]$panel.Current.NativeWindowHandle
    if ([XianyuQQWindow]::IsIconic($handle)) { [void][XianyuQQWindow]::ShowWindowAsync($handle, 9) }
    [void][XianyuQQWindow]::SetForegroundWindow($handle)
    for ($attempt = 0; $attempt -lt 12; $attempt++) {
        Start-Sleep -Milliseconds 250
        if ([XianyuQQWindow]::GetForegroundWindow() -eq $handle) { break }
    }
    if ([XianyuQQWindow]::GetForegroundWindow() -ne $handle) { return 'qq_unavailable' }
    $panel = [Windows.Automation.AutomationElement]::FromHandle($handle)
    $edits = @(Find-Type $panel ([Windows.Automation.ControlType]::Edit))
    if ($edits | Where-Object { $_.Current.IsPassword }) { return 'qq_closed' }
    $search = @($edits | Where-Object { $_.Current.ClassName -match '(?i)search' -or $_.Current.Name -match '^(\u641c\u7d22|Search)' })
    if ($search.Count -ne 1) { return 'qq_unavailable' }
    $search = $search[0]
    $searchValue = Get-ValuePattern $search
    if (-not $searchValue -or $searchValue.Current.IsReadOnly) { return 'qq_unavailable' }
    $number = [string]$inputData.robotQq
    $label = [string]$inputData.robotName
    $numberPattern = '(?<!\d)' + [regex]::Escape($number) + '(?!\d)'
    if ($searchValue.Current.Value -cne $number) {
        if ([XianyuQQWindow]::GetForegroundWindow() -ne $handle) { return 'qq_unavailable' }
        $search.SetFocus()
        $searchValue.SetValue('')
        if ($searchValue.Current.Value -or -not (Paste-Editor $search $handle $number)) { return 'qq_unavailable' }
    }

    $result = $null
    for ($attempt = 0; $attempt -lt 12; $attempt++) {
        Start-Sleep -Milliseconds 250
        if ([XianyuQQWindow]::GetForegroundWindow() -ne $handle) { return 'qq_unavailable' }
        if ($searchValue.Current.Value -cne $number) { continue }
        $rows = @(Find-Type $panel ([Windows.Automation.ControlType]::ListItem) | Where-Object {
            ($_.Current.Name -match $numberPattern -or ($label -and $_.Current.Name -ceq $label)) -and (Test-SearchResult $_)
        })
        if ($rows.Count -gt 1) { return 'contact_not_found' }
        if ($rows.Count -eq 1) { $result = $rows[0]; break }
    }
    if (-not $result -or [XianyuQQWindow]::GetForegroundWindow() -ne $handle) { return 'contact_not_found' }
    if ($result.Current.Name -match $numberPattern) {
        $bracketPattern = '[\s(（\[【:：-]*' + $numberPattern + '[\s)）\]】:：-]*'
        $trimChars = [char[]]@(' ', '(', ')', '[', ']', ':', '-', [char]0xff08, [char]0xff09, [char]0x3010, [char]0x3011, [char]0xff1a, [char]0x3000)
        $resultLabel = ($result.Current.Name -replace $bracketPattern, '').Trim($trimChars)
        if ($resultLabel) { $label = $resultLabel }
    }
    if (-not $label) { $label = $number }
    $invoke = $null
    if ($result.TryGetCurrentPattern([Windows.Automation.InvokePattern]::Pattern, [ref]$invoke)) {
        $invoke.Invoke()
    } else {
        $point = $result.GetClickablePoint()
        if ([XianyuQQWindow]::GetForegroundWindow() -ne $handle -or
            -not (Test-Within ([Windows.Automation.AutomationElement]::FromPoint($point)) $result)) { return 'contact_not_found' }
        [Windows.Forms.Cursor]::Position = [Drawing.Point]::new([int]$point.X, [int]$point.Y)
        [XianyuQQWindow]::mouse_event(6, 0, 0, 0, [UIntPtr]::Zero)
    }

    for ($attempt = 0; $attempt -lt 12; $attempt++) {
        Start-Sleep -Milliseconds 250
        $chatHandle = [XianyuQQWindow]::GetForegroundWindow()
        if ($chatHandle -eq [IntPtr]::Zero) { continue }
        $root = [Windows.Automation.AutomationElement]::FromHandle($chatHandle)
        if ($root.Current.ProcessId -notin $processes.Id) { return 'chat_not_verified' }
        $headers = @(Find-Class $root 'chat-header__contact-name')
        $editors = @(Find-Class $root 'qq-msg-editor')
        if ($headers.Count -ne 1 -or $headers[0].Current.Name -cne $label -or $editors.Count -ne 1) { continue }
        $editor = $editors[0]
        $oldValue = Read-Editor $editor
        if ($null -eq $oldValue) { return 'chat_not_verified' }
        if ($oldValue -ceq $inputData.command) { return 'draft_ready' }
        if ($oldValue.Length) { return 'draft_exists' }
        if ($headers[0].Current.Name -cne $label -or (Read-Editor $editor) -cne '' -or
            -not (Paste-Editor $editor $chatHandle $inputData.command)) { return 'chat_not_verified' }
        if ($headers[0].Current.Name -ceq $label -and (Read-Editor $editor) -ceq $inputData.command) { return 'draft_ready' }
        return 'chat_not_verified'
    }
    return 'chat_not_verified'
}

try { Open-QQDraft } catch { 'chat_not_verified' }
