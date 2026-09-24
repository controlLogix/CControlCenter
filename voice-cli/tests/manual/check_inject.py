"""Types into a focused Tk Entry via SendInput and checks it arrived; also checks the
overlay does not take focus from that window."""
import threading, time, tkinter as tk, ctypes
from voicecli import inject

SAMPLE = "git status && echo 'héllo wörld' ✓ 🚀"
root = tk.Tk(); root.title("inject-target"); root.geometry("600x80+200+200")
e = tk.Entry(root, width=80); e.pack(padx=10, pady=20)
result = {}

def drive():
    time.sleep(1.0)
    root.after(0, lambda: (root.lift(), e.focus_set()))
    hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
    # Windows only lets the foreground process hand out focus; a lone Alt tap unlocks it.
    inject._send([inject._key(vk=0x12), inject._key(vk=0x12, flags=inject.KEYEVENTF_KEYUP)])
    ctypes.windll.user32.SetForegroundWindow(hwnd)
    time.sleep(0.8)
    result["fg_before"] = inject.foreground_title()
    if result["fg_before"] != "inject-target":  # never type into someone else's window
        root.after(0, root.destroy)
        return
    inject.type_text(SAMPLE)
    inject.press_enter()
    time.sleep(0.8)
    result["value"] = e.get()
    root.after(0, root.destroy)

e.bind("<Return>", lambda ev: result.setdefault("enter", True))
threading.Thread(target=drive, daemon=True).start()
root.mainloop()
print("foreground:", result.get("fg_before"))
print("typed ok:", result.get("value") == SAMPLE, repr(result.get("value")))
print("enter ok:", result.get("enter", False))
