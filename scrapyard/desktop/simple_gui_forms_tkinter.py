"""
simple_gui_forms_tkinter — Simplifies creating simple GUI forms using Tkinter with minimal boilerplate and reusable components. This module provides a declarative interface for building desktop forms, focusing on usability and 

### PART-META-JSON
{
  "name": "simple_gui_forms_tkinter",
  "layer": "desktop",
  "purpose": "Declarative Tkinter forms: FieldDef(label, default, validator) definitions generate labelled Entry widgets with typed value retrieval (int/float/bool/str) and per-field validation.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Tk root, list of FieldDef(label, default, optional validator).",
  "outputs": "Form with get_values() -> typed dict; show() runs the mainloop.",
  "files_created": [],
  "security_notes": "Requires a display (Tk). Validators run caller-supplied callables on user input - keep them side-effect free. Values come from the user: validate before persisting or executing anything with them.",
  "ai_usage": "Import what you need from `scrapyard.desktop.simple_gui_forms_tkinter`.",
  "example": "from scrapyard.desktop.simple_gui_forms_tkinter import *",
  "import_path": "scrapyard.desktop.simple_gui_forms_tkinter"
}
### END-PART-META
"""

from typing import List, Dict, Any, TypeVar, Generic, Callable, Optional
from tkinter import Tk, Label, Entry, StringVar, Frame, messagebox
import logging
import os
import tempfile

logger = logging.getLogger(__name__)

T = TypeVar('T')


class FieldDef(Generic[T]):
    """Definition of a form field with label, default value, and optional validator."""
    
    def __init__(self, label: str, default: T, validator: Optional[Callable[[T], None]] = None):
        self.label = label
        self.default = default
        self.validator = validator


def convert_field_value(default: Any, value: str) -> Any:
    """Convert a text field using the declared default's type."""
    field_type = type(default)
    if field_type is int:
        return int(value)
    if field_type is float:
        return float(value)
    if field_type is bool:
        return value.lower() in ('true', '1', 'yes', 'on')
    return value


class Form:
    """A simple GUI form that generates widgets from field definitions."""
    
    def __init__(self, root: Tk, fields: List[FieldDef]):
        self.root = root
        self.fields = fields
        self.values: Dict[str, Any] = {field.label: field.default for field in fields}
        self.entries: Dict[str, tuple[StringVar, Entry]] = {}
        self._setup_form()

    def _setup_form(self) -> None:
        """Create and layout the form widgets."""
        form_frame = Frame(self.root)
        form_frame.pack(padx=10, pady=10)

        for i, field in enumerate(self.fields):
            label = Label(form_frame, text=field.label + ":")
            label.grid(row=i, column=0, padx=5, pady=5, sticky='w')

            entry_var = StringVar(value=str(field.default))
            entry = Entry(form_frame, textvariable=entry_var)
            entry.grid(row=i, column=1, padx=5, pady=5)

            self.entries[field.label] = (entry_var, entry)

    def show(self) -> None:
        """Display the form and start the main event loop."""
        self.root.mainloop()

    def get_values(self) -> Dict[str, Any]:
        """Retrieve current values from form fields with type conversion and validation."""
        for field in self.fields:
            field_label = field.label
            value_str = self.entries[field_label][0].get()
            try:
                # Convert string to appropriate type based on default value
                converted = convert_field_value(field.default, value_str)
                
                # Apply custom validator if provided
                if field.validator is not None:
                    field.validator(converted)
                
                self.values[field_label] = converted
                self.entries[field_label][1].config(fg="black")
            except (ValueError, TypeError) as e:
                messagebox.showerror("Validation Error", f"Invalid input for {field_label}: {e}")
                self.entries[field_label][1].config(fg="red")
        
        return self.values


def create_form(root: Tk, fields: List[FieldDef]) -> Form:
    """Create a Form instance with the given fields."""
    form = Form(root, fields)
    return form


def _selftest():
    """Headless contract test for field definitions and typed conversion."""
    positive = FieldDef("Age", 30, validator=lambda value: value > 0)
    assert positive.label == "Age" and positive.default == 30
    assert convert_field_value("", "Jane Doe") == "Jane Doe"
    assert convert_field_value(0, "25") == 25
    assert convert_field_value(0.0, "165.5") == 165.5
    assert convert_field_value(False, "yes") is True
    assert convert_field_value(True, "no") is False
    try:
        convert_field_value(0, "not-an-int")
        raise AssertionError("invalid integer input must fail")
    except ValueError:
        pass


if __name__ == "__main__":
    _selftest()
