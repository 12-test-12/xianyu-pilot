# QQ NT accessibility selectors are documented by treers2/qq-operations.
$ErrorActionPreference = 'Stop'
$inputData = [Console]::In.ReadToEnd() | ConvertFrom-Json
Add-Type -AssemblyName System.Windows.Forms
Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class XianyuQQWindow {
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr window);
    [DllImport("user32.dll")] public static extern bool ShowWindowAsync(IntPtr window, int action);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr window);
    [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr window);
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
}

[ComImport, Guid("352ffba8-0973-437c-a61f-f64cafd81df9"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
internal interface IQQCondition {}

[ComImport, Guid("d22108aa-8ac5-49a5-837b-37bbb3d7591e"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
internal interface IQQElement {
    void SetFocus();
    void GetRuntimeId();
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
    public bool IsPassword { get { return Equals(Element.GetCurrentPropertyValue(30019), true); } }

    internal bool IsUsable {
        get {
            return Equals(Element.GetCurrentPropertyValue(30010), true) &&
                Equals(Element.GetCurrentPropertyValue(30022), false);
        }
    }

    public bool HasEditableValue {
        get {
            var value = Pattern<IQQValue>(10002);
            return value != null && !value.GetIsReadOnly();
        }
    }

    public string Value {
        get {
            var value = Pattern<IQQValue>(10002);
            return value == null ? null : value.GetValue();
        }
    }

    public void SetFocus() { Element.SetFocus(); }
    public void SetValue(string value) {
        var pattern = Pattern<IQQValue>(10002);
        if (pattern == null || pattern.GetIsReadOnly()) throw new InvalidOperationException();
        pattern.SetValue(value);
    }

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
    public const int ListItem = 50007;
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
        var matches = root.Element.FindAll(4, client.CreatePropertyCondition(property, value));
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

function Test-SearchResult($node) {
    $inSearch = $false
    for ($depth = 0; $node -and $depth -lt 8; $depth++) {
        $name = $node.Name
        $class = $node.ClassName
        if ($name -match '^(\u7fa4\u804a|\u6d88\u606f\u8bb0\u5f55|\u7f51\u7edc\u641c\u7d22)' -or $class -match '(?i)search.*(group|message|network)') { return $false }
        if ($name -match '^(\u8054\u7cfb\u4eba|\u597d\u53cb)$' -or $class -match '(?i)search.*(result|list|panel|item|container)') { $inSearch = $true }
        $node = $automation.Parent($node)
    }
    return $inSearch
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
    $panels = @(
        $window = [IntPtr]::Zero
        while ($true) {
            $window = [XianyuQQWindow]::NextQQWindow($window)
            if ($window -eq [IntPtr]::Zero) { break }
            if ([XianyuQQWindow]::IsWindowVisible($window) -and [XianyuQQWindow]::ProcessId($window) -in $processes.Id) { $window }
        }
    )
    if (-not $panels.Count) { return 'qq_window_missing' }
    $foreground = [XianyuQQWindow]::GetForegroundWindow()
    if ($panels.Count -eq 1 -and $foreground -notin $panels) {
        if ([XianyuQQWindow]::IsIconic($panels[0])) {
            [void][XianyuQQWindow]::ShowWindowAsync($panels[0], 9)
            Start-Sleep -Milliseconds 250
        }
        [void][XianyuQQWindow]::SetForegroundWindow($panels[0])
    }
    for ($attempt = 0; $attempt -lt 24; $attempt++) {
        $handle = [XianyuQQWindow]::GetForegroundWindow()
        if ($handle -in $panels) { break }
        Start-Sleep -Milliseconds 250
    }
    if ($handle -notin $panels) { return 'qq_unavailable' }

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
        if ($matches.Count -eq 1 -and $matches[0].HasEditableValue) {
            $search = $matches[0]
            break
        }
        Start-Sleep -Milliseconds 250
    }
    if (-not $search) { return 'qq_search_unavailable' }
    $number = [string]$inputData.robotQq
    $label = [string]$inputData.robotName
    $numberPattern = '(?<!\d)' + [regex]::Escape($number) + '(?!\d)'
    if ($search.Value -cne $number) {
        if ([XianyuQQWindow]::GetForegroundWindow() -ne $handle) { return 'qq_unavailable' }
        $search.SetFocus()
        $search.SetValue('')
        if ($search.Value -or -not (Paste-Editor $search $handle $number)) { return 'qq_search_unavailable' }
    }

    $result = $null
    for ($attempt = 0; $attempt -lt 12; $attempt++) {
        Start-Sleep -Milliseconds 250
        if ([XianyuQQWindow]::GetForegroundWindow() -ne $handle) { return 'qq_unavailable' }
        if ($search.Value -cne $number) { continue }
        $rows = @(Find-Type $panel ([QQAutomation]::ListItem) | Where-Object {
            ($_.Name -match $numberPattern -or ($label -and $_.Name -ceq $label)) -and (Test-SearchResult $_)
        })
        if ($rows.Count -gt 1) { return 'contact_not_found' }
        if ($rows.Count -eq 1) { $result = $rows[0]; break }
    }
    if (-not $result -or [XianyuQQWindow]::GetForegroundWindow() -ne $handle) { return 'contact_not_found' }
    if ($result.Name -match $numberPattern) {
        $bracketPattern = '[\s(（\[【:：-]*' + $numberPattern + '[\s)）\]】:：-]*'
        $trimChars = [char[]]@(' ', '(', ')', '[', ']', ':', '-', [char]0xff08, [char]0xff09, [char]0x3010, [char]0x3011, [char]0xff1a, [char]0x3000)
        $resultLabel = ($result.Name -replace $bracketPattern, '').Trim($trimChars)
        if ($resultLabel) { $label = $resultLabel }
    }
    if (-not $label) { $label = $number }
    if ([XianyuQQWindow]::GetForegroundWindow() -ne $handle) { return 'qq_unavailable' }
    if (-not $result.TryInvoke()) {
        $point = $result.Center()
        if ($null -eq $point -or -not (Test-Within ($automation.FromPoint($point)) $result)) { return 'contact_not_found' }
        if ([XianyuQQWindow]::GetForegroundWindow() -ne $handle) { return 'qq_unavailable' }
        [Windows.Forms.Cursor]::Position = [Drawing.Point]::new($point.X, $point.Y)
        [XianyuQQWindow]::mouse_event(6, 0, 0, 0, [UIntPtr]::Zero)
    }

    for ($attempt = 0; $attempt -lt 12; $attempt++) {
        Start-Sleep -Milliseconds 250
        $chatHandle = [XianyuQQWindow]::GetForegroundWindow()
        if ($chatHandle -eq [IntPtr]::Zero) { continue }
        if ([XianyuQQWindow]::ProcessId($chatHandle) -notin $processes.Id) { return 'chat_not_verified' }
        $root = $automation.FromHandle($chatHandle)
        $headers = @(Find-Class $root 'chat-header__contact-name')
        $editors = @(Find-Class $root 'qq-msg-editor')
        if ($headers.Count -ne 1 -or $headers[0].Name -cne $label -or $editors.Count -ne 1) { continue }
        $editor = $editors[0]
        $oldValue = $editor.ReadEditor()
        if ($null -eq $oldValue) { return 'chat_not_verified' }
        if ($oldValue -ceq $inputData.command) { return 'draft_ready' }
        if ($oldValue.Length) { return 'draft_exists' }
        if ($headers[0].Name -cne $label -or $editor.ReadEditor() -cne '' -or
            -not (Paste-Editor $editor $chatHandle $inputData.command)) { return 'chat_not_verified' }
        if ($headers[0].Name -ceq $label -and $editor.ReadEditor() -ceq $inputData.command) { return 'draft_ready' }
        return 'chat_not_verified'
    }
    return 'chat_not_verified'
}

try { Open-QQDraft } catch { 'chat_not_verified' }
