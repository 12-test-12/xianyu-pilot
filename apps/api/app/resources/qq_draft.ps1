# QQ NT accessibility selectors are documented by treers2/qq-operations.
param([string]$helperPath)

$ErrorActionPreference = 'Stop'
$inputData = [Console]::In.ReadToEnd() | ConvertFrom-Json
try {
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -Path $helperPath
    $automation = [QQAutomation]::new()
} catch {
    [Console]::Out.WriteLine('qq_helper_unavailable')
    return
}

function Find-Class($root, $class) {
    $automation.Find($root, [QQAutomation]::ClassNameProperty, $class)
}

function Find-Type($root, $type) {
    $automation.Find($root, [QQAutomation]::ControlTypeProperty, $type)
}

function Test-Within($child, $parent) {
    for ($depth = 0; $child -and $depth -lt 12; $depth++) {
        if ($automation.Same($child, $parent)) { return $true }
        $child = $automation.Parent($child)
    }
    return $false
}

function Get-QQSearchAtPoint($panel, $point) {
    $control = $automation.FromPoint($point)
    for ($depth = 0; $control -and $depth -lt 8; $depth++) {
        if ($control.ControlType -in @([QQAutomation]::Edit, [QQAutomation]::ComboBox) -and
            -not $control.IsPassword -and (Test-Within $control $panel)) { return $control }
        $control = $automation.Parent($control)
    }
}

function Get-SearchResultKind($node) {
    if ($node.Name -match '^\s*(?:(?:\u8fdb\u5165)?(?:\u7efc\u5408\u641c\u7d22|\u7f51\u7edc\u641c\u7d22)(?:$|[0-9\s:\uFF1A]|\u67e5\u627e)|\u67e5\u627e\s*(?:\u7528\u6237|\u7fa4\u804a)(?:$|[\s:\uFF1A]))') { return 'excluded' }
    $inContact = $false
    for ($depth = 0; $node -and $depth -lt 8; $depth++) {
        $name = $node.Name
        $class = $node.ClassName
        if ($name -match '^(?:\u7fa4\u804a|\u6d88\u606f\u8bb0\u5f55|\u7f51\u7edc\u641c\u7d22)(?:$|[\s:\uFF1A(\uFF08])' -or
            $class -match '(?i)search.*(group|message|network)') { return 'excluded' }
        if ($name -match '^(\u8054\u7cfb\u4eba|\u597d\u53cb)$' -or $class -match '(?i)search.*(result|list|panel|item|container)') { $inContact = $true }
        $node = $automation.Parent($node)
    }
    if ($inContact) { return 'contact' }
    return 'unknown'
}

function Get-QQChatControls($root, [string]$label) {
    $headers = @(Find-Class $root 'chat-header__contact-name')
    $editors = @(Find-Class $root 'qq-msg-editor')
    if (-not $headers.Count) {
        $headers = @(Find-Type $root ([QQAutomation]::Button) | Where-Object Name -CEQ $label)
    }
    if (-not $editors.Count) {
        $editors = @(Find-Type $root ([QQAutomation]::Edit) | Where-Object Name -CEQ $label)
    }
    if ($headers.Count -eq 1 -and $headers[0].Name -ceq $label -and $editors.Count -eq 1) {
        return @{ Header = $headers[0]; Editor = $editors[0] }
    }
}

function Get-QQMessageBubbles($root) {
    $messageClass = '^(?:message-container|msg-content-container)(?:--[^\s]+)?(?:\s|$)'
    $messages = [ordered]@{}
    foreach ($bubble in $automation.MessageContainers($root)) {
        if ($bubble.ClassName -notmatch $messageClass) { continue }
        $self = $bubble.ClassName -match 'container--self'
        $outer = $bubble
        $parent = $automation.Parent($bubble)
        for ($depth = 0; $parent -and $depth -lt 8; $depth++) {
            if ($parent.ClassName -match $messageClass) { $outer = $parent }
            if ($parent.ClassName -match 'container--self') { $self = $true }
            $parent = $automation.Parent($parent)
        }
        $id = $outer.RuntimeId
        if (-not $id) { continue }
        if (-not $messages.Contains($id)) { $messages[$id] = @{ Control = $outer; Self = $false } }
        if ($self) { $messages[$id].Self = $true }
    }
    foreach ($id in $messages.Keys) {
        $message = $messages[$id]
        $text = ((Find-Type $message.Control ([QQAutomation]::Text)) | ForEach-Object { $_.Name } | Where-Object { $_ }) -join ' '
        if ($text) { [pscustomobject]@{ Id = $id; Self = $message.Self; Text = $text.Trim() } }
    }
}

function Get-QQReceiptState([string]$text, [string]$target) {
    if ($target -notmatch '^[0-9]{5,20}$') { return }
    $number = '(?<!\d)' + [regex]::Escape($target) + '(?!\d)'
    $numbers = @([regex]::Matches($text, '(?<!\d)[0-9]{5,20}(?!\d)').Value | Select-Object -Unique)
    if ($numbers.Count -ne 1 -or $numbers[0] -cne $target) { return }
    $trim = [char[]]@(' ', "`r", "`n", "`t", ':', '[', ']', '(', ')', '!', '.', ',', [char]0xFF1A, [char]0x3002, [char]0xFF01, [char]0xFF0C)
    $result = ($text -replace ('(?:(?:\u76ee\u6807)?\u7403\u7403\u53f7\s*[:\uFF1A]?\s*)?' + $number), '').Trim($trim)
    if ($result -match '^(?:\u52a9\u529b\u6210\u529f|\u5df2\u52a9\u529b(?:\u6210\u529f)?|\u5df2\u6210\u529f\u62c9\u6ee1)$') { return 'receipt_success' }
    if ($result -match '^(?:(?:\u5df2)?\u8fbe\u5230\u4e0a\u9650|\u52a9\u529b\u5df2\u8fbe\u4e0a\u9650|\u6b21\u6570\u5df2\u7528\u5b8c|\u4eca\u65e5\u5df2\u6ee1|\u4eca\u65e5\u52a9\u529b\u6b21\u6570\u5df2\u7528\u5b8c)$') { return 'receipt_capped' }
}

function Find-QQReceipt($baseline, $current, [string]$command, [string]$target) {
    if ($baseline | Where-Object { $_.Self -and $_.Text -ceq $command }) { return }
    if ($baseline.Count) {
        # A changed message viewport can give old bubbles new runtime IDs.
        $lastKnown = [Array]::IndexOf(@($current.Id), $baseline[-1].Id)
        if ($lastKnown -lt 0) { return }
        $current = @($current | Select-Object -Skip ($lastKnown + 1))
    }
    $newBubbles = @($current | Where-Object { $_.Id -notin $baseline.Id })
    $own = @($newBubbles | Where-Object { $_.Self -and $_.Text -ceq $command })
    if ($own.Count -ne 1) { return }
    $afterCommand = $false
    $states = @(foreach ($bubble in $newBubbles) {
        if ($bubble.Self) { $afterCommand = $bubble.Id -eq $own[0].Id; continue }
        if ($afterCommand) { Get-QQReceiptState $bubble.Text $target }
    })
    $states = @($states | Select-Object -Unique)
    if ($states.Count -eq 1) { return $states[0] }
}

function Find-QQContact($panel, [string]$number, [string]$label) {
    $numberPattern = '(?<!\d)' + [regex]::Escape($number) + '(?!\d)'
    $fieldsPattern = '^(?:(?:QQ|\u8d26\u53f7|\u5e10\u53f7)\s*[:\uFF1A]?\s*)?' + [regex]::Escape($number) + '$'
    $candidates = @(foreach ($row in (Find-Type $panel ([QQAutomation]::ListItem))) {
        $kind = Get-SearchResultKind $row
        if ($kind -eq 'excluded') { continue }

        $fields = @((Find-Type $row ([QQAutomation]::Text)).Name | Where-Object { $_ })
        $hasNumberField = @($fields | Where-Object { $_ -match $fieldsPattern }).Count -gt 0
        $exact = $row.Name -match $numberPattern -or $hasNumberField
        if (-not $exact -and (-not $label -or $row.Name -cne $label)) { continue }
        $names = @($fields | Where-Object {
            $_ -notmatch $fieldsPattern -and $_ -notmatch '^(?:[()\uFF08\uFF09]|\u6765\u81ea\s*[:\uFF1A].*)$'
        } | Select-Object -Unique)
        $observedLabel = if ($label -and $label -cin $names) { $label } elseif ($names.Count -eq 1) { $names[0] }
        # Some QQ builds expose the result as an unnamed list. Require a dedicated number field there.
        if ($kind -ne 'contact' -and (-not $observedLabel -or -not $hasNumberField)) { continue }
        if (-not $observedLabel -and $row.Name -match $numberPattern) {
            $brackets = '[\s\(\[\:\-\uFF08\u3010\uFF1A]*' + $numberPattern + '[\s\)\]\:\-\uFF09\u3011\uFF1A-]*'
            $observedLabel = ($row.Name -replace $brackets, '').Trim()
        }
        if (-not $observedLabel) { $observedLabel = $label }
        if ($observedLabel) { [pscustomobject]@{ Control = $row; Label = $observedLabel; ExactNumber = $exact } }
    })
    $exactMatches = @($candidates | Where-Object ExactNumber)
    if ($exactMatches.Count) { $candidates = $exactMatches }
    if ($candidates.Count -eq 1) { return $candidates[0] }
}

function Paste-Editor($editor, $window, [string]$text) {
    try { $editor.SetFocus() } catch [Runtime.InteropServices.COMException] {}
    if ([XianyuQQWindow]::GetForegroundWindow() -ne $window -or $editor.ReadEditor() -cne '') { return $false }
    if (-not (Test-Within ($automation.Focused()) $editor)) {
        # QQ may keep accessibility focus on the document even while the input caret is visible.
        if (-not $editor.TrySetValue($text)) { return $false }
        return $editor.ReadEditor() -ceq $text
    }
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
            -not (Test-Within ($automation.Focused()) $editor)) { return $false }
        if (-not [XianyuQQWindow]::Paste($window)) { return $false }
        for ($attempt = 0; $attempt -lt 8; $attempt++) {
            Start-Sleep -Milliseconds 100
            if ($editor.ReadEditor() -ceq $text) { return $true }
        }
        return $false
    } finally {
        if ([XianyuQQWindow]::GetClipboardSequenceNumber() -eq $sequence) {
            if ($null -eq $saved -or $saved.GetFormats().Length -eq 0) { [Windows.Forms.Clipboard]::Clear() }
            else { [Windows.Forms.Clipboard]::SetDataObject($saved, $true) }
        }
    }
}

function Click-QQControl($control, $window) {
    $point = $control.Center()
    if ($null -eq $point -or -not (Test-Within ($automation.FromPoint($point)) $control) -or
        [XianyuQQWindow]::GetForegroundWindow() -ne $window) { return $false }
    [Windows.Forms.Cursor]::Position = [Drawing.Point]::new($point.X, $point.Y)
    [XianyuQQWindow]::mouse_event(6, 0, 0, 0, [UIntPtr]::Zero)
    return $true
}

function Get-QQWindowBinding($window) {
    $owner = [XianyuQQWindow]::ProcessId($window)
    $process = Get-Process -Id $owner -ErrorAction SilentlyContinue
    if ($process -and $process.ProcessName -eq 'QQ') {
        return 'window:{0}:{1}:{2}' -f $window.ToInt64(), $owner, $process.StartTime.ToUniversalTime().Ticks
    }
}

function Submit-QQCommand($root, $header, $editor, $window, $label) {
    if ([XianyuQQWindow]::GetForegroundWindow() -ne $window -or
        $header.Name -cne $label -or $editor.ReadEditor() -cne $inputData.command) { return 'qq_send_unavailable' }

    $targetNumber = [string]$inputData.value
    $readReceipt = $targetNumber -match '^[0-9]{5,20}$' -and
        $inputData.command -cmatch ('^\u52a9\u529b ' + $targetNumber + '\z')
    if ($readReceipt) {
        try { $baseline = @(Get-QQMessageBubbles $root) }
        catch { $readReceipt = $false }
    }

    if ([XianyuQQWindow]::GetForegroundWindow() -ne $window) { return 'qq_send_unavailable' }
    $root = $automation.FromHandle($window)
    $chat = Get-QQChatControls $root $label
    if (-not $chat -or -not $automation.Same($chat.Header, $header) -or
        -not $automation.Same($chat.Editor, $editor)) { return 'qq_send_unavailable' }
    $buttons = @(Find-Type $root ([QQAutomation]::Button) | Where-Object { $_.Name -match '^(\u53d1\u9001|Send)$' })
    if ($buttons.Count -ne 1 -or $chat.Header.Name -cne $label -or
        $chat.Editor.ReadEditor() -cne $inputData.command -or
        [XianyuQQWindow]::GetForegroundWindow() -ne $window) { return 'qq_send_unavailable' }

    $script:submitAttempted = $true
    if (-not (Click-QQControl $buttons[0] $window)) {
        if ($chat.Header.Name -cne $label -or $chat.Editor.ReadEditor() -cne $inputData.command -or
            [XianyuQQWindow]::GetForegroundWindow() -ne $window -or
            -not $buttons[0].TryInvoke()) { return 'qq_send_unavailable' }
    }
    $sentConfirmed = $false
    for ($attempt = 0; $attempt -lt 12; $attempt++) {
        Start-Sleep -Milliseconds 150
        if ([XianyuQQWindow]::GetForegroundWindow() -ne $window -or $chat.Header.Name -cne $label) { break }
        if ($chat.Editor.ReadEditor() -ceq '') { $sentConfirmed = $true; break }
    }
    if (-not $sentConfirmed) { return 'send_uncertain' }

    [Console]::Out.WriteLine('send_confirmed')
    [Console]::Out.Flush()
    if ($readReceipt) {
        try {
            for ($attempt = 0; $attempt -lt 20; $attempt++) {
                Start-Sleep -Milliseconds 250
                if ([XianyuQQWindow]::GetForegroundWindow() -ne $window -or $chat.Header.Name -cne $label) { break }
                $receipt = Find-QQReceipt $baseline @(Get-QQMessageBubbles $root) $inputData.command $targetNumber
                if (-not $receipt) { continue }
                $currentChat = Get-QQChatControls ($automation.FromHandle($window)) $label
                if ($currentChat -and $automation.Same($currentChat.Header, $chat.Header) -and
                    $automation.Same($currentChat.Editor, $chat.Editor) -and
                    [XianyuQQWindow]::GetForegroundWindow() -eq $window) { return $receipt }
                break
            }
        } catch {
            # The editor already cleared. An unreadable receipt cannot undo the submission.
        }
    }
    return 'submitted'
}

function Open-QQDraft {
    $processes = @(Get-Process -Name QQ -ErrorAction SilentlyContinue)
    if (-not $processes.Count) { return 'qq_closed' }
    $panels = @(
        $window = [IntPtr]::Zero
        while ($true) {
            $window = [XianyuQQWindow]::NextQQWindow($window)
            if ($window -eq [IntPtr]::Zero) { break }
            if ([XianyuQQWindow]::IsWindowVisible($window) -and [XianyuQQWindow]::ProcessId($window) -in $processes.Id) { $window }
        }
    )
    if (-not $panels.Count) { return 'qq_window_missing' }
    $binding = $inputData.operation -eq 'bind'
    $sending = $inputData.operation -eq 'send'
    $otherPanels = @()
    if ($sending) {
        $boundPanels = @($panels | Where-Object { (Get-QQWindowBinding $_) -ceq $inputData.window })
        $otherPanels = @($panels | Where-Object { $_ -notin $boundPanels })
        $panels = $boundPanels
        if ($panels.Count -ne 1) { return 'qq_account_unbound' }
    }
    $foreground = [XianyuQQWindow]::GetForegroundWindow()
    if (-not $binding -and $panels.Count -eq 1 -and $foreground -notin $panels) {
        if ([XianyuQQWindow]::IsIconic($panels[0])) {
            [void][XianyuQQWindow]::ShowWindowAsync($panels[0], 9)
            Start-Sleep -Milliseconds 250
        }
        [void][XianyuQQWindow]::SetForegroundWindow($panels[0])
    }
    $focusAttempts = if ($binding) { 64 } else { 24 }
    for ($attempt = 0; $attempt -lt $focusAttempts; $attempt++) {
        $handle = [XianyuQQWindow]::GetForegroundWindow()
        if ($handle -in $panels) { break }
        Start-Sleep -Milliseconds 250
    }
    if ($handle -notin $panels) { return 'qq_unavailable' }
    if ($binding) { return Get-QQWindowBinding $handle }

    $search = $null
    # QQ may populate the accessible controls only after reaching the foreground.
    for ($attempt = 0; $attempt -lt 12; $attempt++) {
        if ([XianyuQQWindow]::GetForegroundWindow() -ne $handle) { return 'qq_unavailable' }
        $panel = $automation.FromHandle($handle)
        $inputs = @(
            Find-Type $panel ([QQAutomation]::Edit)
            Find-Type $panel ([QQAutomation]::ComboBox)
        )
        if ($inputs | Where-Object IsPassword) { return 'qq_closed' }
        $matches = @($inputs | Where-Object { $_.ClassName -match '(?i)search' -or $_.Name -match '^(\u641c\u7d22|Search)' })
        if ($matches.Count -eq 1) {
            $search = $matches[0]
            break
        }
        Start-Sleep -Milliseconds 250
    }
    if (-not $search) { return 'qq_search_unavailable' }
    $number = [string]$inputData.robotQq
    $label = [string]$inputData.robotName
    # QQ's combo box can report a value without triggering the search panel.
    $searchPoint = $search.Center()
    if (-not (Click-QQControl $search $handle)) { return 'qq_search_unavailable' }
    # QQ can replace the search field on activation and report focus on its enclosing document.
    $search = $null
    for ($attempt = 0; $attempt -lt 6; $attempt++) {
        Start-Sleep -Milliseconds 100
        if ([XianyuQQWindow]::GetForegroundWindow() -ne $handle) { return 'qq_unavailable' }
        $panel = $automation.FromHandle($handle)
        $candidate = Get-QQSearchAtPoint $panel $searchPoint
        $focused = $automation.Focused()
        if ($candidate -and $focused -and ((Test-Within $focused $candidate) -or (Test-Within $candidate $focused))) {
            $search = $candidate
            break
        }
    }
    if (-not $search -or -not [XianyuQQWindow]::SearchNumber($handle, $number)) {
        return 'qq_search_unavailable'
    }

    $result = $null
    $queryVisible = $false
    $enterTried = $false
    for ($attempt = 0; $attempt -lt 16; $attempt++) {
        Start-Sleep -Milliseconds 250
        if ([XianyuQQWindow]::GetForegroundWindow() -ne $handle) { return 'qq_unavailable' }
        $panel = $automation.FromHandle($handle)
        $search = Get-QQSearchAtPoint $panel $searchPoint
        if (-not $search -or ($search.Value -cne $number -and $search.ReadEditor() -cne $number)) { continue }
        $queryVisible = $true
        $match = Find-QQContact $panel $number $label
        if ($match -and (-not $sending -or $match.ExactNumber)) { $result = $match; break }
        if ($attempt -ge 7 -and -not $enterTried -and (Test-Within ($automation.Focused()) $search)) {
            $enterTried = $true
            if (-not [XianyuQQWindow]::SearchEnter($handle)) { return 'qq_search_unavailable' }
        }
    }
    if (-not $queryVisible) { return 'qq_search_not_entered' }
    if (-not $result -or [XianyuQQWindow]::GetForegroundWindow() -ne $handle) { return 'contact_not_found' }
    $label = $result.Label
    if ([XianyuQQWindow]::GetForegroundWindow() -ne $handle) { return 'qq_unavailable' }
    # QQ can expose Invoke on a result without opening its private conversation.
    if (-not (Click-QQControl $result.Control $handle) -and
        ([XianyuQQWindow]::GetForegroundWindow() -ne $handle -or -not $result.Control.TryInvoke())) {
        return 'contact_not_opened'
    }

    for ($attempt = 0; $attempt -lt 12; $attempt++) {
        Start-Sleep -Milliseconds 250
        $chatHandle = [XianyuQQWindow]::GetForegroundWindow()
        if ($chatHandle -eq [IntPtr]::Zero) { continue }
        $chatOwner = [XianyuQQWindow]::ProcessId($chatHandle)
        if ($chatOwner -notin $processes.Id) { continue }
        if ($sending -and $chatHandle -ne $handle) {
            if ($chatHandle -in $otherPanels -or $chatOwner -ne [XianyuQQWindow]::ProcessId($handle)) { continue }
            if ([XianyuQQWindow]::GetAncestor($chatHandle, 3) -ne $handle -and
                ($otherPanels | Where-Object { [XianyuQQWindow]::ProcessId($_) -eq $chatOwner })) { continue }
        }
        $root = $automation.FromHandle($chatHandle)
        $chat = Get-QQChatControls $root $label
        if (-not $chat) { continue }
        $editor = $chat.Editor
        $oldValue = $editor.ReadEditor()
        if ($null -eq $oldValue) { return 'chat_not_verified' }
        if (-not $sending -and $oldValue -ceq $inputData.command) { return 'draft_ready' }
        if ($oldValue.Length) { return 'draft_exists' }
        if ($chat.Header.Name -cne $label -or $editor.ReadEditor() -cne '') { return 'chat_not_verified' }
        if (-not (Paste-Editor $editor $chatHandle $inputData.command)) { return 'draft_not_inserted' }
        if ($chat.Header.Name -ceq $label -and $editor.ReadEditor() -ceq $inputData.command) {
            if ($sending) { return Submit-QQCommand $root $chat.Header $editor $chatHandle $label }
            return 'draft_ready'
        }
        return 'chat_not_verified'
    }
    return 'contact_not_opened'
}

$script:submitAttempted = $false
try { Open-QQDraft } catch {
    if ($script:submitAttempted) { 'send_uncertain' } else { 'chat_not_verified' }
}
