/** @odoo-module **/

import { Component, onMounted, onWillUnmount, onWillStart, onWillUpdateProps, useRef } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { loadJS, loadCSS } from "@web/core/assets";
import { useService } from "@web/core/utils/hooks";

const SELECT_COLOR = "#875A7B";
const HIGHLIGHT_COLOR = "rgba(135, 90, 123, 0.18)";

class RangePlannerField extends Component {
  static template = "custom_rental.RangePlannerField";
  static props = { ...standardFieldProps };
  static supportedTypes = ["char", "text"];

  setup() {
    this.orm = useService("orm");

    this.calRef = useRef("calendar");
    this.inputRef = useRef("input");

    this.calendar = null;
    this.selected = new Set();

    this.parseCSV = (txt) => (txt || "").split(",").map(s => s.trim()).filter(Boolean);
    this.fmt = (d) => d.toISOString().slice(0, 10);
    this.addDaysISO = (iso, n) => {
      const [y, m, d] = iso.split("-").map(Number);
      const dt = new Date(y, m - 1, d);
      dt.setHours(12, 0, 0, 0);
      dt.setDate(dt.getDate() + n);
      return this.fmt(dt);
    };
    this.forEachISOInRange = (s, e, cb) => { let cur = s; while (cur < e) { cb(cur); cur = this.addDaysISO(cur, 1); } };
    this.toCSV = () => Array.from(this.selected).sort().join(", ");
    this.toggleDay = (iso) => this.selected.has(iso) ? this.selected.delete(iso) : this.selected.add(iso);

    this._bufferUpdate = (val) => {
      if (typeof this.props.update === "function") this.props.update(val);
      else if (this.props.record && this.props.name) this.props.record.update({ [this.props.name]: val });
    };

    onWillStart(async () => {
      await loadCSS("/custom_rental/static/src/lib/fullcalendar/main.min.css");
      await loadJS("/custom_rental/static/src/lib/fullcalendar/index.global.min.js");
    });

    onWillUpdateProps((next) => {
      const newSet = new Set(this.parseCSV(next.value));
      const same = newSet.size === this.selected.size && Array.from(newSet).every((d) => this.selected.has(d));
      if (!same) {
        this.selected = newSet;
        if (this.inputRef.el) this.inputRef.el.value = this.toCSV();
        if (this.calendar) this.renderSelected();
      }
    });

    this.renderSelected = () => {
      if (!this.calendar) return;
      this.calendar.batchRendering(() => {
        this.calendar.removeAllEvents();
        for (const day of this.selected) {
          const end = this.addDaysISO(day, 1);
          this.calendar.addEvent({ start: day, end, allDay: true, display: "background", color: SELECT_COLOR });
        }
      });
    };

    onMounted(() => {
      const calEl = this.calRef.el;
      const inputEl = this.inputRef.el;
      if (!calEl || !inputEl) return;

      const FC = window.FullCalendar;
      if (!FC?.Calendar) return;

      // inicial CSV → selección
      this.parseCSV(this.props.value).forEach((d) => this.selected.add(d));
      inputEl.value = this.toCSV();

      this.calendar = new FC.Calendar(calEl, {
        timeZone: "local",
        now: () => { const n = new Date(); n.setHours(12,0,0,0); return n; },
        initialView: "multiMonthYear",
        locale: "es",
        selectable: true,
        unselectAuto: false,
        selectMirror: true,
        selectMinDistance: 8,
        longPressDelay: 0,
        selectLongPressDelay: 0,
        dayMaxEvents: true,
        eventInteractive: false,
        headerToolbar: { left: "today prev,next", center: "title", right: "multiMonthYear,dayGridMonth,timeGridWeek,dayGridDay,listMonth" },
        dayCellDidMount: ({ el }) => { el.style.cursor = "pointer"; el.style.userSelect = "none"; },
        select: (info) => {
          const s = info.startStr.slice(0, 10);
          const e = info.endStr.slice(0, 10);
          this.forEachISOInRange(s, e, (iso) => this.toggleDay(iso));
          this.calendar.unselect();
          this.renderSelected();
          inputEl.value = this.toCSV();
          this._bufferUpdate(inputEl.value); // el formulario queda sincronizado
        },
        dateClick: (info) => {
          this.toggleDay(info.dateStr);
          this.renderSelected();
          inputEl.value = this.toCSV();
          this._bufferUpdate(inputEl.value);
        },
      });

      calEl.style.setProperty("--fc-highlight-color", HIGHLIGHT_COLOR);
      this.calendar.render();
      this.renderSelected();
    });

    onWillUnmount(() => this.calendar?.destroy());
  }
}

registry.category("fields").add("range_planner", { component: RangePlannerField });
export default RangePlannerField;
