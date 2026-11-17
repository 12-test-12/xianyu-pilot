$ErrorActionPreference = 'Stop'
$path = (Resolve-Path 'apps/api/app/resources/qq_draft.ps1').Path
$tokens = $errors = $null
$ast = [Management.Automation.Language.Parser]::ParseInput([IO.File]::ReadAllText($path), [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw ($errors -join "`n") }
$names = 'Get-SearchResultKind', 'Find-QQContact', 'Get-QQMessageBubbles', 'Get-QQReceiptState', 'Find-QQReceipt', 'Submit-QQCommand'
foreach ($definition in $ast.FindAll({ param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] }, $false)) {
    if ($definition.Name -notin $names) { continue }
    $code = $definition.Extent.Text.Replace('[QQAutomation]::Button', '50000').Replace('[QQAutomation]::ListItem', '50007').Replace('[QQAutomation]::Text', '50020')
    . ([scriptblock]::Create($code.Replace('[XianyuQQWindow]::GetForegroundWindow()', '42')))
}

function Assert-Equal($actual, $expected, [string]$label) {
    if ($actual -cne $expected) { throw "$label expected [$expected], got [$actual]" }
}

Assert-Equal (Get-QQReceiptState '球球号：12345 助力成功！' '12345') 'receipt_success' 'explicit success'
Assert-Equal (Get-QQReceiptState '12345 今日助力次数已用完' '12345') 'receipt_capped' 'explicit cap'
foreach ($text in @('回复 助力 123456 已成功', '12345 助力失败，未达到成功条件',
        '12345 球球号不存在', '12345 全服排名第 10', '12345、45678 助力成功')) {
    Assert-Equal (Get-QQReceiptState $text '12345') $null $text
}

$old = [pscustomobject]@{ Id = 'old'; Self = $false; Text = '12345 助力成功' }
$sent = [pscustomobject]@{ Id = 'sent'; Self = $true; Text = '助力 12345' }
$reply = [pscustomobject]@{ Id = 'reply'; Self = $false; Text = $old.Text }
$ownCopy = [pscustomobject]@{ Id = 'copy'; Self = $true; Text = $old.Text }
$cap = [pscustomobject]@{ Id = 'cap'; Self = $false; Text = '12345 已达到上限' }
Assert-Equal (Find-QQReceipt @($old) @($old, $sent, $reply) $sent.Text '12345') 'receipt_success' 'distinct incoming bubble with identical text'
Assert-Equal (Find-QQReceipt @($old) @($old, $sent, $ownCopy) $sent.Text '12345') $null 'own message'
Assert-Equal (Find-QQReceipt @($old) @($old, $reply, $sent) $sent.Text '12345') $null 'reply before outgoing bubble'
Assert-Equal (Find-QQReceipt @($old) @($sent, $reply) $sent.Text '12345') $null 'prior viewport disappeared'
Assert-Equal (Find-QQReceipt @($sent) @($sent, $reply) $sent.Text '12345') $null 'missing new outgoing bubble'
Assert-Equal (Find-QQReceipt @() @($sent, $reply, $cap) $sent.Text '12345') $null 'conflicting outcomes'

$top = [pscustomobject]@{ Name = '综合搜索'; ClassName = 'search-result-list' }
$friend = [pscustomobject]@{ Name = '助力机器人 12345'; ClassName = ''; Parent = $top; Fields = @('助力机器人', '12345') }
$shortcut = [pscustomobject]@{ Name = '综合搜索 查找用户 12345'; ClassName = ''; Parent = $top; Fields = @('查找用户', '12345') }
$automation = [pscustomobject]@{} | Add-Member ScriptMethod Parent { param($node) $node.Parent } -PassThru
$automation | Add-Member ScriptMethod FromHandle { param($window) 0 }
$automation | Add-Member ScriptMethod Same { param($first, $second) [object]::ReferenceEquals($first, $second) }
$automation | Add-Member ScriptMethod MessageContainers { param($root) @($outer, $inner) }
function Find-Type($root, $type) {
    if ($type -eq 50000) { return $button }
    if ($type -eq 50007) { return @($friend, $shortcut) }
    foreach ($field in $root.Fields) { [pscustomobject]@{ Name = $field } }
}
Assert-Equal (Find-QQContact 0 '12345' '助力机器人').Label '助力机器人' 'contact nested in comprehensive search'
$friend.Name = '综合搜索机器人 12345'
$friend.Fields = @('综合搜索机器人', '12345')
Assert-Equal (Find-QQContact 0 '12345' '综合搜索机器人').Label '综合搜索机器人' 'contact name that starts with search label'

$outer = [pscustomobject]@{ ClassName = 'message-container'; RuntimeId = 'outer'; Fields = @($old.Text) }
$inner = [pscustomobject]@{ ClassName = 'msg-content-container container--self'; Parent = $outer }
$message = @(Get-QQMessageBubbles 0)
Assert-Equal $message.Count 1 'nested bubble counted once'
Assert-Equal $message[0].Self $true 'nested outgoing marker preserved'

$script:clicked = $false
$inputData = @{ command = $sent.Text; value = '12345' }
$header = [pscustomobject]@{ Name = 'robot' }
$editor = [pscustomobject]@{} | Add-Member ScriptMethod ReadEditor { if ($script:clicked) { return '' }; return $inputData.command } -PassThru
$button = [pscustomobject]@{ Name = 'Send' } | Add-Member ScriptMethod TryInvoke { $script:clicked = $true; return $true } -PassThru
function Get-QQChatControls($root, $label) {
    if ($header.Name -ceq $label) { return @{ Header = $header; Editor = $editor } }
}
function Get-QQMessageBubbles { $header.Name = 'another-chat' }
Assert-Equal (Submit-QQCommand 0 $header $editor 42 'robot') 'qq_send_unavailable' 'chat switches during baseline scan'
Assert-Equal $script:clicked $false 'must never click Send after chat switches'

$header.Name = 'robot'
$inputData = @{ command = '查 小明'; value = '小明' }
function Start-Sleep {}
Assert-Equal (Submit-QQCommand 0 $header $editor 42 'robot') 'submitted' 'ranking lookup is only a QQ submission'
