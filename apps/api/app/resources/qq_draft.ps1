# QQ NT accessibility selectors are documented by treers2/qq-operations.
$ErrorActionPreference = 'Stop'
$inputData = [Console]::In.ReadToEnd() | ConvertFrom-Json
Add-Type -AssemblyName System.Windows.Forms
Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class XianyuQQWindow {
    [StructLayout(LayoutKind.Sequential)]
    private struct KeyboardInput {
        public ushort Key, Scan;
        public uint Flags, Time;
        public UIntPtr Extra;
    }
    [StructLayout(LayoutKind.Sequential)]
    private struct MouseInput {
        public int X, Y;
        public uint Data, Flags, Time;
        public UIntPtr Extra;
    }
    [StructLayout(LayoutKind.Explicit)]
    private struct InputData {
        [FieldOffset(0)] public KeyboardInput Keyboard;
        [FieldOffset(0)] public MouseInput Mouse;
    }
    [StructLayout(LayoutKind.Sequential)]
    private struct Input {
        public uint Type;
        public InputData Data;
    }
    [DllImport("user32.dll")] private static extern uint SendInput(uint count, Input[] inputs, int size);
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr window);
    [DllImport("user32.dll")] public static extern bool ShowWindowAsync(IntPtr window, int action);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr window);
    [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr window);
    [DllImport("user32.dll")] public static extern IntPtr GetAncestor(IntPtr window, uint flags);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] private static extern IntPtr FindWindowEx(IntPtr parent, IntPtr after, string className, string title);
    [DllImport("user32.dll")] private static extern uint GetWindowThreadProcessId(IntPtr window, out uint processId);
    [DllImport("user32.dll")] public static extern uint GetClipboardSequenceNumber();
    [DllImport("user32.dll")] public static extern void mouse_event(uint flags, uint x, uint y, uint data, UIntPtr extra);
    public static IntPtr NextQQWindow(IntPtr after) { return FindWindowEx(IntPtr.Zero, after, null, "QQ"); }
    public static uint ProcessId(IntPtr window) {
        uint id;
        GetWindowThreadProcessId(window, out id);
        return id;
    }

    private static Input Key(ushort code, bool release) {
        return new Input { Type = 1, Data = new InputData {
            Keyboard = new KeyboardInput { Key = code, Flags = release ? 2u : 0u }
        }};
    }
    public static bool Paste(IntPtr window) {
        return SendKeys(window, new[] { Key(0x11, false), Key(0x56, false), Key(0x56, true), Key(0x11, true) });
    }
    public static bool SearchNumber(IntPtr window, string number) {
        if (!System.Text.RegularExpressions.Regex.IsMatch(number, @"\A[1-9][0-9]{4,19}\z")) return false;
        var keys = new System.Collections.Generic.List<Input> {
            Key(0x11, false), Key(0x41, false), Key(0x41, true), Key(0x11, true)
        };
        foreach (char digit in number) {
            keys.Add(Key(digit, false));
            keys.Add(Key(digit, true));
        }
        return SendKeys(window, keys.ToArray());
    }
    public static bool SearchEnter(IntPtr window) {
        return SendKeys(window, new[] { Key(0x0D, false), Key(0x0D, true) });
    }
    private static bool SendKeys(IntPtr window, Input[] keys) {
        return GetForegroundWindow() == window && SendInput((uint)keys.Length, keys, Marshal.SizeOf(typeof(Input))) == keys.Length;
    }
}

// Import the native UI Automation client. The legacy managed client can miss QQ's Chromium controls.
// Unused methods keep the COM vtable positions defined by UIAutomationClient.idl.
[ComImport, Guid("30cbe57d-d9d0-452a-ab13-7ac5ac4825ee"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
internal interface IQQAutomation {
    [return: MarshalAs(UnmanagedType.Bool)]
    bool CompareElements(IQQElement first, IQQElement second);
    void CompareRuntimeIds();
    void GetRootElement();
    IQQElement ElementFromHandle(IntPtr window);
    IQQElement ElementFromPoint(QQPoint point);
    IQQElement GetFocusedElement();
    void GetRootElementBuildCache();
    void ElementFromHandleBuildCache();
    void ElementFromPointBuildCache();
    void GetFocusedElementBuildCache();
    void CreateTreeWalker();
    IQQWalker GetControlViewWalker();
    void GetContentViewWalker();
    void GetRawViewWalker();
    void GetRawViewCondition();
    void GetControlViewCondition();
    void GetContentViewCondition();
    void CreateCacheRequest();
    void CreateTrueCondition();
    void CreateFalseCondition();
    IQQCondition CreatePropertyCondition(int property, [MarshalAs(UnmanagedType.Struct)] object value);
    IQQCondition CreatePropertyConditionEx(int property, [MarshalAs(UnmanagedType.Struct)] object value, int flags);
    void CreateAndCondition();
    void CreateAndConditionFromArray();
    void CreateAndConditionFromNativeArray();
    IQQCondition CreateOrCondition(IQQCondition first, IQQCondition second);
}

[ComImport, Guid("352ffba8-0973-437c-a61f-f64cafd81df9"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
internal interface IQQCondition {}

[ComImport, Guid("d22108aa-8ac5-49a5-837b-37bbb3d7591e"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
internal interface IQQElement {
    void SetFocus();
    [return: MarshalAs(UnmanagedType.SafeArray, SafeArraySubType=VarEnum.VT_I4)]
    int[] GetRuntimeId();
    void FindFirst();
    IQQElements FindAll(int scope, IQQCondition condition);
    void FindFirstBuildCache();
    void FindAllBuildCache();
    void BuildUpdatedCache();
    [return: MarshalAs(UnmanagedType.Struct)]
    object GetCurrentPropertyValue(int property);
    void GetCurrentPropertyValueEx();
    void GetCachedPropertyValue();
    void GetCachedPropertyValueEx();
    void GetCurrentPatternAs();
    void GetCachedPatternAs();
    [PreserveSig]
    int GetCurrentPattern(int pattern, [MarshalAs(UnmanagedType.IUnknown)] out object value);
}

[ComImport, Guid("14314595-b4bc-4055-95f2-58f2e42c9855"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
internal interface IQQElements {
    int GetLength();
    IQQElement GetElement(int index);
}

[ComImport, Guid("4042c624-389c-4afc-a630-9df854a541fc"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
internal interface IQQWalker {
    IQQElement GetParentElement(IQQElement element);
}

[ComImport, Guid("fb377fbe-8ea6-46d5-9c73-6499642d3059"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
internal interface IQQInvoke {
    void Invoke();
}

[ComImport, Guid("a94cd8b1-0844-4cd6-9d2d-640537ab39e9"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
internal interface IQQValue {
    void SetValue([MarshalAs(UnmanagedType.BStr)] string value);
    [return: MarshalAs(UnmanagedType.BStr)]
    string GetValue();
    [return: MarshalAs(UnmanagedType.Bool)]
    bool GetIsReadOnly();
}

[ComImport, Guid("32eba289-3583-42c9-9c59-3b6d9a1e9b6a"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
internal interface IQQText {
    void RangeFromPoint();
    void RangeFromChild();
    void GetSelection();
    void GetVisibleRanges();
    IQQTextRange GetDocumentRange();
}

[ComImport, Guid("a543cc6a-f4ae-494b-8239-c814481187a8"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
internal interface IQQTextRange {
    void Clone();
    void Compare();
    void CompareEndpoints();
    void ExpandToEnclosingUnit();
    void FindAttribute();
    void FindText();
    void GetAttributeValue();
    void GetBoundingRectangles();
    void GetEnclosingElement();
    [return: MarshalAs(UnmanagedType.BStr)]
    string GetText(int maxLength);
}

[StructLayout(LayoutKind.Sequential)]
public struct QQPoint {
    public int X;
    public int Y;
}

public sealed class QQControl {
    internal readonly IQQElement Element;
    internal QQControl(IQQElement element) { Element = element; }

    public string Name { get { return Element.GetCurrentPropertyValue(30005) as string; } }
    public string ClassName { get { return Element.GetCurrentPropertyValue(30012) as string; } }
    public string RuntimeId { get { return String.Join(":", Element.GetRuntimeId()); } }
    public bool IsPassword { get { return Equals(Element.GetCurrentPropertyValue(30019), true); } }

    internal bool IsUsable {
        get {
            return Equals(Element.GetCurrentPropertyValue(30010), true) &&
                Equals(Element.GetCurrentPropertyValue(30022), false);
        }
    }

    public string Value {
        get {
            var value = Pattern<IQQValue>(10002);
            return value == null ? null : value.GetValue();
        }
    }

    public void SetFocus() { Element.SetFocus(); }
    public string ReadEditor() {
        var pattern = Pattern<IQQText>(10014);
        var range = pattern == null ? null : pattern.GetDocumentRange();
        var text = range == null ? null : range.GetText(600).TrimEnd('\r', '\n');
        return String.IsNullOrEmpty(text) ? Value ?? text : text;
    }

    public bool TryInvoke() {
        var pattern = Pattern<IQQInvoke>(10000);
        if (pattern == null) return false;
        pattern.Invoke();
        return true;
    }

    public QQPoint? Center() {
        var bounds = Element.GetCurrentPropertyValue(30001) as double[];
        if (bounds == null || bounds.Length != 4 || bounds[2] <= 0 || bounds[3] <= 0) return null;
        return new QQPoint { X = (int)(bounds[0] + bounds[2] / 2), Y = (int)(bounds[1] + bounds[3] / 2) };
    }

    private T Pattern<T>(int pattern) where T : class {
        object value;
        return Element.GetCurrentPattern(pattern, out value) < 0 ? null : value as T;
    }
}

public sealed class QQAutomation {
    public const int ControlTypeProperty = 30003;
    public const int ClassNameProperty = 30012;
    public const int Edit = 50004;
    public const int ComboBox = 50003;
    public const int Button = 50000;
    public const int ListItem = 50007;
    public const int Text = 50020;
    private readonly IQQAutomation client = (IQQAutomation)Activator.CreateInstance(
        Type.GetTypeFromCLSID(new Guid("e22ad333-b25f-460c-83d0-0581107395c9")));
    private readonly IQQWalker walker;

    public QQAutomation() { walker = client.GetControlViewWalker(); }
    public QQControl FromHandle(IntPtr window) { return Wrap(client.ElementFromHandle(window)); }
    public QQControl FromPoint(QQPoint point) { return Wrap(client.ElementFromPoint(point)); }
    public QQControl Focused() { return Wrap(client.GetFocusedElement()); }
    public QQControl Parent(QQControl element) { return Wrap(walker.GetParentElement(element.Element)); }
    public bool Same(QQControl first, QQControl second) { return client.CompareElements(first.Element, second.Element); }

    public QQControl[] Find(QQControl root, int property, object value) {
        return Find(root, client.CreatePropertyCondition(property, value));
    }

    public QQControl[] MessageContainers(QQControl root) {
        const int matchSubstring = 2;
        var outer = client.CreatePropertyConditionEx(ClassNameProperty, "message-container", matchSubstring);
        var inner = client.CreatePropertyConditionEx(ClassNameProperty, "msg-content-container", matchSubstring);
        return Find(root, client.CreateOrCondition(outer, inner));
    }

    private static QQControl[] Find(QQControl root, IQQCondition condition) {
        var matches = root.Element.FindAll(4, condition);
        var result = new System.Collections.Generic.List<QQControl>();
        int count = matches.GetLength();
        for (var index = 0; index < count; index++) {
            var control = Wrap(matches.GetElement(index));
            if (control != null && control.IsUsable) result.Add(control);
        }
        return result.ToArray();
    }

    private static QQControl Wrap(IQQElement element) { return element == null ? null : new QQControl(element); }
}
'@

$automation = [QQAutomation]::new()

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

function Get-SearchResultKind($node) {
    if ($node.Name -match '^\s*(?:(?:\u7efc\u5408\u641c\u7d22|\u7f51\u7edc\u641c\u7d22)(?:$|[\s:\uFF1A]|\u67e5\u627e)|\u67e5\u627e\s*(?:\u7528\u6237|\u7fa4\u804a)(?:$|[\s:\uFF1A]))') { return 'excluded' }
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
    if (-not $headers.Count -and -not $editors.Count) {
        $headers = @(Find-Type $root ([QQAutomation]::Button) | Where-Object Name -CEQ $label)
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
        $exact = $row.Name -match $numberPattern
        if (-not $exact -and (-not $label -or $row.Name -cne $label)) { continue }
        $kind = Get-SearchResultKind $row
        if ($kind -eq 'excluded') { continue }

        $fields = @((Find-Type $row ([QQAutomation]::Text)).Name | Where-Object { $_ })
        $names = @($fields | Where-Object { $_ -notmatch $fieldsPattern } | Select-Object -Unique)
        $observedLabel = if ($label -and $label -cin $names) { $label } elseif ($names.Count -eq 1) { $names[0] }
        # Some QQ builds expose the result as an unnamed list. Require a dedicated number field there.
        if ($kind -ne 'contact' -and (-not $observedLabel -or -not @($fields | Where-Object { $_ -match $fieldsPattern }).Count)) { continue }
        if (-not $observedLabel -and $exact) {
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
    $editor.SetFocus()
    if ([XianyuQQWindow]::GetForegroundWindow() -ne $window -or
        -not (Test-Within ($automation.Focused()) $editor) -or
        $editor.ReadEditor() -cne '') { return $false }
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
    if (-not $buttons[0].TryInvoke()) {
        if ($chat.Header.Name -cne $label -or $chat.Editor.ReadEditor() -cne $inputData.command -or
            -not (Click-QQControl $buttons[0] $window)) { return 'qq_send_unavailable' }
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
    if (-not (Click-QQControl $search $handle)) { return 'qq_search_unavailable' }
    Start-Sleep -Milliseconds 150
    if (-not (Test-Within ($automation.Focused()) $search) -or -not [XianyuQQWindow]::SearchNumber($handle, $number)) {
        return 'qq_search_unavailable'
    }

    $result = $null
    $queryVisible = $false
    $enterTried = $false
    for ($attempt = 0; $attempt -lt 16; $attempt++) {
        Start-Sleep -Milliseconds 250
        if ([XianyuQQWindow]::GetForegroundWindow() -ne $handle) { return 'qq_unavailable' }
        if ($search.Value -cne $number -and $search.ReadEditor() -cne $number) { continue }
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
    if (-not $result.Control.TryInvoke() -and -not (Click-QQControl $result.Control $handle)) { return 'contact_not_found' }

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
        if ($chat.Header.Name -cne $label -or $editor.ReadEditor() -cne '' -or
            -not (Paste-Editor $editor $chatHandle $inputData.command)) { return 'chat_not_verified' }
        if ($chat.Header.Name -ceq $label -and $editor.ReadEditor() -ceq $inputData.command) {
            if ($sending) { return Submit-QQCommand $root $chat.Header $editor $chatHandle $label }
            return 'draft_ready'
        }
        return 'chat_not_verified'
    }
    return 'chat_not_verified'
}

$script:submitAttempted = $false
try { Open-QQDraft } catch {
    if ($script:submitAttempted) { 'send_uncertain' } else { 'chat_not_verified' }
}
