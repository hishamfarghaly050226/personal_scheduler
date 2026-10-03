"""Friendly point-and-click interface for the Personal Scheduler, built with
ipywidgets so it runs inside Jupyter (no Qt window needed).

Layers are unchanged:  SchedulerApp (this file) -> Scheduler -> DatabaseManager
This file contains no SQL and no business rules, only display + button wiring.
"""

import calendar
import html
from datetime import date, datetime, time, timedelta

import ipywidgets as w
from IPython.display import clear_output, display

from models import Event, Task
from utils.constants import (
    DEFAULT_CATEGORIES, PRIORITIES, PRIORITY_COLORS, RECURRENCES,
    REMINDER_OPTIONS, STATUSES,
)
from utils.formatting import format_time
from utils.validators import Validator

STATUS_COLORS = {"Pending": "#D97706", "In Progress": "#4F8EF7", "Completed": "#059669"}
ACCENT = "#4F8EF7"
TIME_CHOICES = [("No time", "")] + [
    (format_time(time(h, m)), f"{h:02d}:{m:02d}") for h in range(24) for m in (0, 15, 30, 45)
]

# Tab positions
T_TODAY, T_TASKS, T_EVENTS, T_CAL, T_ADD, T_STATS, T_SET = range(7)

# Colors are semi-transparent so the UI looks fine in both light and dark themes.
CARD = "border:1px solid rgba(128,128,128,.35);background:rgba(128,128,128,.08);border-radius:10px;"


def _badge(text: str, color: str) -> str:
    return (f'<span style="background:{color};color:#fff;padding:2px 9px;'
            f'border-radius:10px;font-size:12px;white-space:nowrap">{html.escape(text)}</span>')


def _stat_card(label: str, value, color: str) -> str:
    return (f'<div style="{CARD}padding:10px 16px;min-width:110px;border-left:5px solid {color}">'
            f'<div style="font-size:26px;font-weight:700">{value}</div>'
            f'<div style="opacity:.7;font-size:13px">{label}</div></div>')


def _empty(text: str) -> str:
    return f'<div style="opacity:.6;padding:14px;font-style:italic">{html.escape(text)}</div>'


def _section(title: str, body: str) -> str:
    return (f'<div style="{CARD}padding:10px 14px;margin:8px 0">'
            f'<div style="font-weight:700;margin-bottom:6px">{title}</div>{body}</div>')


class SchedulerApp:
    """Builds the whole interface and connects it to a Scheduler."""

    def __init__(self, scheduler, reminder_service) -> None:
        self.s = scheduler
        self.rem = reminder_service
        self._editing: tuple[str, int] | None = None      # ("task"/"event", id) while editing
        self._cal_month = date.today().replace(day=1)

        self.header = w.HTML()
        self.msg = w.HTML()                                 # one-line feedback under the tabs
        self._build_today()
        self._build_tasks()
        self._build_events()
        self._build_calendar()
        self._build_form()
        self._build_stats()
        self._build_settings()

        self.tabs = w.Tab(children=[
            self.today_box, self.tasks_box, self.events_box, self.cal_box,
            self.form_box, self.stats_box, self.settings_box,
        ])
        for i, title in enumerate(["🏠 Today", "✅ Tasks", "📅 Events", "🗓 Calendar",
                                   "➕ Add", "📊 Statistics", "⚙ Settings"]):
            self.tabs.set_title(i, title)
        self.tabs.observe(self._on_tab, names="selected_index")
        self.root = w.VBox([self.header, self.tabs, self.msg])
        self.refresh_all()

    def show(self) -> None:
        display(self.root)

    # ------------------------------------------------------------------ helpers
    def _say(self, text: str, kind: str = "ok") -> None:
        color = {"ok": "#059669", "warn": "#D97706", "err": "#DC2626"}[kind]
        icon = {"ok": "✔", "warn": "⚠", "err": "✖"}[kind]
        self.msg.value = (f'<div style="margin-top:8px;padding:8px 14px;border-radius:8px;'
                          f'border-left:5px solid {color};background:rgba(128,128,128,.12)">'
                          f'{icon} {html.escape(text)}</div>')

    def _on_tab(self, _change) -> None:
        self.msg.value = ""
        self.refresh_all()

    def refresh_all(self) -> None:
        self._refresh_header()
        self._refresh_today()
        self._refresh_tasks()
        self._refresh_events()
        self._refresh_calendar()
        self._refresh_stats()

    def _refresh_header(self) -> None:
        self.header.value = (
            f'<div style="padding:6px 2px"><span style="font-size:22px;font-weight:700">'
            f'{html.escape(self.s.user.greeting())}</span>'
            f'<span style="opacity:.65;margin-left:12px">{date.today():%A, %d %B %Y}</span></div>')

    @staticmethod
    def _set_options(dropdown: w.Dropdown, options: list) -> None:
        """Replace options but keep the current selection if it still exists."""
        old = dropdown.value
        dropdown.options = options
        valid = [v for _, v in options]
        dropdown.value = old if old in valid else valid[0]

    @staticmethod
    def _set_time(dropdown: w.Dropdown, value) -> None:
        text = value.strftime("%H:%M") if value else ""
        if text not in [v for _, v in dropdown.options]:     # e.g. 09:10 saved by the old app
            dropdown.options = list(dropdown.options) + [(format_time(value), text)]
        dropdown.value = text

    # ------------------------------------------------------------------ Today
    def _build_today(self) -> None:
        self.today_html = w.HTML()
        self.bell_btn = w.Button(description="Check reminders", icon="bell",
                                 button_style="info", tooltip="Show reminders that are due now")
        self.bell_html = w.HTML()
        self.bell_btn.on_click(self._on_bell)
        quick = w.Button(description="Add something", icon="plus", button_style="primary")
        quick.on_click(lambda _: self._goto_add())
        self.today_box = w.VBox([self.today_html, w.HBox([quick, self.bell_btn]), self.bell_html])

    def _refresh_today(self) -> None:
        st = self.s.get_statistics()
        cards = "".join([
            _stat_card("Total tasks", st["total"], ACCENT),
            _stat_card("Completed", st["completed"], "#059669"),
            _stat_card("Unfinished", st["unfinished"], "#D97706"),
            _stat_card("Overdue", st["overdue"], "#DC2626"),
            _stat_card("Events", st["events"], "#8B5CF6"),
        ])
        today_rows = "".join(
            f'<div style="padding:3px 0">{"☑" if t.is_completed() else "☐"} '
            f'{html.escape(t.get_summary())} <span style="opacity:.6">· {t.time_text()}</span></div>'
            for t in self.s.todays_tasks()) or _empty("Nothing planned for today. Enjoy! 🎉")
        event_rows = "".join(
            f'<div style="padding:3px 0">📅 {e.date:%a %d %b} · {html.escape(e.get_summary())}</div>'
            for e in self.s.upcoming_events()) or _empty("No upcoming events.")
        soon_rows = "".join(
            f'<div style="padding:3px 0">⏰ {html.escape(t.title)} '
            f'<span style="opacity:.6">· {t.starts_at():%a} {format_time(t.starts_at())}</span></div>'
            for t in self.s.tasks_due_soon()) or _empty("Nothing due in the next 24 hours.")
        self.today_html.value = (
            f'<div style="display:flex;gap:12px;flex-wrap:wrap;margin:6px 0">{cards}</div>'
            + _section("☀ Today's tasks", today_rows)
            + _section("📅 Upcoming events", event_rows)
            + _section("⏰ Due in the next 24 hours", soon_rows))

    def _on_bell(self, _btn) -> None:
        notes = self.rem.check_due()
        if not notes:
            self.bell_html.value = _empty("No reminders are due right now.")
            return
        self.bell_html.value = "".join(
            _section(f"🔔 {html.escape(n.title)}",
                     html.escape(n.message).replace("\n", "<br>")) for n in notes)

    def _goto_add(self) -> None:
        self.tabs.selected_index = T_ADD

    # ------------------------------------------------------------------ Tasks
    def _build_tasks(self) -> None:
        cats = [("All categories", None)] + [(c.name, c.id) for c in self.s.get_categories()]
        self.t_search = w.Text(placeholder="🔍 Search title or description", layout=w.Layout(width="260px"),
                               continuous_update=False)
        self.t_status = w.Dropdown(options=["All statuses"] + STATUSES, layout=w.Layout(width="150px"))
        self.t_prio = w.Dropdown(options=["All priorities"] + PRIORITIES, layout=w.Layout(width="150px"))
        self.t_cat = w.Dropdown(options=cats, layout=w.Layout(width="170px"))
        self.t_date = w.DatePicker(description="Day:", layout=w.Layout(width="230px"))
        self.t_hide = w.Checkbox(value=False, description="Hide completed", indent=False)
        for widget in (self.t_search, self.t_status, self.t_prio, self.t_cat, self.t_date, self.t_hide):
            widget.observe(lambda _c: self._refresh_tasks(), names="value")
        clear = w.Button(description="Clear filters", icon="times")
        clear.on_click(self._clear_task_filters)

        self.t_html = w.HTML()
        self.t_select = w.Dropdown(options=[("— choose a task to act on —", None)],
                                   layout=w.Layout(width="440px"))
        self.t_done = w.Button(description="Done", icon="check", button_style="success")
        self.t_prog = w.Button(description="In progress", icon="play", button_style="info")
        self.t_pend = w.Button(description="Pending", icon="undo")
        self.t_edit = w.Button(description="Edit", icon="pencil")
        self.t_del = w.Button(description="Delete", icon="trash", button_style="danger")
        self.t_done.on_click(lambda _: self._task_status("Completed"))
        self.t_prog.on_click(lambda _: self._task_status("In Progress"))
        self.t_pend.on_click(lambda _: self._task_status("Pending"))
        self.t_edit.on_click(lambda _: self._edit_selected("task", self.t_select.value))
        self.t_del.on_click(lambda _: self._ask_delete("task"))
        self.t_confirm_label = w.HTML()
        yes = w.Button(description="Yes, delete", button_style="danger", icon="trash")
        no = w.Button(description="Cancel")
        yes.on_click(lambda _: self._do_delete("task"))
        no.on_click(lambda _: self._hide_confirm("task"))
        self.t_confirm = w.HBox([self.t_confirm_label, yes, no], layout=w.Layout(display="none"))

        self.tasks_box = w.VBox([
            w.HBox([self.t_search, self.t_status, self.t_prio, self.t_cat]),
            w.HBox([self.t_date, self.t_hide, clear]),
            self.t_html,
            w.HTML("<b>Selected task:</b>"),
            self.t_select,
            w.HBox([self.t_done, self.t_prog, self.t_pend, self.t_edit, self.t_del]),
            self.t_confirm,
        ])

    def _clear_task_filters(self, _btn) -> None:
        self.t_search.value = ""
        self.t_status.value = "All statuses"
        self.t_prio.value = "All priorities"
        self.t_cat.value = None
        self.t_date.value = None
        self.t_hide.value = False

    def _filtered_tasks(self) -> list[Task]:
        tasks = self.s.get_tasks(
            keyword=self.t_search.value.strip() or None,
            status=None if self.t_status.value == "All statuses" else self.t_status.value,
            priority=None if self.t_prio.value == "All priorities" else self.t_prio.value,
            category_id=self.t_cat.value,
            item_date=self.t_date.value,
        )
        return [t for t in tasks if not (self.t_hide.value and t.is_completed())]

    def _refresh_tasks(self) -> None:
        tasks = self._filtered_tasks()
        if not tasks:
            self.t_html.value = _empty("No tasks match. Use the ➕ Add tab to create one.")
        else:
            rows = []
            for t in tasks:
                overdue = t.is_overdue()
                when = f"{t.date:%a %d %b} · {t.time_text()}"
                when_html = (f'<span style="color:#DC2626;font-weight:600">{when} ⚠ overdue</span>'
                             if overdue else when)
                repeat = f' <span title="Repeats {t.recurrence}">🔁</span>' if t.recurrence != "None" else ""
                rows.append(
                    f"<tr><td style='padding:6px 10px'><b>{html.escape(t.title)}</b>{repeat}</td>"
                    f"<td style='padding:6px 10px'>{when_html}</td>"
                    f"<td style='padding:6px 10px'>{_badge(t.priority, PRIORITY_COLORS[t.priority])}</td>"
                    f"<td style='padding:6px 10px'>{_badge(t.status, STATUS_COLORS[t.status])}</td>"
                    f"<td style='padding:6px 10px;opacity:.75'>{html.escape(self.s.get_category_name(t.category_id))}</td></tr>")
            head = "".join(f"<th style='text-align:left;padding:6px 10px'>{h}</th>"
                           for h in ["Task", "When", "Priority", "Status", "Category"])
            self.t_html.value = (f'<div style="{CARD}margin:8px 0;overflow-x:auto">'
                                 f'<table style="border-collapse:collapse;width:100%">'
                                 f'<tr style="border-bottom:1px solid rgba(128,128,128,.35)">{head}</tr>'
                                 f'{"".join(rows)}</table></div>'
                                 f'<div style="opacity:.6;font-size:12px">{len(tasks)} task(s)</div>')
        self._set_options(self.t_select, [("— choose a task to act on —", None)] + [
            (f"{t.date:%d %b} · {t.title}  [{t.status}]", t.id) for t in tasks])

    def _task_status(self, status: str) -> None:
        if self.t_select.value is None:
            return self._say("Choose a task from the list first.", "warn")
        try:
            nxt = self.s.set_task_status(self.t_select.value, status)
        except ValueError as error:
            return self._say(str(error), "err")
        self.refresh_all()
        self._say(f"Marked as {status}." + (f" Next repeat created for {nxt.date:%a %d %b}." if nxt else ""))

    # ------------------------------------------------------------------ Events
    def _build_events(self) -> None:
        self.e_past = w.Checkbox(value=False, description="Show past events", indent=False)
        self.e_past.observe(lambda _c: self._refresh_events(), names="value")
        self.e_html = w.HTML()
        self.e_select = w.Dropdown(options=[("— choose an event to act on —", None)],
                                   layout=w.Layout(width="440px"))
        edit = w.Button(description="Edit", icon="pencil")
        delete = w.Button(description="Delete", icon="trash", button_style="danger")
        edit.on_click(lambda _: self._edit_selected("event", self.e_select.value))
        delete.on_click(lambda _: self._ask_delete("event"))
        self.e_confirm_label = w.HTML()
        yes = w.Button(description="Yes, delete", button_style="danger", icon="trash")
        no = w.Button(description="Cancel")
        yes.on_click(lambda _: self._do_delete("event"))
        no.on_click(lambda _: self._hide_confirm("event"))
        self.e_confirm = w.HBox([self.e_confirm_label, yes, no], layout=w.Layout(display="none"))
        self.events_box = w.VBox([self.e_past, self.e_html, w.HTML("<b>Selected event:</b>"),
                                  self.e_select, w.HBox([edit, delete]), self.e_confirm])

    def _refresh_events(self) -> None:
        events = self.s.get_events(from_date=None if self.e_past.value else date.today())
        if not self.e_past.value:
            events = [e for e in events if e.is_upcoming() or e.date > date.today()]
        if not events:
            self.e_html.value = _empty("No events to show. Use the ➕ Add tab to create one.")
        else:
            rows = "".join(
                f"<tr><td style='padding:6px 10px'>{e.date:%a %d %b}</td>"
                f"<td style='padding:6px 10px'>{e.time_text()}</td>"
                f"<td style='padding:6px 10px'><b>{html.escape(e.title)}</b></td>"
                f"<td style='padding:6px 10px;opacity:.75'>{html.escape(e.location) or '—'}</td>"
                f"<td style='padding:6px 10px;opacity:.75'>{e.duration_minutes()} min</td></tr>"
                for e in events)
            head = "".join(f"<th style='text-align:left;padding:6px 10px'>{h}</th>"
                           for h in ["Date", "Time", "Event", "Location", "Length"])
            self.e_html.value = (f'<div style="{CARD}margin:8px 0;overflow-x:auto">'
                                 f'<table style="border-collapse:collapse;width:100%">'
                                 f'<tr style="border-bottom:1px solid rgba(128,128,128,.35)">{head}</tr>'
                                 f'{rows}</table></div>')
        self._set_options(self.e_select, [("— choose an event to act on —", None)] + [
            (f"{e.date:%d %b} {e.time_text()} · {e.title}", e.id) for e in events])

    # ------------------------------------------------------------------ delete flow (shared)
    def _selected_widgets(self, kind: str):
        return ((self.t_select, self.t_confirm, self.t_confirm_label) if kind == "task"
                else (self.e_select, self.e_confirm, self.e_confirm_label))

    def _ask_delete(self, kind: str) -> None:
        select, box, label = self._selected_widgets(kind)
        if select.value is None:
            return self._say(f"Choose a {kind} from the list first.", "warn")
        text = dict((v, l) for l, v in select.options)[select.value]
        label.value = f'<span style="padding:6px 10px">Delete <b>{html.escape(text)}</b>?</span>'
        box.layout.display = "flex"

    def _hide_confirm(self, kind: str) -> None:
        self._selected_widgets(kind)[1].layout.display = "none"

    def _do_delete(self, kind: str) -> None:
        select = self._selected_widgets(kind)[0]
        if kind == "task":
            self.s.delete_task(select.value)
        else:
            self.s.delete_event(select.value)
        self._hide_confirm(kind)
        self.refresh_all()
        self._say(f"{kind.capitalize()} deleted.")

    # ------------------------------------------------------------------ Calendar
    def _build_calendar(self) -> None:
        prev_btn = w.Button(icon="chevron-left", tooltip="Previous month", layout=w.Layout(width="45px"))
        next_btn = w.Button(icon="chevron-right", tooltip="Next month", layout=w.Layout(width="45px"))
        today_btn = w.Button(description="Today", icon="calendar-day")
        self.cal_pick = w.DatePicker(description="Day:", value=date.today(), layout=w.Layout(width="230px"))
        prev_btn.on_click(lambda _: self._shift_month(-1))
        next_btn.on_click(lambda _: self._shift_month(1))
        today_btn.on_click(lambda _: setattr(self.cal_pick, "value", date.today()))
        self.cal_pick.observe(self._on_cal_pick, names="value")
        self.cal_html = w.HTML()
        self.cal_day_html = w.HTML()
        self.cal_box = w.VBox([w.HBox([prev_btn, next_btn, today_btn, self.cal_pick]),
                               self.cal_html, self.cal_day_html])

    def _shift_month(self, step: int) -> None:
        m = self._cal_month
        self._cal_month = ((m + timedelta(days=32)) if step > 0 else (m - timedelta(days=1))).replace(day=1)
        self._refresh_calendar()

    def _on_cal_pick(self, change) -> None:
        if change["new"]:
            self._cal_month = change["new"].replace(day=1)
            self._refresh_calendar()

    def _refresh_calendar(self) -> None:
        y, m = self._cal_month.year, self._cal_month.month
        marked = self.s.dates_with_items(y, m)
        picked, today = self.cal_pick.value, date.today()
        head = "".join(f"<th style='padding:6px;opacity:.7'>{d}</th>"
                       for d in ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"])
        body = ""
        for week in calendar.Calendar(0).monthdatescalendar(y, m):
            body += "<tr>"
            for d in week:
                style = "text-align:center;padding:10px 4px;border-radius:8px;"
                if d.month != m:
                    style += "opacity:.3;"
                if d == picked:
                    style += f"background:{ACCENT};color:#fff;font-weight:700;"
                elif d == today:
                    style += f"border:2px solid {ACCENT};"
                dot = ('<div style="color:#F59E0B;font-size:10px;line-height:8px">●</div>'
                       if d in marked else '<div style="font-size:10px;line-height:8px">&nbsp;</div>')
                body += f"<td style='{style}'>{d.day}{dot}</td>"
            body += "</tr>"
        self.cal_html.value = (
            f'<div style="{CARD}padding:10px;max-width:480px;margin:8px 0">'
            f'<div style="text-align:center;font-size:18px;font-weight:700;margin-bottom:6px">'
            f'{self._cal_month:%B %Y}</div><table style="width:100%;border-collapse:separate;'
            f'border-spacing:3px"><tr>{head}</tr>{body}</table>'
            f'<div style="opacity:.6;font-size:12px;margin-top:4px">● = has tasks or events</div></div>')
        if picked:
            items = self.s.items_on(picked)
            rows = "".join(
                f'<div style="padding:3px 0">{"📅" if i.get_type() == "event" else "✅"} '
                f'<span style="opacity:.65">{i.time_text()}</span> · {html.escape(i.get_summary())}</div>'
                for i in items) or _empty("Nothing scheduled this day.")
            self.cal_day_html.value = _section(f"{picked:%A %d %B}", rows)
        else:
            self.cal_day_html.value = ""

    # ------------------------------------------------------------------ Add / edit form
    def _build_form(self) -> None:
        cats = [(c.name, c.id) for c in self.s.get_categories()]
        lay = w.Layout(width="420px")
        self.f_head = w.HTML("<h3 style='margin:4px 0'>➕ New item</h3>")
        self.f_kind = w.ToggleButtons(options=["Task", "Event"], value="Task")
        self.f_title = w.Text(description="Title", placeholder="e.g. Study OOP chapter 5", layout=lay)
        self.f_desc = w.Textarea(description="Notes", placeholder="optional", layout=w.Layout(width="420px", height="60px"))
        self.f_date = w.DatePicker(description="Date", value=date.today(), layout=w.Layout(width="260px"))
        today_btn = w.Button(description="Today", layout=w.Layout(width="70px"))
        tomorrow_btn = w.Button(description="Tomorrow", layout=w.Layout(width="90px"))
        today_btn.on_click(lambda _: setattr(self.f_date, "value", date.today()))
        tomorrow_btn.on_click(lambda _: setattr(self.f_date, "value", date.today() + timedelta(days=1)))
        self.f_start = w.Dropdown(description="Start", options=TIME_CHOICES, value="", layout=w.Layout(width="200px"))
        self.f_end = w.Dropdown(description="End", options=TIME_CHOICES, value="", layout=w.Layout(width="200px"))
        self.f_prio = w.ToggleButtons(description="Priority", options=PRIORITIES, value="Medium",
                                      style={"button_width": "80px"})
        self.f_cat = w.Dropdown(description="Category", options=cats, layout=w.Layout(width="260px"))
        self.f_rec = w.Dropdown(description="Repeat", options=RECURRENCES, layout=w.Layout(width="260px"))
        self.f_loc = w.Text(description="Location", placeholder="optional", layout=lay)
        self.f_rem = w.Dropdown(description="Reminder", options=[(l, v) for l, v in REMINDER_OPTIONS],
                                value=None, layout=w.Layout(width="300px"))
        self.f_save = w.Button(description="Save", icon="save", button_style="success")
        self.f_cancel = w.Button(description="Cancel edit", icon="times", layout=w.Layout(display="none"))
        self.f_save.on_click(self._on_save)
        self.f_cancel.on_click(lambda _: self._reset_form(go_back=True))
        self.f_kind.observe(lambda _c: self._toggle_kind(), names="value")
        self.f_start.observe(self._auto_end, names="value")

        self.task_only = w.VBox([self.f_prio, self.f_cat, self.f_rec])
        self.event_only = w.VBox([self.f_loc], layout=w.Layout(display="none"))
        self.form_box = w.VBox([
            self.f_head, self.f_kind, self.f_title, self.f_desc,
            w.HBox([self.f_date, today_btn, tomorrow_btn]),
            w.HBox([self.f_start, self.f_end]),
            self.task_only, self.event_only, self.f_rem,
            w.HBox([self.f_save, self.f_cancel]),
        ])

    def _toggle_kind(self) -> None:
        is_task = self.f_kind.value == "Task"
        self.task_only.layout.display = "flex" if is_task else "none"
        self.event_only.layout.display = "none" if is_task else "flex"

    def _auto_end(self, change) -> None:
        """Convenience: picking a start time proposes an end one hour later."""
        if change["new"] and not self.f_end.value:
            hour, minute = map(int, change["new"].split(":"))
            end = (datetime(2000, 1, 1, hour, minute) + timedelta(hours=1))
            if end.day == 1:
                self.f_end.value = f"{end:%H:%M}"

    def _reset_form(self, go_back: bool = False) -> None:
        kind = self._editing[0] if self._editing else None
        self._editing = None
        self.f_title.value = ""
        self.f_desc.value = ""
        self.f_loc.value = ""
        self.f_start.value = ""
        self.f_end.value = ""
        self.f_prio.value = "Medium"
        self.f_rec.value = "None"
        self.f_rem.value = None
        self.f_kind.disabled = False
        self.f_save.description = "Save"
        self.f_cancel.layout.display = "none"
        self.f_head.value = "<h3 style='margin:4px 0'>➕ New item</h3>"
        if go_back and kind:
            self.tabs.selected_index = T_TASKS if kind == "task" else T_EVENTS

    def _edit_selected(self, kind: str, item_id) -> None:
        if item_id is None:
            return self._say(f"Choose a {kind} from the list first.", "warn")
        item = self.s.get_task(item_id) if kind == "task" else self.s.get_event(item_id)
        self._reset_form()
        self.f_kind.value = "Task" if kind == "task" else "Event"
        self.f_kind.disabled = True
        self.f_title.value, self.f_desc.value, self.f_date.value = item.title, item.description, item.date
        self._set_time(self.f_start, item.start_time)
        self._set_time(self.f_end, item.end_time)
        minutes = self.s.get_reminder_minutes(item)
        self.f_rem.value = minutes if minutes in [v for _, v in REMINDER_OPTIONS] else None
        if kind == "task":
            self.f_prio.value, self.f_rec.value = item.priority, item.recurrence
            if item.category_id in [v for _, v in self.f_cat.options]:
                self.f_cat.value = item.category_id
        else:
            self.f_loc.value = item.location
        self._editing = (kind, item_id)
        self.f_save.description = "Save changes"
        self.f_cancel.layout.display = "inline-flex"
        self.f_head.value = f"<h3 style='margin:4px 0'>✏ Edit {kind}</h3>"
        self.tabs.selected_index = T_ADD
        self.msg.value = ""

    def _on_save(self, _btn) -> None:
        try:
            title = Validator.title(self.f_title.value)
            if self.f_date.value is None:
                raise ValueError("Please pick a date.")
            start = Validator.parse_time(self.f_start.value) if self.f_start.value else None
            end = Validator.parse_time(self.f_end.value) if self.f_end.value else None
            minutes = self.f_rem.value
            editing = self._editing
            conflicts, next_task = [], None

            if self.f_kind.value == "Task":
                if editing:
                    item = self.s.get_task(editing[1])
                    item.title, item.description, item.date = title, self.f_desc.value, self.f_date.value
                    item.set_times(start, end)
                    item.priority, item.category_id, item.recurrence = self.f_prio.value, self.f_cat.value, self.f_rec.value
                    next_task = self.s.update_task(item, minutes)
                else:
                    self.s.add_task(Task(title, self.f_date.value, start, end, self.f_desc.value,
                                         priority=self.f_prio.value, category_id=self.f_cat.value,
                                         recurrence=self.f_rec.value), minutes)
            else:
                if start is None or end is None:
                    raise ValueError("Events need both a start and an end time.")
                if editing:
                    item = self.s.get_event(editing[1])
                    item.title, item.description, item.date = title, self.f_desc.value, self.f_date.value
                    item.set_times(start, end)
                    item.location = self.f_loc.value
                else:
                    item = Event(title, self.f_date.value, start, end, self.f_desc.value, self.f_loc.value)
                conflicts = self.s.find_conflicts(item)
                if editing:
                    self.s.update_event(item, minutes)
                else:
                    self.s.add_event(item, minutes)
        except ValueError as error:
            return self._say(str(error), "err")

        went_back = bool(editing)
        self._reset_form(go_back=went_back)
        self.refresh_all()
        if conflicts:
            names = ", ".join(e.title for e in conflicts)
            self._say(f"Saved, but it overlaps with: {names}.", "warn")
        else:
            self._say(("Changes saved." if went_back else "Saved! Add another or open a tab to see it.")
                      + (f" Next repeat created for {next_task.date:%a %d %b}." if next_task else ""))

    # ------------------------------------------------------------------ Statistics
    def _build_stats(self) -> None:
        self.st_html = w.HTML()
        self.st_bar = w.IntProgress(min=0, max=100, description="Done:", bar_style="success",
                                    layout=w.Layout(width="420px"))
        self.st_out = w.Output()
        self.stats_box = w.VBox([self.st_html, self.st_bar, self.st_out])

    def _refresh_stats(self) -> None:
        import matplotlib.pyplot as plt
        st = self.s.get_statistics()
        self.st_html.value = ('<div style="display:flex;gap:12px;flex-wrap:wrap;margin:6px 0">'
                              + _stat_card("Completion", f'{st["completion_percentage"]}%', "#059669")
                              + _stat_card("High priority", st["high_priority"], "#DC2626")
                              + _stat_card("Overdue", st["overdue"], "#DC2626")
                              + _stat_card("Pending", st["pending"], "#D97706")
                              + _stat_card("In progress", st["in_progress"], ACCENT) + "</div>")
        self.st_bar.value = int(st["completion_percentage"])
        with self.st_out:
            clear_output(wait=True)
            if not st["total"]:
                display(w.HTML(_empty("Add some tasks to see charts here.")))
                return
            colors = {c: col for c, col in DEFAULT_CATEGORIES}
            fig, axes = plt.subplots(1, 2, figsize=(9, 3.4))
            axes[0].bar(["Pending", "In progress", "Completed"],
                        [st["pending"], st["in_progress"], st["completed"]],
                        color=[STATUS_COLORS["Pending"], STATUS_COLORS["In Progress"], STATUS_COLORS["Completed"]])
            axes[0].set_title("Tasks by status")
            axes[0].yaxis.get_major_locator().set_params(integer=True)
            names = list(st["by_category"])
            axes[1].pie(st["by_category"].values(), labels=names, autopct="%d",
                        colors=[colors.get(n, "#9CA3AF") for n in names])
            axes[1].set_title("Tasks by category")
            fig.tight_layout()
            display(fig)
            plt.close(fig)

    # ------------------------------------------------------------------ Settings
    def _build_settings(self) -> None:
        self.s_name = w.Text(description="Your name", value=self.s.user.name, layout=w.Layout(width="380px"))
        self.s_email = w.Text(description="Email", value=self.s.user.email, layout=w.Layout(width="380px"))
        save = w.Button(description="Save profile", icon="save", button_style="success")
        save.on_click(self._on_save_profile)
        self.settings_box = w.VBox([w.HTML("<h3 style='margin:4px 0'>👤 Profile</h3>"),
                                    self.s_name, self.s_email, save])

    def _on_save_profile(self, _btn) -> None:
        try:
            self.s.update_user(self.s_name.value, self.s_email.value)
        except ValueError as error:
            return self._say(str(error), "err")
        self._refresh_header()
        self._say("Profile saved.")


def seed_demo_data(scheduler) -> None:
    """Fill an empty database with a few example items so the UI isn't blank."""
    if scheduler.get_tasks() or scheduler.get_events():
        return
    ids = {c.name: c.id for c in scheduler.get_categories()}
    today = date.today()
    from datetime import time
    scheduler.add_task(Task("Study OOP chapter 5", today, time(9), time(10), "Inheritance and polymorphism",
                            priority="High", category_id=ids["Study"]), reminder_minutes=15)
    scheduler.add_task(Task("Go for a run", today, time(18), time(19), priority="Low",
                            category_id=ids["Exercise"], recurrence="Daily"))
    scheduler.add_task(Task("Submit assignment", today - timedelta(days=1), priority="High",
                            category_id=ids["Study"]))
    scheduler.add_task(Task("Buy groceries", today + timedelta(days=1), category_id=ids["Personal"]))
    scheduler.add_event(Event("Team meeting", today, time(10), time(11), location="Room 5"))
    scheduler.add_event(Event("Dentist", today + timedelta(days=3), time(14), time(15), location="Clinic"))
