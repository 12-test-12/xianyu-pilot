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
    public int ControlType { get { return (int)Element.GetCurrentPropertyValue(30003); } }
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
    public bool TrySetValue(string text) {
        var value = Pattern<IQQValue>(10002);
        if (value == null || value.GetIsReadOnly()) return false;
        value.SetValue(text);
        return true;
    }

    public string ReadEditor() {
        var pattern = Pattern<IQQText>(10014);
        var range = pattern == null ? null : pattern.GetDocumentRange();
        var text = range == null ? null : range.GetText(600).TrimEnd('\r', '\n');
        if (String.IsNullOrWhiteSpace(text)) text = Value ?? text;
        // QQ can expose an empty chat editor as a newline and a space.
        return text != null && String.IsNullOrWhiteSpace(text) ? String.Empty : text;
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
