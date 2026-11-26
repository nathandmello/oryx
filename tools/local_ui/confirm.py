"""Present a roadmap approval in a trusted local desktop window."""

import json
import sys


def main():
    import tkinter as tk
    from tkinter import ttk
    from tkinter.scrolledtext import ScrolledText

    review = json.load(sys.stdin)
    window = tk.Tk()
    window.title("oryx · Approve roadmap change")
    window.geometry("760x640")
    window.minsize(490, 380)
    frame = ttk.Frame(window, padding=18)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text=f"Review roadmap changes for {review['product']}").pack(anchor="w", pady=(0, 12))
    detail = ScrolledText(frame, wrap="word", height=20, padx=10, pady=10)
    detail.pack(fill="both", expand=True)
    for change in review["changes"]:
        if change["type"] == "cycle":
            detail.insert("end", f"Create cycle {change['cycle']}\n{change['starts_on']} to {change['ends_on']}\n"
                          f"Capacity: {change['capacity']} {change['unit']}\n"
                          f"Compared: {', '.join(change['options'])}\n\n")
        else:
            title = review["titles"][change["initiative"]]
            description = "Release selection"
            if change["action"] == "plan":
                description = f"Select for {change['cycle']} / {change['horizon']} / rank {change['rank']} / effort {change['effort']}"
            detail.insert("end", f"{description}\n{title} ({change['initiative']})\n{change['on']}\n"
                          f"Reason: {change['reason']}\nSource: {change['source']}\n\n")
    for document in review["documents"]:
        detail.insert("end", f"{document['path']}\n\n{document['text']}\n")
    detail.insert("end", f"\nRevision {review['revision']}\n")
    detail.configure(state="disabled")
    footer = ttk.Frame(frame)
    footer.pack(fill="x", pady=(12, 0))
    approved = False

    def approve():
        nonlocal approved
        approved = True
        window.destroy()

    ttk.Button(footer, text="Approve and apply", command=approve).pack(side="right", padx=(8, 0))
    cancel = ttk.Button(footer, text="Cancel", command=window.destroy)
    cancel.pack(side="right")
    cancel.focus_set()
    window.bind("<Escape>", lambda _: window.destroy())
    window.mainloop()
    return 0 if approved else 1


if __name__ == "__main__":
    try:
        result = main()
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        result = 2
    sys.exit(result)
