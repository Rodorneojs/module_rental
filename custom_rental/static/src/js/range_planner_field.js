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
    this.disabled = new Set(); // NUEVO: días ocupados

    // -------- utilidades --------
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
    this.isDisabled = (dateObj) => this.disabled.has(this.fmt(dateObj));

    this._bufferUpdate = (val) => {
      if (typeof this.props.update === "function") this.props.update(val);
      else if (this.props.record && this.props.name) this.props.record.update({ [this.props.name]: val });
    };

    // Renderizar selección como "background events"
    this.renderSelected = () => {
      if (!this.calendar) return;
      this.calendar.batchRendering(() => {
        // Primero limpiamos TODO y volvemos a pintar disabled + selected
        this.calendar.removeAllEvents();
        // Disabled como background
        for (const day of this.disabled) {
          const end = this.addDaysISO(day, 1);
          this.calendar.addEvent({ start: day, end, allDay: true, display: "background", className: "busy-day" });
        }
        // Selección actual
        for (const day of this.selected) {
          const end = this.addDaysISO(day, 1);
          this.calendar.addEvent({ start: day, end, allDay: true, display: "background", color: SELECT_COLOR });
        }
      });
    };

    // -------- ciclo de vida --------
    onWillStart(async () => {
      await loadCSS("/custom_rental/static/src/lib/fullcalendar/main.min.css");
      await loadJS("/custom_rental/static/src/lib/fullcalendar/index.global.min.js");
    });

    onWillUpdateProps((next) => {
      // 1) CSV seleccionado
      const newSet = new Set(this.parseCSV(next.value));
      const sameSel = newSet.size === this.selected.size && Array.from(newSet).every((d) => this.selected.has(d));
      if (!sameSel) {
        this.selected = newSet;
        if (this.inputRef.el) this.inputRef.el.value = this.toCSV();
      }
      // 2) Fechas bloqueadas (pueden cambiar si el user toca horas/temporada/embarcación)
      const nextDisabledJSON = (next?.record?.data?.disabled_dates_json || "[]");
      let nextDisabled = new Set();
      try { nextDisabled = new Set(JSON.parse(nextDisabledJSON)); } catch (e) {}
      const sameDisabled = nextDisabled.size === this.disabled.size && Array.from(nextDisabled).every(d => this.disabled.has(d));
      if (!sameDisabled) {
        this.disabled = nextDisabled;
      }
      // Re-pintar si cambió algo
      if (this.calendar) this.renderSelected();
    });

    onMounted(() => {
      const calEl = this.calRef.el;
      const inputEl = this.inputRef.el;
      if (!calEl || !inputEl) return;

      const FC = window.FullCalendar;
      if (!FC?.Calendar) return;

      // Inicial: CSV seleccionado + JSON disabled
      this.parseCSV(this.props.value).forEach((d) => this.selected.add(d));
      inputEl.value = this.toCSV();
      try {
        this.disabled = new Set(JSON.parse(this.props?.record?.data?.disabled_dates_json || "[]"));
      } catch (e) { this.disabled = new Set(); }

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

        // Bloqueo por UI: rangos seleccionados NO pueden incluir días ocupados
        selectAllow: (info) => {
          for (let d = new Date(info.start); d < info.end; d.setDate(d.getDate() + 1)) {
            if (this.isDisabled(d)) return false;
          }
          return true;
        },

        dayCellDidMount: ({ el, date }) => {
          el.style.cursor = "pointer";
          el.style.userSelect = "none";
          if (this.isDisabled(date)) {
            el.classList.add("fc-disabled-day");
            el.setAttribute("title", "Día ya ocupado");
            el.style.pointerEvents = "none"; // hard block de clicks
          }
        },

        select: (info) => {
          // Multi-arrastre (ya filtrado por selectAllow)
          const s = info.startStr.slice(0, 10);
          const e = info.endStr.slice(0, 10);
          let changed = false;
          for (let cur = s; cur < e; cur = this.addDaysISO(cur, 1)) {
            if (!this.disabled.has(cur)) { this.toggleDay(cur); changed = true; }
          }
          this.calendar.unselect();
          if (changed) {
            this.renderSelected();
            inputEl.value = this.toCSV();
            this._bufferUpdate(inputEl.value);
          }
        },

        dateClick: (info) => {
          // Click simple en día: ignorar si es disabled
          if (this.disabled.has(info.dateStr)) return;
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
