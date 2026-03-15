"""Arrow-key selector helpers backed by InquirerPy."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import os
import sys
from typing import TypeAlias


class SelectorUnavailableError(RuntimeError):
    """Raised when arrow-key selector UI cannot be used."""


@dataclass(frozen=True)
class _SelectionOption:
    value: str
    label: str


@dataclass(frozen=True)
class SelectionSeparator:
    label: str


SelectOneOption: TypeAlias = tuple[str, str] | SelectionSeparator


def _run_prompt_handlers(handlers: object, event: object) -> None:
    if not isinstance(handlers, list):
        return
    for handler in handlers:
        if not isinstance(handler, dict):
            continue
        func = handler.get("func")
        if not callable(func):
            continue
        args = handler.get("args", [])
        if not isinstance(args, list):
            args = []
        func(event, *args)


def _bind_fuzzy_submit_only(prompt: object) -> None:
    """Override fuzzy multiselect Enter to submit only selected values."""
    kb_func_lookup = getattr(prompt, "kb_func_lookup", None)
    if not isinstance(kb_func_lookup, dict):
        return

    original_answer_handlers = kb_func_lookup.get("answer")
    if not isinstance(original_answer_handlers, list):
        original_answer_handlers = []

    def _submit_only(event: object) -> None:
        try:
            from InquirerPy.base import FakeDocument
            from prompt_toolkit.validation import ValidationError
        except Exception:
            _run_prompt_handlers(original_answer_handlers, event)
            return

        try:
            validator = getattr(prompt, "_validator", None)
            result_value = list(getattr(prompt, "result_value", []))
            if validator is not None:
                validator.validate(FakeDocument(result_value))  # type: ignore[arg-type]

            selected_choices = getattr(prompt, "selected_choices", [])
            status = getattr(prompt, "status", None)
            app = getattr(event, "app", None)
            app_exit = getattr(app, "exit", None)
            if not callable(app_exit):
                _run_prompt_handlers(original_answer_handlers, event)
                return

            if isinstance(status, dict):
                status["answered"] = True
            if selected_choices:
                result_name = list(getattr(prompt, "result_name", []))
                if isinstance(status, dict):
                    status["result"] = result_name
                app_exit(result=result_value)
                return

            if isinstance(status, dict):
                status["result"] = []
            app_exit(result=[])
        except ValidationError as exc:
            set_error = getattr(prompt, "_set_error", None)
            if callable(set_error):
                set_error(str(exc))
                return
            _run_prompt_handlers(original_answer_handlers, event)
        except IndexError:
            status = getattr(prompt, "status", None)
            if isinstance(status, dict):
                status["answered"] = True
                status["result"] = []
            app = getattr(event, "app", None)
            app_exit = getattr(app, "exit", None)
            if callable(app_exit):
                app_exit(result=[])
                return
            _run_prompt_handlers(original_answer_handlers, event)
        except Exception:
            _run_prompt_handlers(original_answer_handlers, event)

    kb_func_lookup["answer"] = [{"func": _submit_only}]


def _ensure_tty() -> None:
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        raise SelectorUnavailableError("interactive selector requires a TTY")


def _inquirer():
    try:
        from InquirerPy import inquirer
    except Exception as exc:  # pragma: no cover - environment dependent
        raise SelectorUnavailableError("InquirerPy unavailable") from exc
    return inquirer


@contextmanager
def _no_cpr_env():
    previous = os.environ.get("PROMPT_TOOLKIT_NO_CPR")
    os.environ["PROMPT_TOOLKIT_NO_CPR"] = "1"
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("PROMPT_TOOLKIT_NO_CPR", None)
        else:
            os.environ["PROMPT_TOOLKIT_NO_CPR"] = previous


def select_one(
    title: str,
    options: list[SelectOneOption],
    *,
    default_value: str | None = None,
) -> str | None:
    """Return selected value, None on cancel, or raise SelectorUnavailableError."""
    _ensure_tty()
    if not options:
        return None

    inquirer = _inquirer()
    try:
        from InquirerPy.separator import Separator
    except Exception as exc:
        raise SelectorUnavailableError("InquirerPy separator support unavailable") from exc

    choices = []
    for option in options:
        if isinstance(option, SelectionSeparator):
            choices.append(Separator(option.label))
            continue
        value, label = option
        choices.append(_SelectionOption(value=value, label=label))

    try:
        with _no_cpr_env():
            result = inquirer.select(
                message=title,
                choices=[
                    item
                    if not isinstance(item, _SelectionOption)
                    else {"name": item.label, "value": item.value}
                    for item in choices
                ],
                default=default_value,
                pointer=">",
                vi_mode=False,
                mandatory=False,
                raise_keyboard_interrupt=True,
            ).execute()
    except (KeyboardInterrupt, EOFError):
        return None
    except Exception as exc:
        raise SelectorUnavailableError("selector runtime failed") from exc

    if result is None:
        return None
    return str(result)


def select_text(
    message: str,
    *,
    default_value: str = "",
    multiline: bool = False,
) -> str | None:
    """Return typed text, None on cancel, or raise SelectorUnavailableError."""
    _ensure_tty()

    inquirer = _inquirer()
    try:
        with _no_cpr_env():
            result = inquirer.text(
                message=message,
                default=default_value,
                vi_mode=False,
                mandatory=False,
                multiline=multiline,
                raise_keyboard_interrupt=True,
            ).execute()
    except (KeyboardInterrupt, EOFError):
        return None
    except Exception as exc:
        raise SelectorUnavailableError("selector runtime failed") from exc

    if result is None:
        return None
    return str(result)


def select_fuzzy(
    title: str,
    options: list[tuple[str, str]],
    *,
    default_value: str | None = None,
) -> str | None:
    """Return a value from a fuzzy prompt, or None on cancel."""
    _ensure_tty()
    if not options:
        return None

    choices = [_SelectionOption(value=value, label=label) for value, label in options]
    inquirer = _inquirer()
    try:
        with _no_cpr_env():
            result = inquirer.fuzzy(
                message=title,
                choices=[{"name": item.label, "value": item.value} for item in choices],
                default=default_value,
                vi_mode=False,
                mandatory=False,
                raise_keyboard_interrupt=True,
            ).execute()
    except (KeyboardInterrupt, EOFError):
        return None
    except Exception as exc:
        raise SelectorUnavailableError("selector runtime failed") from exc

    if result is None:
        return None
    return str(result)


def select_fuzzy_many(
    title: str,
    options: list[tuple[str, str]],
    *,
    default_values: list[str] | None = None,
) -> list[str] | None:
    """Return selected values from fuzzy multiselect in source order."""
    _ensure_tty()
    if not options:
        return []

    defaults = set(default_values or [])
    choices = [_SelectionOption(value=value, label=label) for value, label in options]
    inquirer = _inquirer()
    try:
        with _no_cpr_env():
            prompt = inquirer.fuzzy(
                message=title,
                choices=[
                    {
                        "name": item.label,
                        "value": item.value,
                        "enabled": item.value in defaults,
                    }
                    for item in choices
                ],
                multiselect=True,
                instruction="(space/tab to toggle, enter to submit, ctrl-c to cancel)",
                marker="[x]",
                marker_pl="[ ]",
                keybindings={
                    "toggle": [{"key": "space"}],
                    "toggle-down": [{"key": "c-i"}],
                    "toggle-up": [{"key": "s-tab"}],
                },
                vi_mode=False,
                mandatory=False,
                raise_keyboard_interrupt=True,
            )
            _bind_fuzzy_submit_only(prompt)
            selected = prompt.execute()
    except (KeyboardInterrupt, EOFError):
        return None
    except Exception as exc:
        raise SelectorUnavailableError("selector runtime failed") from exc

    if selected is None:
        return None
    return [value for value, _label in options if value in set(selected)]
